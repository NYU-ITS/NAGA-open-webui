"""Coordinated file, Knowledge-membership, vector, and storage cleanup."""

import logging
import time
from typing import Dict, Optional, Tuple

from open_webui.internal.db import get_db
from open_webui.models.files import File, Files
from open_webui.models.knowledge import Knowledge, Knowledges
from open_webui.retrieval.vector.connector import VECTOR_DB_CLIENT
from open_webui.storage.provider import Storage


log = logging.getLogger(__name__)


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
    """Remove one file and all non-excluded memberships and projections."""

    details = {
        "knowledge_bases_updated": [],
        "vector_db_cleaned": False,
        "file_collection_deleted": False,
        "sql_deleted": False,
        "physical_file_deleted": False,
        "errors": [],
    }

    delete_file_projection = _transactional_vector_delete(
        "delete_file_projection"
    )
    if delete_file_projection is not None:
        try:
            with get_db() as db:
                # File-first is the common lock order for deletion and ingestion.
                file = (
                    db.query(File)
                    .filter(File.id == file_id)
                    .with_for_update()
                    .first()
                )
                if file is None:
                    details["errors"].append("File not found")
                    return False, details

                storage_path = file.path
                candidate_ids = {
                    str(row.id)
                    for row in db.query(Knowledge).all()
                    if file_id in _file_ids(row.data)
                }
                # Adds use the same File-first lock order. Locking the current
                # candidates is therefore sufficient and avoids a table-wide
                # Knowledge lock during deletion.
                knowledge_rows = (
                    db.query(Knowledge)
                    .filter(Knowledge.id.in_(sorted(candidate_ids)))
                    .order_by(Knowledge.id)
                    .with_for_update()
                    .all()
                    if candidate_ids
                    else []
                )
                affected_rows = [
                    row
                    for row in knowledge_rows
                    if row.id != exclude_knowledge_id
                    and file_id in _file_ids(row.data)
                ]
                for knowledge in affected_rows:
                    data = dict(knowledge.data or {})
                    data["file_ids"] = [
                        candidate
                        for candidate in _file_ids(data)
                        if candidate != file_id
                    ]
                    knowledge.data = data
                    knowledge.updated_at = int(time.time())
                    delete_file_projection(
                        collection_name=knowledge.id,
                        file_id=file_id,
                        session=db,
                    )
                    details["knowledge_bases_updated"].append(knowledge.id)

                delete_file_projection(
                    collection_name=f"file-{file_id}",
                    file_id=file_id,
                    session=db,
                )
                db.delete(file)
                db.commit()

            details["vector_db_cleaned"] = True
            details["file_collection_deleted"] = True
            details["sql_deleted"] = True
            if delete_physical_file and storage_path:
                try:
                    Storage.delete_file(storage_path)
                    details["physical_file_deleted"] = True
                except Exception:
                    log.exception(
                        "Physical file cleanup failed after database deletion | file=%s",
                        file_id,
                    )
                    details["errors"].append("Physical file cleanup failed")
            elif not delete_physical_file:
                details["physical_file_deleted"] = None
            else:
                details["errors"].append("Physical file path is missing")
            return True, details
        except Exception:
            log.exception("Atomic file cleanup failed | file=%s", file_id)
            details["errors"].append("Database file cleanup failed")
            return False, details

    # Non-pgvector stores cannot participate in the primary transaction. Do not
    # hide memberships or delete the File row unless every vector deletion wins.
    file = Files.get_file_by_id(file_id)
    if file is None:
        details["errors"].append("File not found")
        return False, details
    knowledge_bases = [
        knowledge
        for knowledge in Knowledges.get_knowledge_bases_by_file_id(file_id)
        if knowledge.id != exclude_knowledge_id
    ]
    try:
        for knowledge in knowledge_bases:
            VECTOR_DB_CLIENT.delete(
                collection_name=knowledge.id,
                filter={"file_id": file_id},
            )
        VECTOR_DB_CLIENT.delete_collection(collection_name=f"file-{file_id}")
    except Exception:
        log.exception("Legacy vector cleanup failed | file=%s", file_id)
        details["errors"].append("Vector database cleanup failed")
        return False, details

    details["vector_db_cleaned"] = True
    details["file_collection_deleted"] = True
    for knowledge in knowledge_bases:
        data = dict(knowledge.data or {})
        data["file_ids"] = [
            candidate for candidate in _file_ids(data) if candidate != file_id
        ]
        if not Knowledges.update_knowledge_data_by_id(knowledge.id, data):
            details["errors"].append("Knowledge membership cleanup failed")
            return False, details
        details["knowledge_bases_updated"].append(knowledge.id)

    if not Files.delete_file_by_id(file_id):
        details["errors"].append("Database file cleanup failed")
        return False, details
    details["sql_deleted"] = True
    if delete_physical_file and file.path:
        try:
            Storage.delete_file(file.path)
            details["physical_file_deleted"] = True
        except Exception:
            log.exception("Physical file cleanup failed | file=%s", file_id)
            details["errors"].append("Physical file cleanup failed")
    elif not delete_physical_file:
        details["physical_file_deleted"] = None
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
