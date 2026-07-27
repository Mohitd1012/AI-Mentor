"""
RoleManager — load, persist, and switch roles.

Storage:
  • Built-in roles live in backend/roles/builtin/*.json  (read-only)
  • Custom roles live in backend/roles/custom/*.json     (user-writable)

On startup, all roles are loaded into memory. Custom roles take precedence
over built-ins with the same id (so the user can override a built-in).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from modules.role_manager.models import Role

logger = logging.getLogger(__name__)

# Default role IDs
DEFAULT_ROLE_ID = "default"

# Path layout: backend/roles/{builtin,custom}/
_ROLES_DIR  = Path(__file__).resolve().parents[2] / "roles"
_BUILTIN_DIR = _ROLES_DIR / "builtin"
_CUSTOM_DIR  = _ROLES_DIR / "custom"


class RoleManager:
    def __init__(self) -> None:
        self._roles: dict[str, Role] = {}
        self._active_id: str = DEFAULT_ROLE_ID
        self._load_all()

    # ── Loading ───────────────────────────────────────────────────────────────

    def _load_all(self) -> None:
        loaded = 0
        # Built-ins first
        if _BUILTIN_DIR.exists():
            for p in sorted(_BUILTIN_DIR.glob("*.json")):
                role = self._load_file(p, is_builtin=True)
                if role:
                    self._roles[role.id] = role
                    loaded += 1
        # Custom overrides
        _CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
        for p in sorted(_CUSTOM_DIR.glob("*.json")):
            role = self._load_file(p, is_builtin=False)
            if role:
                self._roles[role.id] = role
                loaded += 1
        logger.info("[roles] loaded %d roles (active=%s)", loaded, self._active_id)

    @staticmethod
    def _load_file(path: Path, is_builtin: bool) -> Optional[Role]:
        try:
            data = json.loads(path.read_text())
            data["is_builtin"] = is_builtin
            return Role(**data)
        except Exception as exc:
            logger.warning("[roles] failed to load %s: %s", path, exc)
            return None

    # ── CRUD ──────────────────────────────────────────────────────────────────

    def list_roles(self) -> list[Role]:
        return sorted(self._roles.values(), key=lambda r: (not r.is_builtin, r.name))

    def get(self, role_id: str) -> Optional[Role]:
        return self._roles.get(role_id)

    def set_active(self, role_id: str) -> Role:
        if role_id not in self._roles:
            raise KeyError(f"Role not found: {role_id}")
        self._active_id = role_id
        logger.info("[roles] active → %s", role_id)
        return self._roles[role_id]

    @property
    def active_id(self) -> str:
        return self._active_id

    @property
    def active(self) -> Role:
        return self._roles.get(self._active_id) or self._roles[DEFAULT_ROLE_ID]

    def upsert(self, role: Role) -> Role:
        """Create or update a custom role. Built-ins cannot be overwritten in-place."""
        role.is_builtin = False
        self._roles[role.id] = role
        path = _CUSTOM_DIR / f"{role.id}.json"
        path.write_text(role.model_dump_json(indent=2))
        logger.info("[roles] saved custom role %s", role.id)
        return role

    def delete(self, role_id: str) -> bool:
        if role_id == DEFAULT_ROLE_ID:
            raise ValueError("Cannot delete the default role")
        role = self._roles.get(role_id)
        if not role:
            return False
        if role.is_builtin:
            raise ValueError(f"Cannot delete built-in role {role_id}")
        path = _CUSTOM_DIR / f"{role_id}.json"
        if path.exists():
            path.unlink()
        del self._roles[role_id]
        if self._active_id == role_id:
            self._active_id = DEFAULT_ROLE_ID
        logger.info("[roles] deleted %s", role_id)
        return True

    def reload(self) -> None:
        self._roles.clear()
        self._load_all()
