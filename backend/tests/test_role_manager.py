"""
Tests for Phase 6 — Role Engine.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch

from modules.role_manager import RoleManager, Role, DEFAULT_ROLE_ID


# ── Role model ────────────────────────────────────────────────────────────────

class TestRoleModel:
    def test_minimum_fields(self):
        r = Role(id="x", name="X")
        assert r.id == "x"
        assert r.proactivity == 2
        assert r.voice == "af_heart"
        assert r.is_builtin is False

    def test_auto_generated_prompt_includes_name(self):
        r = Role(id="x", name="Test Coach", description="Helps you test.",
                 expertise=["pytest", "hypothesis"])
        prompt = r.build_system_prompt()
        assert "Test Coach" in prompt
        assert "pytest" in prompt

    def test_explicit_prompt_overrides_auto(self):
        custom = "You are a poet. Speak only in haiku."
        r = Role(id="x", name="X", system_prompt=custom)
        assert r.build_system_prompt() == custom

    def test_humor_level_appears_in_prompt(self):
        low  = Role(id="x", name="X", humor_level=0).build_system_prompt()
        high = Role(id="x", name="X", humor_level=5).build_system_prompt()
        assert "professional" in low.lower()
        assert "playful" in high.lower() or "witty" in high.lower()

    def test_proactivity_clamped(self):
        with pytest.raises(Exception):
            Role(id="x", name="X", proactivity=99)

    def test_invalid_teaching_style_rejected(self):
        with pytest.raises(Exception):
            Role(id="x", name="X", teaching_style="banter")


# ── Built-in catalog ──────────────────────────────────────────────────────────

class TestBuiltins:
    def test_default_role_loaded(self):
        mgr = RoleManager()
        assert mgr.get(DEFAULT_ROLE_ID) is not None

    def test_several_builtins_loaded(self):
        mgr = RoleManager()
        roles = mgr.list_roles()
        # We ship 12 built-ins
        assert len(roles) >= 12
        ids = {r.id for r in roles}
        for expected in ("default", "senior-architect", "pair-programmer",
                         "interview-coach", "trading-mentor"):
            assert expected in ids, f"Missing built-in: {expected}"

    def test_builtins_marked_as_builtin(self):
        mgr = RoleManager()
        for role in mgr.list_roles():
            # Note: `default` may be overridden by a user JSON in roles/custom/,
            # in which case it's loaded as custom (is_builtin=False).
            # The other built-ins should always remain marked as built-in.
            if role.id in ("senior-architect", "pair-programmer"):
                assert role.is_builtin is True

    def test_active_starts_as_default(self):
        mgr = RoleManager()
        assert mgr.active_id == DEFAULT_ROLE_ID


# ── set_active / hot-swap ─────────────────────────────────────────────────────

class TestSetActive:
    def test_set_active_returns_role(self):
        mgr = RoleManager()
        role = mgr.set_active("senior-architect")
        assert role.id == "senior-architect"
        assert mgr.active_id == "senior-architect"

    def test_set_active_unknown_raises(self):
        mgr = RoleManager()
        with pytest.raises(KeyError):
            mgr.set_active("does-not-exist")

    def test_active_property_returns_role_object(self):
        mgr = RoleManager()
        mgr.set_active("pair-programmer")
        assert mgr.active.name == "Pair Programmer"


# ── Custom roles (upsert / delete) ────────────────────────────────────────────

class TestCustomRoles:
    def test_upsert_creates_custom(self, tmp_path, monkeypatch):
        from modules.role_manager import manager as mgr_module
        monkeypatch.setattr(mgr_module, "_CUSTOM_DIR", tmp_path)
        mgr = RoleManager()

        custom = Role(id="my-custom", name="My Custom Role",
                      description="Test", expertise=["testing"])
        saved = mgr.upsert(custom)

        # is_builtin always False for custom
        assert saved.is_builtin is False
        # File persisted
        assert (tmp_path / "my-custom.json").exists()
        # In-memory roster includes it
        assert mgr.get("my-custom") is not None

    def test_custom_overrides_builtin(self, tmp_path, monkeypatch):
        from modules.role_manager import manager as mgr_module
        monkeypatch.setattr(mgr_module, "_CUSTOM_DIR", tmp_path)

        # Override the default role
        override = Role(id="default", name="My Override",
                        description="Custom version")
        (tmp_path / "default.json").write_text(override.model_dump_json())

        mgr = RoleManager()
        loaded = mgr.get("default")
        assert loaded.name == "My Override"
        assert loaded.is_builtin is False

    def test_cannot_delete_default(self):
        mgr = RoleManager()
        with pytest.raises(ValueError):
            mgr.delete(DEFAULT_ROLE_ID)

    def test_cannot_delete_builtin(self):
        mgr = RoleManager()
        with pytest.raises(ValueError):
            mgr.delete("senior-architect")

    def test_delete_custom_role(self, tmp_path, monkeypatch):
        from modules.role_manager import manager as mgr_module
        monkeypatch.setattr(mgr_module, "_CUSTOM_DIR", tmp_path)
        mgr = RoleManager()
        mgr.upsert(Role(id="to-delete", name="Temp"))
        assert mgr.delete("to-delete") is True
        assert mgr.get("to-delete") is None
        assert not (tmp_path / "to-delete.json").exists()

    def test_delete_active_falls_back_to_default(self, tmp_path, monkeypatch):
        from modules.role_manager import manager as mgr_module
        monkeypatch.setattr(mgr_module, "_CUSTOM_DIR", tmp_path)
        mgr = RoleManager()
        mgr.upsert(Role(id="my-role", name="Mine"))
        mgr.set_active("my-role")
        mgr.delete("my-role")
        assert mgr.active_id == DEFAULT_ROLE_ID


# ── Orchestrator integration ──────────────────────────────────────────────────

class TestRoleApplication:
    def test_apply_role_updates_router_prompt(self):
        from modules.ai_router.router import AIRouter
        from modules.react_planner import ConversationOrchestrator
        router = AIRouter()
        orch = ConversationOrchestrator(router)

        role = Role(id="custom", name="Pirate Mentor",
                    system_prompt="Yarrr, speak like a pirate.",
                    conversation_mode="socratic", proactivity=3,
                    voice="am_onyx")
        orch.apply_role(role)

        assert "pirate" in router._base_prompt.lower()
        assert orch.mode.value == "socratic"
        assert orch.proactivity == 3

    def test_apply_role_with_provider_pref(self):
        from modules.ai_router.router import AIRouter
        from modules.react_planner import ConversationOrchestrator
        router = AIRouter()
        orch = ConversationOrchestrator(router)

        role = Role(id="x", name="X", preferred_provider="ollama")
        orch.apply_role(role)
        assert router.preferred_provider == "ollama"
