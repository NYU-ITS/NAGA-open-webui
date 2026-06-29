import logging

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MAIN"])


def find_workspace_portkey_key() -> str:
    """Read the workspace's existing Portkey API key directly from the config
    table. Checks the same config paths RAG_OPENAI_API_KEY /
    AUDIO_*_PORTKEY_API_KEY use, across all admins' config rows - no
    per-request email scoping needed for the startup-migration / new-function
    callers of this helper. Returns the first non-empty match, or "" if none."""
    from open_webui.config import Config
    from open_webui.internal.db import get_db

    paths = ["rag.openai_api_key", "audio.stt.portkey.api_key", "audio.tts.portkey.api_key"]

    with get_db() as db:
        for entry in db.query(Config).all():
            data = entry.data or {}
            for path in paths:
                value = data
                for part in path.split("."):
                    value = value.get(part, {}) if isinstance(value, dict) else {}
                if isinstance(value, str) and value:
                    return value

    log.debug("No workspace Portkey key found in config table")
    return ""
