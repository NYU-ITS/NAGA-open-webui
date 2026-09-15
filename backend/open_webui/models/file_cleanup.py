"""Durable deletion intents, independent of the file row they remove."""

import time
import uuid

from sqlalchemy import BigInteger, Column, Integer, String, Text

from open_webui.internal.db import Base


class FileCleanupTask(Base):
    __tablename__ = "file_cleanup_task"

    id = Column(String, primary_key=True)
    file_id = Column(String, nullable=False)
    kind = Column(String(16), nullable=False)
    storage_path = Column(Text, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(BigInteger, nullable=False, index=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(BigInteger, nullable=False)


def enqueue_file_cleanup(db, file_id: str, *, kind="orphan", storage_path=None):
    """Commit the intent in the same transaction as its triggering deletion."""
    now = int(time.time())
    task = FileCleanupTask(
        id=str(uuid.uuid4()),
        file_id=file_id,
        kind=kind,
        storage_path=storage_path,
        attempts=0,
        next_attempt_at=now,
        created_at=now,
    )
    db.add(task)
    return task.id
