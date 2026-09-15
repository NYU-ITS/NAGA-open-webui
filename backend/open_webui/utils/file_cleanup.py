"""Coordinated file, Knowledge-membership, vector, and storage cleanup."""

import asyncio
import logging
import time
from typing import Dict, Optional, Tuple

from open_webui.internal.db import get_db
from open_webui.models.files import File
from open_webui.models.file_cleanup import FileCleanupTask, enqueue_file_cleanup
from open_webui.models.embeddings import RagChunk
from open_webui.models.knowledge import Knowledge, Knowledges
from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT
from open_webui.storage.provider import Storage


log = logging.getLogger(__name__)


def process_file_cleanup_task(task_id: str) -> bool:
    """Retry a durable intent; a row lock prevents duplicate work across pods."""
    with get_db() as db:
        task = (
            db.query(FileCleanupTask)
            .filter(FileCleanupTask.id == task_id)
            .with_for_update(skip_locked=True)
            .first()
        )
        if task is None:
            return False
        try:
            if task.kind != "storage":
                raise ValueError("Unknown file cleanup task kind")
            Storage.delete_file(task.storage_path)
        except Exception as error:
            log.exception("File cleanup deferred | file=%s", task.file_id)
            task.attempts += 1
            # Persist only the error type: provider errors can contain credentials.
            task.last_error = type(error).__name__
            task.next_attempt_at = int(time.time()) + min(
                3600, 30 * 2 ** min(task.attempts - 1, 7)
            )
            db.commit()
            return False
        db.delete(task)
        db.commit()
        return True


def retry_pending_file_cleanup() -> None:
    with get_db() as db:
        task_ids = [
            row.id
            for row in db.query(FileCleanupTask.id)
            .filter(FileCleanupTask.next_attempt_at <= int(time.time()))
            .order_by(FileCleanupTask.next_attempt_at, FileCleanupTask.id)
            .limit(100)
            .all()
        ]
    for task_id in task_ids:
        try:
            process_file_cleanup_task(task_id)
        except Exception:
            log.exception("Could not process file cleanup task | task=%s", task_id)


async def periodic_file_cleanup() -> None:
    """Run without Redis, including immediately after a process restart."""
    while True:
        try:
            await asyncio.to_thread(retry_pending_file_cleanup)
        except Exception:
            log.exception("File cleanup reconciliation failed")
        await asyncio.sleep(30)


def _transactional_vector_delete(name: str):
    operation = getattr(VECTOR_DB_CLIENT, name, None)
    return operation if callable(operation) else None


def _file_ids(data) -> list[str]:
    values = data.get("file_ids", []) if isinstance(data, dict) else []
    return list(values) if isinstance(values, list) else []


def cleanup_knowledge_collection(
    knowledge_id: str,
    *,
    delete_knowledge: bool = False,
) -> bool:
    """Clear a Knowledge collection, atomically when pgvector is primary-backed."""

    delete_collection_rows = _transactional_vector_delete("delete_collection_rows")
    if delete_collection_rows is None:
        # Legacy vector stores cannot join the primary transaction. Preserve the
        # safer ordering: vector cleanup must succeed before membership is hidden.
        try:
            VECTOR_DB_CLIENT.delete_collection(collection_name=knowledge_id)
            if delete_knowledge:
                return Knowledges.delete_knowledge_by_id(id=knowledge_id)
            knowledge = Knowledges.get_knowledge_by_id(id=knowledge_id)
            if knowledge is None:
                return False
            data = dict(knowledge.data or {})
            data["file_ids"] = []
            return bool(
                Knowledges.update_knowledge_data_by_id(
                    id=knowledge_id,
                    data=data,
                )
            )
        except Exception:
            log.exception(
                "Knowledge collection cleanup failed | knowledge=%s",
                knowledge_id,
            )
            return False

    try:
        with get_db() as db:
            knowledge = (
                db.query(Knowledge)
                .filter(Knowledge.id == knowledge_id)
                .with_for_update()
                .first()
            )
            if knowledge is None:
                return False
            delete_collection_rows(collection_name=knowledge_id, session=db)
            if delete_knowledge:
                db.delete(knowledge)
            else:
                data = dict(knowledge.data or {})
                data["file_ids"] = []
                knowledge.data = data
                knowledge.updated_at = int(time.time())
            db.commit()
        return True
    except Exception:
        log.exception(
            "Atomic knowledge collection cleanup failed | knowledge=%s",
            knowledge_id,
        )
        return False


