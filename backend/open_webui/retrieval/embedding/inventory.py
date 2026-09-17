"""Deterministic, deduplicated reindex file inventory for one admin (Spec 02).

``build_reindex_inventory`` produces the frozen snapshot of every physical file
a reindex operation must rebuild for one admin: knowledge-base files plus
applicable chat uploads, deduplicated, with every collection membership the
worker needs to reconstruct each required vector projection.

Inventory scope is based on source ownership, not access-control membership:

- A knowledge base belongs to its direct admin owner, regardless of sharing.
- A grouped chat belongs to the group's admin owner. An ungrouped chat is
  included only when it is directly owned by the requested admin.

Only eligible sources and references sharing their files are parsed, so unrelated
malformed references do not block this admin's model change. Non-admin-owned
knowledge bases and ungrouped non-admin chats have no admin reindex scope. Files
referenced by multiple admins remain ambiguous because publication state is per file.

Malformed eligible knowledge/chat references fail the inventory. Missing
originals also fail unless retry discovery explicitly collects and skips them.

Exact chat reference path (mirrors the Phase 1 backfill migration and the
frontend payload): ``chat.chat["history"]["messages"][*]["files"][*]`` where
``messages`` is a dict keyed by message id or a list, and a files entry is an
uploaded file when its ``type`` is not one of ``collection``/``web_search``/
``text`` and it carries an ``id``.

The result is sorted by ``file_id`` and every nested collection id is sorted,
so persistence (Spec 03/04) produces a deterministic snapshot. ``ReindexFile``
round-trips through JSON so the job repository can persist source freshness
fields plus the canonical preparation recipe and its digest (used by Spec 11's
``REINDEX_SOURCE_CHANGED`` staleness check).
"""

import hashlib
import logging
import os
import stat
from dataclasses import dataclass, field
from typing import Any, Optional

