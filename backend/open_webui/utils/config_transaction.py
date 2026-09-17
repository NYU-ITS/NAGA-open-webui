"""Stage AppConfig edits without publishing them before their transaction commits."""

from copy import deepcopy
from datetime import datetime
import logging

from open_webui import config as config_module
from open_webui.config import Config, GLOBAL_CONFIG_EMAIL, PersistentConfig, UserScopedConfig

log = logging.getLogger(__name__)
_MISSING = object()


def _read(data, path, default=None):
    for part in path.split("."):
        if not isinstance(data, dict) or part not in data:
            return default
        data = data[part]
    return data


def _write(data, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        if not isinstance(data.get(part), dict):
            data[part] = {}
        data = data[part]
    data[parts[-1]] = deepcopy(value)


class ConfigUpdateConflict(Exception):
    """A concurrent save changed one of the values used by this proposal."""


class _ScopedValue:
    def __init__(self, proposal, item):
        self.proposal = proposal
        self.item = item

    def get(self, email):
        return self.proposal.get_value(email, self.item.config_path, self.item.default)

    def set(self, email, value, db=None):
        self.proposal.set_value(email, self.item.config_path, value)


class ConfigTransaction:
    """Admin-only config view backed by a caller-owned SQLAlchemy transaction.

    Reads use database snapshots rather than process-local caches. Assignments
    and scoped .set() calls only stage values. persist() merges changed paths
    under row locks; publish() must be called only after the caller commits.
    """

    def __init__(self, app_config, db):
        object.__setattr__(self, "_config", app_config)
        object.__setattr__(self, "_db", db)
        object.__setattr__(self, "_original", {})
        object.__setattr__(self, "_updates", {})
        object.__setattr__(self, "_committed", {})

    def _row(self, email, lock=False):
        query = self._db.query(Config).filter_by(email=email, version=0)
        if lock:
            query = query.populate_existing().with_for_update()
        row = query.first()
        if row is None and email == GLOBAL_CONFIG_EMAIL:
            query = self._db.query(Config).filter(Config.email.is_(None)).order_by(Config.id)
            if lock:
                query = query.populate_existing().with_for_update()
            row = query.first()
        return row

    def _snapshot(self, email):
        if email not in self._original:
            row = self._row(email)
            self._original[email] = deepcopy(row.data) if row else {}
        return self._original[email]

    def get_value(self, email, path, default=None):
        return self._updates.get((email, path), _read(self._snapshot(email), path, default))

    def set_value(self, email, path, value):
        self._snapshot(email)
        self._updates[email, path] = value

    def __getattr__(self, name):
        item = self._config._state.get(name)
        if isinstance(item, UserScopedConfig):
            return _ScopedValue(self, item)
        if isinstance(item, PersistentConfig):
            return self.get_value(GLOBAL_CONFIG_EMAIL, item.config_path, item.env_value)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        item = self._config._state.get(name)
        if not isinstance(item, PersistentConfig):
            raise TypeError(f"{name} is not a global persistent setting")
        self.set_value(GLOBAL_CONFIG_EMAIL, item.config_path, value)

    def persist(self):
        for email in sorted({email for email, _ in self._updates}):
            row = self._row(email, lock=True)
            current = deepcopy(row.data) if row else {}
            original = self._original[email]
            # The whole snapshot influenced recipe/model validation. Reject a
            # concurrent edit rather than committing a job built from stale data.
            if current != original:
                raise ConfigUpdateConflict()
            for (owner, path), value in self._updates.items():
                if owner == email:
                    _write(current, path, value)
            if row is None:
                row = Config(email=email, version=0, data=current)
                self._db.add(row)
            else:
                row.email = email
                row.data = current
                row.updated_at = datetime.now()
            self._committed[email] = current
        self._db.flush()

    def publish(self):
        global_data = self._committed.get(GLOBAL_CONFIG_EMAIL)
        if global_data is not None:
            config_module.CONFIG_DATA = deepcopy(global_data)
            for item in config_module.PERSISTENT_CONFIG_REGISTRY:
                value = _read(global_data, item.config_path, _MISSING)
                if value is not _MISSING:
                    item.value = value
                    item.config_value = value
        for email, path in self._updates:
            if email != GLOBAL_CONFIG_EMAIL:
                try:
                    config_module.invalidate_user_scoped_config_cache(email, path)
                except Exception:
                    log.exception("Could not invalidate committed settings cache")