def cleanup_file_completely(
    file_id: str,
    exclude_knowledge_id: Optional[str] = None,
    delete_physical_file: bool = True,
) -> Tuple[bool, Dict]:
    """Remove content and commit a storage deletion intent with the File deletion."""

    details = {
        "knowledge_bases_updated": [],
        "vector_db_cleaned": False,
        "file_collection_deleted": False,
        "sql_deleted": False,
        "physical_file_deleted": False,
        "storage_cleanup_pending": False,
        "errors": [],
    }
    delete_file_projection = _transactional_vector_delete("delete_file_projection")
    storage_task_id = None
    try:
        with get_db() as db:
            # Ingestion and membership writers also lock File before Knowledge.
            file = (
                db.query(File)
                .filter(File.id == file_id)
                .with_for_update()
                .first()
            )
            if file is None:
                details["errors"].append("File not found")
                return False, details

            candidate_ids = {
                row.id
                for row in db.query(Knowledge).all()
                if file_id in _file_ids(row.data)
            }
            knowledge_rows = (
                db.query(Knowledge)
                .filter(Knowledge.id.in_(sorted(candidate_ids)))
                .order_by(Knowledge.id)
                .populate_existing()
                .with_for_update()
                .all()
                if candidate_ids
                else []
            )
            for knowledge in knowledge_rows:
                if knowledge.id == exclude_knowledge_id:
                    continue
                if delete_file_projection is not None:
                    delete_file_projection(
                        collection_name=knowledge.id, file_id=file_id, session=db
                    )
                else:
                    # External vector stores must succeed before committing SQL.
                    VECTOR_DB_CLIENT.delete(
                        collection_name=knowledge.id, filter={"file_id": file_id}
                    )
                data = dict(knowledge.data or {})
                data["file_ids"] = [
                    candidate for candidate in _file_ids(data) if candidate != file_id
                ]
                knowledge.data = data
                knowledge.updated_at = int(time.time())
                details["knowledge_bases_updated"].append(knowledge.id)

            if delete_file_projection is not None:
                # Include old/staged projections that no longer have a membership.
                VECTOR_DB_CLIENT.delete_file_rows(file_id=file_id, session=db)
            else:
                VECTOR_DB_CLIENT.delete_collection(collection_name=f"file-{file_id}")
            db.query(RagChunk).filter(RagChunk.file_id == file_id).delete(
                synchronize_session=False
            )
            if delete_physical_file and file.path:
                storage_task_id = enqueue_file_cleanup(
                    db, file_id, kind="storage", storage_path=file.path
                )
            db.delete(file)
            db.commit()

        details["vector_db_cleaned"] = True
        details["file_collection_deleted"] = True
        details["sql_deleted"] = True
    except Exception:
        log.exception("File content cleanup failed | file=%s", file_id)
        details["errors"].append("File content cleanup failed")
        return False, details

    if storage_task_id:
        try:
            details["physical_file_deleted"] = process_file_cleanup_task(storage_task_id)
        except Exception:
            log.exception("Storage cleanup remains queued | file=%s", file_id)
        if not details["physical_file_deleted"]:
            details["storage_cleanup_pending"] = True
            details["errors"].append("Storage deletion pending; automatic retry scheduled")
            return False, details
    elif not delete_physical_file:
        details["physical_file_deleted"] = None
    else:
        # Text-only files have no original upload to remove.
        details["physical_file_deleted"] = True
    return True, details


def cleanup_file_from_knowledge_only(
    file_id: str,
    knowledge_id: str,
) -> Tuple[bool, Dict]:
    """Remove one current membership and its projection."""

    details = {
        "vector_db_cleaned": False,
        "knowledge_base_updated": False,
        "errors": [],
    }
    delete_file_projection = _transactional_vector_delete(
        "delete_file_projection"
    )
    if delete_file_projection is not None:
        try:
            with get_db() as db:
                file = (
                    db.query(File)
                    .filter(File.id == file_id)
                    .with_for_update()
                    .first()
                )
                candidate_ids = {
                    str(row.id)
                    for row in db.query(Knowledge).all()
                    if file_id in _file_ids(row.data)
                }
                candidate_ids.add(str(knowledge_id))
                knowledge_rows = (
                    db.query(Knowledge)
                    .filter(Knowledge.id.in_(sorted(candidate_ids)))
                    .order_by(Knowledge.id)
                    .with_for_update()
                    .all()
                )
                knowledge = next(
                    (row for row in knowledge_rows if row.id == knowledge_id),
                    None,
                )
                if file is None or knowledge is None:
                    details["errors"].append("File or knowledge base not found")
                    return False, details
                data = dict(knowledge.data or {})
                data["file_ids"] = [
                    candidate
                    for candidate in _file_ids(data)
                    if candidate != file_id
                ]
                knowledge.data = data
                knowledge.updated_at = int(time.time())
                delete_file_projection(
                    collection_name=knowledge_id,
                    file_id=file_id,
                    session=db,
                )
                db.commit()
            details["vector_db_cleaned"] = True
            details["knowledge_base_updated"] = True
            return True, details
        except Exception:
            log.exception(
                "Atomic membership cleanup failed | file=%s | knowledge=%s",
                file_id,
                knowledge_id,
            )
            details["errors"].append("Knowledge membership cleanup failed")
            return False, details

    try:
        VECTOR_DB_CLIENT.delete(
            collection_name=knowledge_id,
            filter={"file_id": file_id},
        )
        details["vector_db_cleaned"] = True
    except Exception:
        log.exception("Legacy membership vector cleanup failed")
        details["errors"].append("Vector database cleanup failed")
        return False, details

    knowledge = Knowledges.get_knowledge_by_id(knowledge_id)
    if knowledge is None:
        details["errors"].append("Knowledge base not found")
        return False, details
    data = dict(knowledge.data or {})
    data["file_ids"] = [
        candidate for candidate in _file_ids(data) if candidate != file_id
    ]
    details["knowledge_base_updated"] = bool(
        Knowledges.update_knowledge_data_by_id(knowledge_id, data)
    )
    if not details["knowledge_base_updated"]:
        details["errors"].append("Knowledge membership cleanup failed")
    return (
        details["vector_db_cleaned"] and details["knowledge_base_updated"],
        details,
    )