from open_webui.internal.db import get_db
from open_webui.models.chats import Chat
from open_webui.models.files import File
from open_webui.models.groups import Group
from open_webui.models.knowledge import Knowledge
from open_webui.models.users import User
from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    InventorySourceUnavailableError,
    EMBEDDING_ADMIN_UNRESOLVED,
    EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
    EMBEDDING_INVENTORY_AMBIGUOUS_SOURCE,
    EMBEDDING_INVENTORY_AMBIGUOUS_ADMIN,
    EMBEDDING_INVENTORY_MISSING_FILE,
    EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
)
from open_webui.retrieval.embedding.file_processing import (
    CONTENT_ORIGIN_OVERRIDE,
    CONTENT_ORIGIN_STORED_SOURCE,
    read_stored_content_provenance,
)
from open_webui.retrieval.embedding.preparation import (
    PreparationRecipe,
    preparation_recipe_from_snapshot,
)
from open_webui.retrieval.embedding.reliability import EmbeddingReliabilityPolicy
from open_webui.storage.provider import (
    LocalStorageProvider,
    SourceFileNotFoundError,
    Storage,
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
    ``content_hash``, ``updated_at``, and the non-PDF content-override origin
    and digest are captured at snapshot time so Spec 11 can detect stale
    source content. ``preparation_recipe`` freezes every extraction, render,
    and chunking input needed to reproduce preparation.
    """

    file_id: str
    source_contexts: frozenset[str]
    knowledge_collection_ids: tuple[str, ...]
    file_collection_name: str
    admin_id: str
    preparation_recipe: PreparationRecipe
    content_hash: Optional[str] = None
    source_sha256: str = ""
    content_origin: str = CONTENT_ORIGIN_STORED_SOURCE
    content_override_sha256: Optional[str] = None
    updated_at: Optional[int] = None
    index_generation_id: str = ""
    reliability_policy: EmbeddingReliabilityPolicy = field(
        default_factory=EmbeddingReliabilityPolicy
    )

    def __post_init__(self) -> None:
        if not isinstance(self.preparation_recipe, PreparationRecipe):
            raise TypeError("reindex snapshots require a preparation recipe")
        if not isinstance(self.reliability_policy, EmbeddingReliabilityPolicy):
            raise TypeError("reindex snapshots require an embedding reliability policy")
        if (
            not isinstance(self.source_sha256, str)
            or len(self.source_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.source_sha256
            )
        ):
            raise ValueError("reindex snapshots require a source SHA-256 digest")
        if self.content_origin not in {
            CONTENT_ORIGIN_STORED_SOURCE,
            CONTENT_ORIGIN_OVERRIDE,
        }:
            raise ValueError("invalid reindex content origin")
        if (
            self.content_origin == CONTENT_ORIGIN_STORED_SOURCE
            and self.content_override_sha256 is not None
        ):
            raise ValueError("stored-source snapshots cannot carry an override hash")
        if self.content_origin == CONTENT_ORIGIN_OVERRIDE and (
            not isinstance(self.content_override_sha256, str)
            or len(self.content_override_sha256) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.content_override_sha256
            )
        ):
            raise ValueError("override snapshots require a SHA-256 digest")

    def to_dict(self) -> dict[str, Any]:
        """Deterministic JSON-safe snapshot of this inventory item."""
        snapshot = {
            "file_id": self.file_id,
            "source_contexts": sorted(self.source_contexts),
            "knowledge_collection_ids": list(self.knowledge_collection_ids),
            "file_collection_name": self.file_collection_name,
            "admin_id": self.admin_id,
            "content_hash": self.content_hash,
            "source_sha256": self.source_sha256,
            "content_origin": self.content_origin,
            "content_override_sha256": self.content_override_sha256,
            "updated_at": self.updated_at,
            "index_generation_id": self.index_generation_id,
        }
        snapshot["preparation_recipe"] = self.preparation_recipe.to_dict()
        snapshot["preparation_recipe_sha256"] = self.preparation_recipe.sha256
        snapshot["reliability_policy"] = self.reliability_policy.to_dict()
        return snapshot

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
            source_sha256=data.get("source_sha256"),
            content_origin=data.get(
                "content_origin",
                CONTENT_ORIGIN_STORED_SOURCE,
            ),
            content_override_sha256=data.get("content_override_sha256"),
            updated_at=data.get("updated_at"),
            index_generation_id=data.get("index_generation_id", ""),
            preparation_recipe=preparation_recipe_from_snapshot(data),
            reliability_policy=EmbeddingReliabilityPolicy.from_dict(
                data.get("reliability_policy")
            ),
        )


@dataclass(frozen=True)
class ReindexAdminResolver:
    """Shared ownership snapshot for reindex-related reads.

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
        if not self.knowledge_owned_by_admin(knowledge, knowledge.user_id):
            raise EmbeddingError(
                EMBEDDING_ADMIN_UNRESOLVED,
                detail=f"Knowledge {knowledge.id} is not directly owned by an admin.",
            )
        return knowledge.user_id

    def knowledge_owned_by_admin(self, knowledge: Knowledge, admin_id: str) -> bool:
        return bool(
            admin_id
            and knowledge.user_id == admin_id
            and self.roles.get(admin_id) == "admin"
        )

    def chat_owned_by_admin(self, chat: Chat, admin_id: str) -> bool:
        if chat.group_id:
            return self.group_admins.get(chat.group_id) == admin_id
        return bool(
            chat.user_id == admin_id and self.roles.get(admin_id) == "admin"
        )

    def resolve_chat(self, chat: Chat) -> str:
        return _resolve_chat_admin(
            chat,
            self.roles,
            self.group_admins,
        )

    def resolve_user(self, user_id: str) -> str:
        return _resolve_user_admin(
            user_id,
            self.roles,
            self.group_admins,
            self.user_group_ids,
            "standalone file owner",
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


def build_reindex_inventory(
    admin_id: str,
    db=None,
    *,
    preparation_recipe: PreparationRecipe,
    reliability_policy: EmbeddingReliabilityPolicy | None = None,
    file_ids: set[str] | None = None,
    missing_file_ids: set[str] | None = None,
) -> list[ReindexFile]:
    """Build the deterministic reindex inventory for one admin.

    Args:
        admin_id: Stable user id of the responsible admin.
        db: Optional caller-owned session. When provided, all reads use that
            session and nothing is committed (read-only); otherwise a session
            is opened and closed here.
        preparation_recipe: Canonical admin-scoped extraction and chunking
            settings to persist identically on every file snapshot.
        missing_file_ids: When supplied by retry creation, collect and skip
            confirmed missing originals. Other storage failures still abort.

    Returns:
        Inventory items sorted by ``file_id``.

    Raises:
        EmbeddingError: If the requested admin is invalid, a relevant source
            is malformed, a file is governed by multiple admins, or an original
            is unavailable (unless collecting confirmed missing files for a retry).
    """
    if db is None:
        with get_db() as session:
            _assert_admin(session, admin_id)
            return _build_inventory(
                session,
                admin_id,
                preparation_recipe,
                reliability_policy or EmbeddingReliabilityPolicy(),
                file_ids,
                missing_file_ids,
            )
    _assert_admin(db, admin_id)
    return _build_inventory(
        db,
        admin_id,
        preparation_recipe,
        reliability_policy or EmbeddingReliabilityPolicy(),
        file_ids,
        missing_file_ids,
    )


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


def _resolve_chat_admin(
    chat: Chat,
    roles: dict[str, str],
    group_admins: dict[str, Optional[str]],
) -> str:
    """Resolve the single governing admin of a chat.

    ``chat.group_id`` (the owning group's admin) wins when set; otherwise the
    chat must be directly admin-owned. An unresolvable group reference is
    never downgraded to the owner.
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
    if chat.user_id and roles.get(chat.user_id) == "admin":
        return chat.user_id
    raise EmbeddingError(
        EMBEDDING_INVENTORY_UNRESOLVED_SOURCE,
        detail=f"{source_desc}: ungrouped chat is not directly owned by an admin.",
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


def _knowledge_references_requested_file(
    knowledge: Knowledge, file_ids: set[str]
) -> bool:
    """Narrow retry discovery before applying strict source validation."""
    data = knowledge.data
    refs = data.get("file_ids") if isinstance(data, dict) else None
    return isinstance(refs, list) and any(
        isinstance(file_id, str) and file_id in file_ids for file_id in refs
    )


def _chat_references_requested_file(chat: Chat, file_ids: set[str]) -> bool:
    payload = chat.chat
    history = payload.get("history") if isinstance(payload, dict) else None
    messages = history.get("messages") if isinstance(history, dict) else None
    if isinstance(messages, dict):
        messages = messages.values()
    elif not isinstance(messages, list):
        return False
    for message in messages:
        entries = message.get("files") if isinstance(message, dict) else None
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            file_id = entry.get("id")
            entry_type = entry.get("type")
            if (
                not (isinstance(entry_type, str) and entry_type in _CHAT_NON_FILE_TYPES)
                and isinstance(file_id, str)
                and file_id in file_ids
            ):
                return True
    return False


def _build_inventory(
    db,
    admin_id: str,
    preparation_recipe: PreparationRecipe,
    reliability_policy: EmbeddingReliabilityPolicy,
    file_ids: set[str] | None = None,
    missing_file_ids: set[str] | None = None,
) -> list[ReindexFile]:
    admin_resolver = build_reindex_admin_resolver(db)
    files_by_id = _load_files(db)
    knowledge_rows = _load_knowledge(db)
    chat_rows = _load_chats(db)

    # file_id -> set of knowledge base ids whose collections contain the file
    file_knowledge: dict[str, set[str]] = {}
    # file_id -> set of source contexts (knowledge / chat_upload)
    file_contexts: dict[str, set[str]] = {}
    # file_id -> sorted source descriptions for structured error messages
    file_sources: dict[str, set[str]] = {}

    def record(file_id: str, source_desc: str, context: str) -> None:
        file_sources.setdefault(file_id, set()).add(source_desc)
        file_contexts.setdefault(file_id, set()).add(context)

    for knowledge in knowledge_rows:
        if not admin_resolver.knowledge_owned_by_admin(knowledge, admin_id):
            continue
        if file_ids is not None and not _knowledge_references_requested_file(
            knowledge, file_ids
        ):
            continue
        refs = list(_iter_knowledge_refs(knowledge))  # may raise MALFORMED
        if file_ids is not None:
            refs = [file_id for file_id in refs if file_id in file_ids]
        if not refs:
            continue  # references no files; governs nothing in this inventory
        source_desc = f"knowledge {knowledge.id}"
        for file_id in refs:
            record(file_id, source_desc, SOURCE_KNOWLEDGE)
            file_knowledge.setdefault(file_id, set()).add(knowledge.id)

    for chat in chat_rows:
        if not admin_resolver.chat_owned_by_admin(chat, admin_id):
            continue
        if file_ids is not None and not _chat_references_requested_file(chat, file_ids):
            continue
        refs = list(_iter_chat_refs(chat))  # may raise MALFORMED
        if file_ids is not None:
            refs = [file_id for file_id in refs if file_id in file_ids]
        if not refs:
            continue  # no uploads; chat governance is irrelevant to this inventory
        source_desc = f"chat {chat.id}"
        for file_id in refs:
            record(file_id, source_desc, SOURCE_CHAT_UPLOAD)

    # Keep the existing cross-admin guard: File publication/lease metadata is
    # not admin-scoped. Inspect other sources only if they reference our files.
    scoped_ids = set(file_contexts)
    file_admins = {file_id: {admin_id} for file_id in scoped_ids}
    for knowledge in knowledge_rows:
        if (
            knowledge.user_id == admin_id
            or not admin_resolver.knowledge_owned_by_admin(knowledge, knowledge.user_id)
            or not _knowledge_references_requested_file(knowledge, scoped_ids)
        ):
            continue
        for file_id in _iter_knowledge_refs(knowledge):
            if file_id in scoped_ids:
                file_admins[file_id].add(knowledge.user_id)
    for chat in chat_rows:
        if not _chat_references_requested_file(chat, scoped_ids):
            continue
        try:
            chat_admin_id = admin_resolver.resolve_chat(chat)
        except EmbeddingError:
            continue  # Ungoverned chats are outside every admin inventory.
        if chat_admin_id == admin_id:
            continue
        for file_id in _iter_chat_refs(chat):
            if file_id in scoped_ids:
                file_admins[file_id].add(chat_admin_id)

    items: list[ReindexFile] = []
    for file_id in sorted(file_contexts):
        # Missing live sources block a new inventory. Retry discovery may
        # explicitly collect confirmed deletions instead.
        if file_id not in files_by_id:
            if missing_file_ids is not None:
                missing_file_ids.add(file_id)
                continue
            log.warning("Reindex source missing | admin=%s file=%s reason=missing_record sources=%s",
                        admin_id, file_id, sorted(file_sources[file_id]))
            raise InventorySourceUnavailableError(admin_id, file_id, None, "missing_record")

        if len(file_admins[file_id]) != 1:
            raise EmbeddingError(
                EMBEDDING_INVENTORY_AMBIGUOUS_ADMIN,
                detail=(
                    f"File {file_id!r} is governed by multiple admins: "
                    f"{sorted(file_admins[file_id])}."
                ),
            )

        file_row = files_by_id[file_id]
        try:
            content_provenance = read_stored_content_provenance(file_row)
        except ValueError:
            raise EmbeddingError(
                EMBEDDING_INVENTORY_MALFORMED_REFERENCE,
                detail=f"File {file_id!r} has invalid content provenance.",
            ) from None
        try:
            source_sha256 = source_sha256_for_file(
                file_row, report_missing=True
            )
        except SourceFileNotFoundError:
            if missing_file_ids is not None:
                missing_file_ids.add(file_id)
                continue
            log.warning("Reindex source missing | admin=%s file=%s reason=missing_source sources=%s",
                        admin_id, file_id, sorted(file_sources[file_id]))
            raise InventorySourceUnavailableError(
                admin_id, file_id, file_row.filename, "missing_source"
            ) from None
        if source_sha256 is None:
            log.warning("Reindex source unreadable | admin=%s file=%s sources=%s",
                        admin_id, file_id, sorted(file_sources[file_id]))
            raise InventorySourceUnavailableError(
                admin_id, file_id, file_row.filename, "unreadable_source"
            )
        items.append(
            ReindexFile(
                file_id=file_id,
                source_contexts=frozenset(file_contexts[file_id]),
                knowledge_collection_ids=tuple(sorted(file_knowledge.get(file_id, set()))),
                file_collection_name=f"file-{file_id}",
                admin_id=admin_id,
                content_hash=file_row.hash,
                source_sha256=source_sha256,
                content_origin=content_provenance.origin,
                content_override_sha256=(
                    content_provenance.content_override_sha256
                ),
                updated_at=file_row.updated_at,
                preparation_recipe=preparation_recipe,
                reliability_policy=reliability_policy,
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


def source_sha256_for_file(
    file_row: File, *, report_missing: bool = False
) -> Optional[str]:
    """Hash the current original object addressed by a file row.

    Never trust cached file metadata for freshness checks. The path may still
    address different bytes even when ``meta.source_sha256`` has not changed.
    Retry discovery can request a distinct exception for confirmed absence;
    permissions, timeouts, and other read failures still return None.
    """
    if not file_row.path:
        if report_missing:
            raise SourceFileNotFoundError("Original document has no storage path.")
        return None
    try:
        source_path = Storage.get_file(file_row.path)
        if not source_path or not stat.S_ISREG(os.stat(source_path).st_mode):
            return None
        digest = hashlib.sha256()
        with open(source_path, "rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except SourceFileNotFoundError:
        if report_missing:
            raise
    except FileNotFoundError:
        # A missing cloud download directory is an access failure, not proof
        # that the remote original was deleted.
        if report_missing and isinstance(Storage, LocalStorageProvider):
            raise SourceFileNotFoundError("Original document not found.") from None
    except Exception:
        pass
    return None
