"""Cooperative wall-clock budgets shared by media preparation and providers."""

from contextlib import contextmanager
from contextvars import ContextVar
import time

from open_webui.retrieval.embedding.errors import (
    EmbeddingError,
    EMBEDDING_PROVIDER_FAILED,
)


_deadline: ContextVar[float | None] = ContextVar(
    "embedding_execution_deadline", default=None
)


@contextmanager
def execution_budget(seconds: float, *, persistence_reserve: float = 5.0):
    token = _deadline.set(time.monotonic() + max(0, seconds - persistence_reserve))
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining_seconds() -> float | None:
    deadline = _deadline.get()
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise EmbeddingError(
            EMBEDDING_PROVIDER_FAILED,
            detail="Audio processing reached its time budget. Retry remaining audio.",
            retryable=True,
            failure_reason="budget_exhausted",
        )
    return remaining


def capped_timeout(seconds: float) -> float:
    remaining = remaining_seconds()
    return min(seconds, remaining) if remaining is not None else seconds


def provider_timeout(connect: float, read: float) -> tuple[float, float]:
    remaining = remaining_seconds()
    if remaining is None:
        return connect, read
    # Keep the sum of both transport phases inside the execution budget.
    return min(connect, remaining / 2), min(read, remaining / 2)


def budgeted_sleep(seconds: float) -> None:
    time.sleep(capped_timeout(seconds))
    remaining_seconds()
