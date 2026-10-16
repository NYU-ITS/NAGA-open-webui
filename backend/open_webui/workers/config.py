"""Neutral access point for the RQ worker's cached application config."""


def get_worker_config():
    """Resolve the existing worker config lazily to avoid import cycles."""
    from open_webui.workers.file_processor import get_worker_config as factory

    return factory()


__all__ = ["get_worker_config"]
