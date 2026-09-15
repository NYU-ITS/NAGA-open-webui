"""Bounded metric dimensions; source/job identifiers belong only in logs."""

import logging
from functools import lru_cache

log = logging.getLogger(__name__)
_EVENTS = frozenset(
    {
        "published",
        "publication_rejected",
        "retry_files",
        "reconstruction_timeout",
        "repair_abandoned",
        "audio_budget_exhausted",
    }
)


@lru_cache(maxsize=1)
def _event_counter():
    from opentelemetry import metrics

    return metrics.get_meter(__name__).create_counter("naga.index.events")


def record_index_event(event: str, count: int = 1) -> None:
    if event not in _EVENTS:
        raise ValueError("Unknown indexing metric")
    try:
        _event_counter().add(count, {"event": event})
    except Exception:
        log.debug("Index metric unavailable", exc_info=True)
