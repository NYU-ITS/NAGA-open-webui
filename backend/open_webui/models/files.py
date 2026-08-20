import logging
import time
from collections.abc import Mapping
from typing import Any, Optional

from open_webui.internal.db import Base, JSONField, get_db
from open_webui.env import SRC_LOG_LEVELS
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import BigInteger, Column, String, Text, JSON

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

####################
# Files DB Schema
####################


class File(Base):
    __tablename__ = "file"
    id = Column(String, primary_key=True)
    user_id = Column(String)
    hash = Column(Text, nullable=True)

    filename = Column(Text)
    path = Column(Text, nullable=True)

    data = Column(JSON, nullable=True)
    meta = Column(JSON, nullable=True)

    access_control = Column(JSON, nullable=True)

    created_at = Column(BigInteger)
    updated_at = Column(BigInteger)


class FileModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    hash: Optional[str] = None

    filename: str
    path: Optional[str] = None

    data: Optional[dict] = None
    meta: Optional[dict] = None

    access_control: Optional[dict] = None

    created_at: Optional[int]  # timestamp in epoch
    updated_at: Optional[int]  # timestamp in epoch


# These fields are needed internally to validate/reconstruct image chunks, but
# must never cross the browser-facing file/knowledge API boundary. Keep this
# sanitizer in the model layer so every response model gets the same policy.
_PRIVATE_FILE_METADATA_KEYS = frozenset(
    {
        "alpha",
        "bbox",
        "cache",
        "chunk_manifest_id",
        "content_origin",
        "content_override",
        "content_override_sha256",
        "content_sha256",
        "coordinate_space",
        "image_sha256",
        "manifest_id",
        "object_key",
        "output_format",
        "padding_points",
        "page_local_sequence",
        "path",
        "source_sequence",
        "source_sha256",
        "storage_key",
        "storage_path",
    }
)
_PRIVATE_FILE_METADATA_PREFIXES = ("cache_", "extraction_", "render_")
_VISUAL_SUMMARY_KEYS = (
    "figure_count",
    "table_image_count",
    "image_chunk_count",
    "text_chunk_count",
    "video_chunk_count",
)


def sanitize_public_visual_summary(value: Any) -> dict[str, int]:
    """Normalize the four public non-negative visual/chunk counters."""
    source = value if isinstance(value, Mapping) else {}
    result = {}
    for key in _VISUAL_SUMMARY_KEYS:
        try:
            count = int(source.get(key, 0) or 0)
        except (TypeError, ValueError, OverflowError):
            count = 0
        result[key] = max(0, count)
    return result


def sanitize_public_file_metadata(value: Any) -> Any:
    """Return a copy of file metadata with private processing fields removed."""

    if isinstance(value, Mapping):
        from open_webui.retrieval.embedding.errors import (
            safe_file_processing_error_code,
            safe_file_processing_error_message,
            safe_file_processing_warnings,
        )

        raw_code = value.get("processing_error_code")
        public_code = safe_file_processing_error_code(raw_code)
        if public_code is None and (
            value.get("processing_status") == "error"
            or value.get("processing_error") is not None
        ):
            public_code = safe_file_processing_error_code("file_processing_failed")
        result = {}
        for key, item in value.items():
            if (
                not isinstance(key, str)
                or key in _PRIVATE_FILE_METADATA_KEYS
                or key.startswith(_PRIVATE_FILE_METADATA_PREFIXES)
            ):
                continue
            if key == "processing_error_code":
                result[key] = public_code
            elif key == "processing_error":
                result[key] = (
                    safe_file_processing_error_message(public_code)
                    if item is not None
                    else None
                )
            elif key == "processing_warnings":
                result[key] = safe_file_processing_warnings(item)
            elif key == "visual_summary":
                result[key] = sanitize_public_visual_summary(item)
            else:
                result[key] = sanitize_public_file_metadata(item)
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize_public_file_metadata(item) for item in value]
    return value


####################
# Forms
####################


class FileMeta(BaseModel):
    name: Optional[str] = None
    content_type: Optional[str] = None
    size: Optional[int] = None

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def remove_private_processing_metadata(cls, value: Any) -> Any:
        if isinstance(value, BaseModel):
            value = value.model_dump()
        return sanitize_public_file_metadata(value or {})


class FileMetadataResponse(BaseModel):
    id: str
    meta: dict = Field(default_factory=dict)
    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    @field_validator("meta", mode="before")
    @classmethod
    def remove_private_processing_metadata(cls, value: Any) -> Any:
        return sanitize_public_file_metadata(value or {})


