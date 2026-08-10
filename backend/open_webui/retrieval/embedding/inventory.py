"""Deterministic, deduplicated reindex file inventory for one admin (Spec 02).

``build_reindex_inventory`` produces the frozen snapshot of every physical file
a reindex operation must rebuild for one admin: knowledge-base files plus
applicable chat uploads, deduplicated, with every collection membership the
worker needs to reconstruct each required vector projection.

Ownership is resolved through the repository's RBAC-group-first admin rules
(never the uploader email):

- A knowledge base resolves to the admins of the groups named in its
  ``access_control.read/write.group_ids`` when any groups are assigned; with no
  assigned groups it resolves through the knowledge owner's stable-ID admin
  inheritance (the owner if admin, else the owner's single group-owner admin).
- A chat resolves through ``chat.group_id`` (the owning group's admin) when a
  group is set, else through ``chat.user_id`` the same way.

Sources whose governing admin cannot be resolved to exactly one admin are
fatal: the inventory is refused and no partial job may be created (Spec 02
"Error Semantics", user-confirmed stricter reading). A source that references
no files is never resolved for governance and contributes nothing (rule 7). A
file referenced by sources governed by more than one distinct admin is
rejected as ambiguous, and a governed reference to a missing ``file`` row is
fatal because ``embedding_job_files.file_id`` requires a valid file. Missing-
file and ambiguity checks apply only to files governed by the requested admin;
another admin's broken data never blocks this admin's model change.

Malformed structures -- a ``data.file_ids`` that is not a list, a chat payload
whose messages/files containers are not dict/list, or wrong-typed
``access_control`` permission rules -- raise a structured malformed-reference
error; silently ignoring them would change ownership or drop files.

Exact chat reference path (mirrors the Phase 1 backfill migration and the
frontend payload): ``chat.chat["history"]["messages"][*]["files"][*]`` where
``messages`` is a dict keyed by message id or a list, and a files entry is an
uploaded file when its ``type`` is not one of ``collection``/``web_search``/
``text`` and it carries an ``id``.

The result is sorted by ``file_id`` and every nested collection id is sorted,
so persistence (Spec 03/04) produces a deterministic snapshot. ``ReindexFile``
round-trips through JSON so the job repository can persist the snapshot
including content hash and update timestamp (used by Spec 11's
``REINDEX_SOURCE_CHANGED`` staleness check).
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from open_webui.internal.db import get_db
from open_webui.models.chats import Chat
from open_webui.models.files import File
from open_webui.models.groups import Group
from open_webui.models.knowledge import Knowledge
from open_webui.models.users import User
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_ADMIN_UNRESOLVED,
    EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
    EMBEDDING_INVENTORY_AMBIGUOUS_SOURCE,
    EMBEDDING_INVENTORY_AMBIGUOUS_ADMIN,
    EMBEDDING_INVENTORY_MISSING_FILE,
    EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
)

log = logging.getLogger(__name__)

# Source context identifiers carried on every inventory item.
SOURCE_KNOWLEDGE = "knowledge"
SOURCE_CHAT_UPLOAD = "chat_upload"

# File entry types in a chat payload that are not uploaded files.
_CHAT_NON_FILE_TYPES = frozenset({"collection", "web_search", "text"})


@dataclass(frozen=True)
class ReindexFile:
    """One physical file in a reindex snapshot with all collection memberships.

    Contains only stable IDs and membership data; no credentials, model names,
    or provider details. ``knowledge_collection_ids`` are the knowledge base
    ids whose vector collections contain this file; the worker writes every
    knowledge collection plus ``file_collection_name`` (``file-{file_id}``).
    ``content_hash`` and ``updated_at`` are captured at snapshot time so Spec
    11 can detect stale source content.
    """

    file_id: str
    source_contexts: frozenset[str]
    knowledge_collection_ids: tuple[str, ...]
    file_collection_name: str
    admin_id: str
    content_hash: Optional[str] = None
    updated_at: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Deterministic JSON-safe snapshot of this inventory item."""
        return {
            "file_id": self.file_id,
            "source_contexts": sorted(self.source_contexts),
            "knowledge_collection_ids": list(self.knowledge_collection_ids),
            "file_collection_name": self.file_collection_name,
            "admin_id": self.admin_id,
            "content_hash": self.content_hash,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReindexFile":
        """Rebuild an inventory item from a previously persisted snapshot."""
        return cls(
            file_id=data["file_id"],
            source_contexts=frozenset(data.get("source_contexts", [])),
            knowledge_collection_ids=tuple(data.get("knowledge_collection_ids", [])),
            file_collection_name=data["file_collection_name"],
            admin_id=data["admin_id"],
            content_hash=data.get("content_hash"),
            updated_at=data.get("updated_at"),
        )


@dataclass(frozen=True)
class ReindexAdminResolver:
    """Shared group-first governance resolver for reindex-related reads.

    Build this once per database session so callers that inspect several
    knowledge bases reuse the same user and group snapshot as the inventory
    builder. Resolution errors intentionally remain ``EmbeddingError`` values
    so each caller can choose whether to fail the operation or present an
    unavailable status for one source.
    """

    roles: dict[str, str]
    group_admins: dict[str, Optional[str]]
    user_group_ids: dict[str, set[str]]

    def resolve_knowledge(self, knowledge: Knowledge) -> str:
        return _resolve_knowledge_admin(
            knowledge,
            self.roles,
            self.group_admins,
            self.user_group_ids,
        )

    def resolve_chat(self, chat: Chat) -> str:
        return _resolve_chat_admin(
            chat,
            self.roles,
            self.group_admins,
            self.user_group_ids,
        )


def build_reindex_admin_resolver(db) -> ReindexAdminResolver:
    """Build the authoritative admin resolver from one database snapshot."""
    roles = _load_roles(db)
    groups = _load_groups(db)
    return ReindexAdminResolver(
        roles=roles,
        group_admins=_build_group_admins(groups, roles),
        user_group_ids=_build_user_group_index(groups),
    )


def build_reindex_inventory(admin_id: str, db=None) -> list[ReindexFile]:
    """Build the deterministic reindex inventory for one admin.

    Args:
        admin_id: Stable user id of the responsible admin.
        db: Optional caller-owned session. When provided, all reads use that
            session and nothing is committed (read-only); otherwise a session
            is opened and closed here.

    Returns:
        Inventory items sorted by ``file_id``.

    Raises:
        EmbeddingError: On unresolvable or ambiguous source governance, on a
            file governed by more than one distinct admin, on a governed
            reference to a missing ``file`` row, or on a malformed
            knowledge/chat reference. No partial inventory is returned.
    """
    if db is None:
        with get_db() as session:
            _assert_admin(session, admin_id)
            return _build_inventory(session, admin_id)
    _assert_admin(db, admin_id)
    return _build_inventory(db, admin_id)


def _assert_admin(db, admin_id: str) -> None:
    """Verify ``admin_id`` is a real admin using the caller's session.

    Mirrors ``resolution.resolve_admin_for_admin_id`` (stable-ID admin
    resolution) but reads through the same session as the inventory so a
    caller-owned transaction sees one consistent snapshot.
    """
    row = db.query(User).filter(User.id == admin_id).first()
    if row is None:
        raise EmbeddingError(
            EMBEDDING_ADMIN_UNRESOLVED,
            detail=f"Admin {admin_id} not found.",
        )
    if row.role != "admin":
        raise EmbeddingError(
            EMBEDDING_ADMIN_UNRESOLVED,
            detail=f"User {admin_id} is not an admin.",
        )


# ──────────────────────────────────────────────────────────────────────
# Reference data loading
# ──────────────────────────────────────────────────────────────────────


def _load_roles(db) -> dict[str, str]:
    """Map user id -> role for every user row."""
    return {row.id: row.role for row in db.query(User).all()}


def _load_groups(db) -> list:
    """Load all group rows once (id, owner, member ids)."""
    return db.query(Group).all()


def _load_files(db) -> dict[str, File]:
    """Map file id -> File row for existence and snapshot fields."""
    return {row.id: row for row in db.query(File).all()}


def _load_knowledge(db) -> list:
    """Load all knowledge rows once, sorted for deterministic iteration."""
    return db.query(Knowledge).order_by(Knowledge.id).all()


def _load_chats(db) -> list:
    """Load all chat rows once, sorted for deterministic iteration."""
    return db.query(Chat).order_by(Chat.id).all()


def _build_group_admins(groups, roles: dict[str, str]) -> dict[str, Optional[str]]:
    """Map group id -> owner admin id, or None when the owner is not an admin.

    Only users with role ``admin`` govern an embedding space (mirrors the
    Phase 1 backfill rule that never uses ``created_by`` or non-admin owners).
    """
    return {
        group.id: (
            group.user_id
            if group.user_id and roles.get(group.user_id) == "admin"
            else None
        )
        for group in groups
    }


def _build_user_group_index(groups) -> dict[str, set[str]]:
    """Map user id -> set of group ids the user belongs to."""
    index: dict[str, set[str]] = {}
    for group in groups:
        member_ids = group.user_ids or []
        for member_id in member_ids:
            index.setdefault(member_id, set()).add(group.id)
    return index


# ──────────────────────────────────────────────────────────────────────
# Stable-ID admin resolution (batched mirror of resolution.py)
# ──────────────────────────────────────────────────────────────────────


def _resolve_user_admin(
    user_id: Optional[str],
    roles: dict[str, str],
    group_admins: dict[str, Optional[str]],
    user_group_ids: dict[str, set[str]],
    source_desc: str,
) -> str:
    """Resolve a user's effective admin via the stable-ID inheritance rule.

    Mirrors ``resolution.resolve_admin_for_user``: the user themself when they
    are an admin, otherwise the single distinct admin among the group owners
    of the groups the user belongs to. Unresolved or ambiguous results are
    fatal for the inventory (user-confirmed strict reading).
    """
    if not user_id or user_id not in roles:
        raise EmbeddingError(
            EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
            detail=f"{source_desc}: owner user {user_id!r} not found.",
        )
    if roles[user_id] == "admin":
        return user_id

    admin_ids = {
        group_admins[group_id]
        for group_id in user_group_ids.get(user_id, set())
        if group_admins.get(group_id)
    }
    if not admin_ids:
        raise EmbeddingError(
            EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
            detail=f"{source_desc}: no admin found for owner user {user_id!r}.",
        )
    if len(admin_ids) != 1:
        raise EmbeddingError(
            EMBEDDING_INVENTORY_AMBIGUOUS_SOURCE,
            detail=(
                f"{source_desc}: ambiguous admin resolution for user "
                f"{user_id!r}: {sorted(admin_ids)}."
            ),
        )
    return next(iter(admin_ids))


def _knowledge_access_groups(knowledge: Knowledge) -> set[str]:
    """Group ids from access_control read/write permissions, deduplicated.

    ``None`` access_control or an empty dict means no assigned groups (the
    owner rule then applies). A present but wrong-typed structure (non-dict
    ``read``/``write``, non-list ``group_ids``, non-string group id) is a
    malformed reference: silently ignoring it would change governance to the
    knowledge owner, so it raises instead.
    """
    access_control = knowledge.access_control
    if access_control is None:
        return set()
    if not isinstance(access_control, dict):
        raise EmbeddingError(
            EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
            detail=(
                f"knowledge {knowledge.id}: access_control is "
                f"{type(access_control).__name__}, expected a dict or None."
            ),
        )
    group_ids: set[str] = set()
    for permission in ("read", "write"):
        rule = access_control.get(permission)
        if rule is None:
            continue
        if not isinstance(rule, dict):
            raise EmbeddingError(
                EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
                detail=(
                    f"knowledge {knowledge.id}: access_control.{permission} is "
                    f"{type(rule).__name__}, expected a dict."
                ),
            )
        group_id_list = rule.get("group_ids")
        if group_id_list is None:
            continue
        if not isinstance(group_id_list, list):
            raise EmbeddingError(
                EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
                detail=(
                    f"knowledge {knowledge.id}: access_control.{permission}.group_ids "
                    f"is {type(group_id_list).__name__}, expected a list."
                ),
            )
        for group_id in group_id_list:
            if not isinstance(group_id, str) or not group_id:
                raise EmbeddingError(
                    EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
                    detail=(
                        f"knowledge {knowledge.id}: access_control.{permission}.group_ids "
                        f"contains a non-string entry: {group_id!r}."
                    ),
                )
            group_ids.add(group_id)
    return group_ids


def _resolve_knowledge_admin(
    knowledge: Knowledge,
    roles: dict[str, str],
    group_admins: dict[str, Optional[str]],
    user_group_ids: dict[str, set[str]],
) -> str:
    """Resolve the single governing admin of a knowledge base.

    RBAC-group-first: when the knowledge base is assigned to groups via
    ``access_control``, every assigned group must resolve to the same admin.
    With no assigned groups, resolve through the knowledge owner.
    """
    source_desc = f"knowledge {knowledge.id}"
    group_ids = _knowledge_access_groups(knowledge)
    if group_ids:
        resolved: list[str] = []
        for group_id in sorted(group_ids):
            admin_id = group_admins.get(group_id)
            if admin_id is None:
                raise EmbeddingError(
                    EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
                    detail=(
                        f"{source_desc}: assigned group {group_id!r} does not "
                        f"resolve to an admin owner."
                    ),
                )
            resolved.append(admin_id)
        distinct = set(resolved)
        if len(distinct) != 1:
            raise EmbeddingError(
                EMBEDDING_INVENTORY_AMBIGUOUS_SOURCE,
                detail=(
                    f"{source_desc}: assigned groups resolve to multiple admins: "
                    f"{sorted(distinct)}."
                ),
            )
        return next(iter(distinct))
    return _resolve_user_admin(
        knowledge.user_id, roles, group_admins, user_group_ids, source_desc
    )


def _resolve_chat_admin(
    chat: Chat,
    roles: dict[str, str],
    group_admins: dict[str, Optional[str]],
    user_group_ids: dict[str, set[str]],
) -> str:
    """Resolve the single governing admin of a chat.

    ``chat.group_id`` (the owning group's admin) wins when set; otherwise the
    chat owner resolves through the stable-ID rule. An unresolvable group
    reference is fatal, never silently downgraded to the owner.
    """
    source_desc = f"chat {chat.id}"
    if chat.group_id:
        admin_id = group_admins.get(chat.group_id)
        if admin_id is None:
            raise EmbeddingError(
                EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
                detail=(
                    f"{source_desc}: group {chat.group_id!r} does not resolve to "
                    f"an admin owner."
                ),
            )
        return admin_id
    return _resolve_user_admin(
        chat.user_id, roles, group_admins, user_group_ids, source_desc
    )


# ──────────────────────────────────────────────────────────────────────
# Reference parsing (exact JSON paths)
# ──────────────────────────────────────────────────────────────────────


def _iter_knowledge_refs(knowledge: Knowledge):
    """Yield file ids referenced by one knowledge base.

    ``knowledge.data.file_ids`` is the authoritative path. A missing or
    non-dict ``data`` is treated as empty (matching the repository's
    normalization everywhere else); a present ``file_ids`` that is not a list,
    or a list containing non-string entries, is a malformed reference.
    """
    data = knowledge.data
    if data is None or not isinstance(data, dict):
        return
    file_ids = data.get("file_ids")
    if file_ids is None:
        return
    if not isinstance(file_ids, list):
        raise EmbeddingError(
            EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
            detail=(
                f"knowledge {knowledge.id}: data.file_ids is {type(file_ids).__name__}, "
                f"expected a list."
            ),
        )
    for file_id in file_ids:
        if not isinstance(file_id, str) or not file_id:
            raise EmbeddingError(
                EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
                detail=(
                    f"knowledge {knowledge.id}: data.file_ids contains a "
                    f"non-string entry: {file_id!r}."
                ),
            )
        yield file_id


def _iter_chat_refs(chat: Chat):
    """Yield uploaded file ids referenced by one chat payload.

    Exact path: ``chat.chat["history"]["messages"][*]["files"][*]``. Messages
    may be a dict keyed by message id or a list. A files entry is an uploaded
    file when its ``type`` is not ``collection``/``web_search``/``text`` and it
    carries an ``id``. Structural violations (messages neither dict nor list,
    files not a list, non-dict entries, ``type == "file"`` without an id) are
    malformed references.
    """
    payload = chat.chat
    if payload is None or not isinstance(payload, dict):
        return
    history = payload.get("history")
    if history is None:
        return
    if not isinstance(history, dict):
        raise EmbeddingError(
            EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
            detail=f"chat {chat.id}: chat.history is {type(history).__name__}, expected a dict.",
        )
    messages = history.get("messages")
    if messages is None:
        return
    if not isinstance(messages, (dict, list)):
        raise EmbeddingError(
            EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
            detail=(
                f"chat {chat.id}: chat.history.messages is "
                f"{type(messages).__name__}, expected a dict or list."
            ),
        )
    message_values = messages.values() if isinstance(messages, dict) else messages
    for message in message_values:
        if message is None:
            continue
        if not isinstance(message, dict):
            raise EmbeddingError(
                EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
                detail=f"chat {chat.id}: a message is not a dict.",
            )
        files = message.get("files")
        if files is None:
            continue
        if not isinstance(files, list):
            raise EmbeddingError(
                EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
                detail=f"chat {chat.id}: message.files is {type(files).__name__}, expected a list.",
            )
        for entry in files:
            if not isinstance(entry, dict):
                raise EmbeddingError(
                    EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
                    detail=f"chat {chat.id}: a message.files entry is not a dict.",
                )
            entry_type = entry.get("type")
            if entry_type in _CHAT_NON_FILE_TYPES:
                continue
            file_id = entry.get("id")
            if entry_type == "file" and (not isinstance(file_id, str) or not file_id):
                raise EmbeddingError(
                    EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
                    detail=f"chat {chat.id}: an uploaded file entry has no id.",
                )
            if isinstance(file_id, str) and file_id:
                yield file_id


# ──────────────────────────────────────────────────────────────────────
# Inventory assembly
# ──────────────────────────────────────────────────────────────────────


def _build_inventory(db, admin_id: str) -> list[ReindexFile]:
    admin_resolver = build_reindex_admin_resolver(db)
    files_by_id = _load_files(db)

    # file_id -> set of governing admin ids discovered via governed sources
    file_admins: dict[str, set[str]] = {}
    # file_id -> set of knowledge base ids whose collections contain the file
    file_knowledge: dict[str, set[str]] = {}
    # file_id -> set of source contexts (knowledge / chat_upload)
    file_contexts: dict[str, set[str]] = {}
    # file_id -> sorted source descriptions for structured error messages
    file_sources: dict[str, set[str]] = {}

    def record(file_id: str, admin: str, source_desc: str, context: str) -> None:
        file_admins.setdefault(file_id, set()).add(admin)
        file_sources.setdefault(file_id, set()).add(source_desc)
        file_contexts.setdefault(file_id, set()).add(context)

    for knowledge in _load_knowledge(db):
        refs = list(_iter_knowledge_refs(knowledge))  # may raise MALFORMED
        if not refs:
            continue  # references no files; governs nothing in this inventory
        admin = admin_resolver.resolve_knowledge(knowledge)
        source_desc = f"knowledge {knowledge.id}"
        for file_id in refs:
            record(file_id, admin, source_desc, SOURCE_KNOWLEDGE)
            file_knowledge.setdefault(file_id, set()).add(knowledge.id)

    for chat in _load_chats(db):
        refs = list(_iter_chat_refs(chat))  # may raise MALFORMED
        if not refs:
            continue  # no uploads; chat governance is irrelevant to this inventory
        admin = admin_resolver.resolve_chat(chat)
        source_desc = f"chat {chat.id}"
        for file_id in refs:
            record(file_id, admin, source_desc, SOURCE_CHAT_UPLOAD)

    # Restrict to this admin's job before validating: only files governed by
    # ``admin_id`` ever enter the job ledger, so another admin's broken or
    # ambiguous files must not block this model change.
    items: list[ReindexFile] = []
    for file_id in sorted(file_admins):
        governing = file_admins[file_id]
        if admin_id not in governing:
            continue  # governed by another admin; never part of this job

        # Rule 6: a governed reference to a missing file row is fatal because
        # embedding_job_files.file_id requires a valid file.
        if file_id not in files_by_id:
            raise EmbeddingError(
                EMBEDDING_INVENTORY_MISSING_FILE,
                detail=(
                    f"Referenced file {file_id!r} not found in the file table "
                    f"(referenced by {sorted(file_sources[file_id])})."
                ),
            )

        # Rule 8: a file governed by more than one distinct admin is ambiguous.
        if len(governing) != 1:
            raise EmbeddingError(
                EMBEDDING_INVENTORY_AMBIGUOUS_ADMIN,
                detail=(
                    f"File {file_id!r} is governed by multiple admins: "
                    f"{sorted(governing)}."
                ),
            )

        file_row = files_by_id[file_id]
        items.append(
            ReindexFile(
                file_id=file_id,
                source_contexts=frozenset(file_contexts[file_id]),
                knowledge_collection_ids=tuple(sorted(file_knowledge.get(file_id, set()))),
                file_collection_name=f"file-{file_id}",
                admin_id=admin_id,
                content_hash=file_row.hash,
                updated_at=file_row.updated_at,
            )
        )

    items.sort(key=lambda item: item.file_id)
    log.info(
        "[INVENTORY] built for admin %s: %d unique files (%s)",
        admin_id,
        len(items),
        ", ".join(sorted({c for item in items for c in item.source_contexts})) or "none",
    )
    return items
