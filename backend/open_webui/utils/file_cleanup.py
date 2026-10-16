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
from open_webui.utils.file_references import chat_file_ids


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
            if task.kind == "storage":
                Storage.delete_file(task.storage_path)
            elif task.kind == "orphan":
                success, details = cleanup_file_completely(
                    task.file_id, only_if_unreferenced=True
                )
                # A storage task has taken responsibility after SQL deletion.
                if not success and not details.get("storage_cleanup_pending"):
                    raise RuntimeError("Orphan file cleanup failed")
            else:
                raise ValueError("Unknown file cleanup task kind")
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


def process_file_cleanup_tasks(task_ids) -> None:
    """Attempt committed work immediately; failures remain queued for retry."""
    for task_id in task_ids:
        try:
            process_file_cleanup_task(task_id)
        except Exception:
            log.exception("Could not process file cleanup task | task=%s", task_id)


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
    process_file_cleanup_tasks(task_ids)


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
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, str) and value]


def _file_is_referenced(db, file_id: str) -> bool:
    from open_webui.models.chats import Chat

    if any(file_id in _file_ids(row.data) for row in db.query(Knowledge.data)):
        return True
    return any(file_id in chat_file_ids(row.chat) for row in db.query(Chat.chat))


def cleanup_knowledge_collection(
    knowledge_id: str,
    *,
    delete_knowledge: bool = False,
) -> bool:
    """Delete the collection and durably schedule its now-unreferenced uploads."""
    task_ids = []
    delete_collection_rows = _transactional_vector_delete("delete_collection_rows")
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
            if delete_collection_rows is not None:
                delete_collection_rows(collection_name=knowledge_id, session=db)
            else:
                VECTOR_DB_CLIENT.delete_collection(collection_name=knowledge_id)
            if delete_knowledge:
                task_ids = [
                    enqueue_file_cleanup(db, file_id)
                    for file_id in sorted(set(_file_ids(knowledge.data)))
                ]
                db.delete(knowledge)
            else:
                data = dict(knowledge.data or {})
                data["file_ids"] = []
                knowledge.data = data
                knowledge.updated_at = int(time.time())
            db.commit()
    except Exception:
        log.exception("Knowledge collection cleanup failed | knowledge=%s", knowledge_id)
        return False

    process_file_cleanup_tasks(task_ids)
    return True


def cleanup_file_completely(
    file_id: str,
    exclude_knowledge_id: Optional[str] = None,
    delete_physical_file: bool = True,
    *,
    only_if_unreferenced: bool = False,
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
                if only_if_unreferenced:
                    return True, details
                details["errors"].append("File not found")
                return False, details

            if only_if_unreferenced and _file_is_referenced(db, file_id):
                details["preserved_shared_file"] = True
                return True, details

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
