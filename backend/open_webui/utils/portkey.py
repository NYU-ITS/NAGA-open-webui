import logging

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


def find_workspace_portkey_key(user_email: str | None = None) -> str:
    """Return the Portkey API key for the given admin from their config row.

    When user_email is provided the lookup is scoped to that admin only —
    no cross-admin key leakage. Pass None only for startup / migration callers
    that run before any request context exists; those fall back to scanning
    all admin rows and returning the first non-empty match."""
    from open_webui.config import Config
    from open_webui.internal.db import get_db

    paths = ["rag.openai_api_key", "audio.stt.portkey.api_key", "audio.tts.portkey.api_key"]

    with get_db() as db:
        query = db.query(Config)
        if user_email:
            query = query.filter(Config.email == user_email)
        for entry in query.all():
            data = entry.data or {}
            for path in paths:
                value = data
                for part in path.split("."):
                    value = value.get(part, {}) if isinstance(value, dict) else {}
                if isinstance(value, str) and value:
                    return value

    log.debug("No workspace Portkey key found in config table (user_email=%s)", user_email)
    return ""


def find_workspace_portkey_url() -> str:
    """Return the current workspace Portkey gateway URL.

    The URL is a global PersistentConfig (RAG_OPENAI_API_BASE_URL) — not
    per-admin. AppConfig.__setattr__ updates .value and calls .save() on the
    same object, so .value is always the live value without a DB query."""
    from open_webui.config import RAG_OPENAI_API_BASE_URL

    _default = "https://ai-gateway.apps.cloud.rt.nyu.edu/v1"
    try:
        url = RAG_OPENAI_API_BASE_URL.value
        return url if url else _default
    except Exception:
        log.debug("Could not read RAG_OPENAI_API_BASE_URL, using default")
        return _default