class FileModelResponse(BaseModel):
    id: str
    user_id: str
    hash: Optional[str] = None

    filename: str
    data: Optional[dict] = None
    meta: FileMeta = Field(default_factory=FileMeta)

    created_at: int  # timestamp in epoch
    updated_at: int  # timestamp in epoch

    model_config = ConfigDict(from_attributes=True, extra="ignore")

    @field_validator("data", mode="before")
    @classmethod
    def remove_private_processing_data(cls, value: Any) -> Any:
        return sanitize_public_file_metadata(value)

class FileForm(BaseModel):
    id: str
    hash: Optional[str] = None
    filename: str
    path: str
    data: dict = {}
    meta: dict = {}
    access_control: Optional[dict] = None


class FilesTable:
    def insert_new_file(self, user_id: str, form_data: FileForm) -> Optional[FileModel]:
        with get_db() as db:
            file = FileModel(
                **{
                    **form_data.model_dump(),
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "updated_at": int(time.time()),
                }
            )

            try:
                result = File(**file.model_dump())
                db.add(result)
                db.commit()
                db.refresh(result)
                if result:
                    return FileModel.model_validate(result)
                else:
                    return None
            except Exception as e:
                log.exception(f"Error inserting a new file: {e}")
                return None

    def get_file_by_id(self, id: str) -> Optional[FileModel]:
        with get_db() as db:
            try:
                file = db.get(File, id)
                return FileModel.model_validate(file)
            except Exception:
                return None

    def get_file_metadata_by_id(self, id: str) -> Optional[FileMetadataResponse]:
        with get_db() as db:
            try:
                file = db.get(File, id)
                return FileMetadataResponse(
                    id=file.id,
                    meta=file.meta,
                    created_at=file.created_at,
                    updated_at=file.updated_at,
                )
            except Exception:
                return None

    def get_files(self) -> list[FileModel]:
        with get_db() as db:
            return [FileModel.model_validate(file) for file in db.query(File).all()]

    def get_files_by_ids(self, ids: list[str]) -> list[FileModel]:
        with get_db() as db:
            return [
                FileModel.model_validate(file)
                for file in db.query(File)
                .filter(File.id.in_(ids))
                .order_by(File.updated_at.desc())
                .all()
            ]

    def get_file_metadatas_by_ids(self, ids: list[str]) -> list[FileMetadataResponse]:
        with get_db() as db:
            return [
                FileMetadataResponse(
                    id=file.id,
                    meta=file.meta,
                    created_at=file.created_at,
                    updated_at=file.updated_at,
                )
                for file in db.query(File)
                .filter(File.id.in_(ids))
                .order_by(File.updated_at.desc())
                .all()
            ]

    def get_files_by_user_id(self, user_id: str) -> list[FileModel]:
        with get_db() as db:
            return [
                FileModel.model_validate(file)
                for file in db.query(File).filter_by(user_id=user_id).all()
            ]

    def update_file_hash_by_id(self, id: str, hash: str) -> Optional[FileModel]:
        with get_db() as db:
            try:
                file = db.query(File).filter_by(id=id).first()
                file.hash = hash
                db.commit()

                return FileModel.model_validate(file)
            except Exception:
                return None

    def update_file_data_by_id(self, id: str, data: dict) -> Optional[FileModel]:
        with get_db() as db:
            try:
                file = db.query(File).filter_by(id=id).first()
                file.data = {**(file.data if file.data else {}), **data}
                db.commit()
                return FileModel.model_validate(file)
            except Exception as e:

                return None

    def update_file_metadata_by_id(self, id: str, meta: dict) -> Optional[FileModel]:
        with get_db() as db:
            try:
                file = db.query(File).filter_by(id=id).first()
                if not file:
                    log.warning(f"File not found for metadata update: id={id}")
                    return None
                file.meta = {**(file.meta if file.meta else {}), **meta}
                db.commit()
                return FileModel.model_validate(file)
            except Exception as e:
                # BUG #4 fix: Log exceptions instead of swallowing them
                log.error(f"Error updating file metadata for id={id}: {e}", exc_info=True)
                return None

    def delete_file_by_id(self, id: str) -> bool:
        with get_db() as db:
            try:
                db.query(File).filter_by(id=id).delete()
                db.commit()

                return True
            except Exception:
                return False

    def delete_all_files(self) -> bool:
        with get_db() as db:
            try:
                db.query(File).delete()
                db.commit()

                return True
            except Exception:
                return False


Files = FilesTable()
