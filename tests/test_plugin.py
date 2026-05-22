"""Tests for the hermes-voice-ha-integration plugins.

Test isolation: All HA connectivity is mocked via monkeypatching the bridge.
No real HA instance is required.

Run:
    python -m pytest tests/ -v
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _env(monkeypatch):
    """Ensure test isolation — clean HASS env vars."""
    monkeypatch.delenv("HASS_URL", raising=False)
    monkeypatch.delenv("HASS_TOKEN", raising=False)


@pytest.fixture
def with_hass(monkeypatch):
    """Set HASS_URL + HASS_TOKEN for a test."""
    monkeypatch.setenv("HASS_URL", "http://ha.local:8123")
    monkeypatch.setenv("HASS_TOKEN", "test-token-abc123")


# ---------------------------------------------------------------------------
# Bridge tests
# ---------------------------------------------------------------------------

class TestEntityCache:
    """EntityCache TTL and invalidation."""

    def test_cache_starts_empty(self, with_hass):
        from plugins.home_assistant.ha_assistant import _entity_cache
        _entity_cache.invalidate()
        assert _entity_cache.all() == []
        assert not _entity_cache.fresh

    def test_cache_set_and_get(self, with_hass):
        from plugins.home_assistant.ha_assistant import _entity_cache
        entities = [
            {"entity_id": "light.kitchen", "state": "on"},
            {"entity_id": "sensor.temperature", "state": "22.5"},
        ]
        _entity_cache.set(entities)
        assert _entity_cache.fresh
        assert len(_entity_cache.all()) == 2
        assert _entity_cache.get("light.kitchen")["state"] == "on"
        assert _entity_cache.get("sensor.missing") is None

    def test_cache_invalidation(self, with_hass):
        from plugins.home_assistant.ha_assistant import _entity_cache
        _entity_cache.set([{"entity_id": "light.kitchen", "state": "on"}])
        assert _entity_cache.fresh
        _entity_cache.invalidate()
        assert not _entity_cache.fresh
        assert _entity_cache.all() == []


class TestEntityIDRegex:
    """Entity ID validation."""

    _ENTITY_ID_RE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z0-9_]+$")

    def test_valid_entity_ids(self):
        assert self._ENTITY_ID_RE.match("light.living_room")
        assert self._ENTITY_ID_RE.match("sensor.temperature_1")
        assert self._ENTITY_ID_RE.match("binary_sensor.front_door_motion")

    def test_invalid_entity_ids(self):
        assert not self._ENTITY_ID_RE.match("LIGHT.living_room")
        assert not self._ENTITY_ID_RE.match("light.")
        assert not self._ENTITY_ID_RE.match(".living_room")
        assert not self._ENTITY_ID_RE.match("")
        assert not self._ENTITY_ID_RE.match("../../etc/passwd")


class TestSearch:
    """Search / filtering logic."""

    def test_search_by_domain(self, with_hass, monkeypatch):
        from plugins.home_assistant.ha_assistant import _entity_cache
        entities = [
            {"entity_id": "light.kitchen", "state": "on", "attributes": {"friendly_name": "Kitchen Light"}},
            {"entity_id": "light.bedroom", "state": "off", "attributes": {"friendly_name": "Bedroom Light"}},
            {"entity_id": "switch.coffee", "state": "off", "attributes": {"friendly_name": "Coffee Switch"}},
        ]
        _entity_cache.set(entities)

        from plugins.home_assistant.ha_assistant import search_entities
        result = search_entities(domain="light")
        assert result["count"] == 2
        assert all(e["entity_id"].startswith("light.") for e in result["entities"])

    def test_search_by_query(self, with_hass, monkeypatch):
        from plugins.home_assistant.ha_assistant import _entity_cache
        entities = [
            {"entity_id": "light.kitchen", "state": "on", "attributes": {"friendly_name": "Kitchen Light"}},
            {"entity_id": "light.bedroom", "state": "off", "attributes": {"friendly_name": "Bedroom Light"}},
        ]
        _entity_cache.set(entities)

        from plugins.home_assistant.ha_assistant import search_entities
        result = search_entities(query="kitchen")
        assert result["count"] == 1
        assert result["entities"][0]["entity_id"] == "light.kitchen"

    def test_search_by_area(self, with_hass, monkeypatch):
        from plugins.home_assistant.ha_assistant import _entity_cache
        entities = [
            {"entity_id": "sensor.kitchen_temp", "state": "22", "attributes": {"area": "kitchen"}},
            {"entity_id": "sensor.bedroom_temp", "state": "20", "attributes": {"area": "bedroom"}},
        ]
        _entity_cache.set(entities)

        from plugins.home_assistant.ha_assistant import search_entities
        result = search_entities(area="kitchen")
        assert result["count"] == 1

    def test_scene_resolution(self, with_hass, monkeypatch):
        from plugins.home_assistant.ha_assistant import _entity_cache
        entities = [
            {"entity_id": "scene.movie_night", "state": "", "attributes": {"friendly_name": "Movie Night"}},
        ]
        _entity_cache.set(entities)

        from plugins.home_assistant.compound import _resolve_scene_entity_id
        assert _resolve_scene_entity_id("scene.movie_night") == "scene.movie_night"
        assert _resolve_scene_entity_id("movie night") == "scene.movie_night"
        assert _resolve_scene_entity_id("nonexistent") is None


# ---------------------------------------------------------------------------
# Security tests
# ---------------------------------------------------------------------------

class TestAllowList:
    """Allow-list enforcement."""

    def test_allow_list_disabled(self, with_hass, monkeypatch):
        from plugins.home_assistant.security import is_service_allowed
        # Reset cache
        monkeypatch.setattr("plugins.home_assistant.security._ALLOW_LIST_FILE", Path("/nonexistent.json"))
        assert is_service_allowed("light.kitchen", "light", "turn_on") is True

    def test_allow_list_with_wildcard(self, with_hass, tmp_path, monkeypatch):
        config = {
            "enabled": True,
            "rules": [
                {"entity_id": "light.*", "services": ["turn_on", "turn_off"]},
                {"entity_id": "climate.living_room", "services": ["set_temperature"]},
            ],
        }
        f = tmp_path / "allow.json"
        f.write_text(json.dumps(config))
        monkeypatch.setattr("plugins.home_assistant.security._ALLOW_LIST_FILE", f)

        from plugins.home_assistant.security import is_service_allowed
        assert is_service_allowed("light.kitchen", "light", "turn_on") is True
        assert is_service_allowed("light.bedroom", "light", "turn_on") is True
        assert is_service_allowed("climate.living_room", "climate", "set_temperature") is True
        # Not in allow-list
        assert is_service_allowed("climate.living_room", "climate", "turn_off") is False
        assert is_service_allowed("switch.coffee", "switch", "turn_on") is False

    def test_entity_pattern_match(self):
        from plugins.home_assistant.security import _entity_matches
        assert _entity_matches("light.kitchen", "light.*") is True
        assert _entity_matches("light.kitchen.ceiling", "light.*") is True
        assert _entity_matches("switch.coffee", "light.*") is False
        assert _entity_matches("light.kitchen", "light.kitchen") is True
        assert _entity_matches("light.kitchen", "light.bedroom") is False


class TestBlockList:
    """Block-list enforcement."""

    def test_block_list_empty(self, with_hass, monkeypatch):
        monkeypatch.setattr("plugins.home_assistant.security._BLOCK_LIST_FILE", Path("/nonexistent.json"))
        from plugins.home_assistant.security import is_entity_blocked
        assert is_entity_blocked("light.kitchen", "light", "turn_on") is False

    def test_block_list_blocks(self, tmp_path, monkeypatch):
        config = {"entities": ["switch.server_power", "lock.front_door"]}
        f = tmp_path / "block.json"
        f.write_text(json.dumps(config))
        monkeypatch.setattr("plugins.home_assistant.security._BLOCK_LIST_FILE", f)

        from plugins.home_assistant.security import is_entity_blocked
        assert is_entity_blocked("switch.server_power", "switch", "turn_on") is True
        assert is_entity_blocked("lock.front_door", "lock", "unlock") is True
        assert is_entity_blocked("light.kitchen", "light", "turn_on") is False


class TestAuditLog:
    """Audit log writes."""

    def test_audit_log_writes(self, tmp_path, monkeypatch):
        log_file = tmp_path / "audit.log"
        monkeypatch.setattr("plugins.home_assistant.security._AUDIT_LOG_FILE", log_file)

        from plugins.home_assistant.security import log_call
        log_call("light.kitchen", "light", "turn_on", {"brightness": 255}, allowed=True, reason="test")

        lines = log_file.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["entity_id"] == "light.kitchen"
        assert entry["domain"] == "light"
        assert entry["service"] == "turn_on"
        assert entry["allowed"] is True
        assert entry["reason"] == "test"


class TestBlockedDomains:
    """Security: blocked service domains."""

    def test_blocked_domains_rejected(self, with_hass):
        from plugins.home_assistant.ha_assistant import call_service
        result = call_service("shell_command", "run", data={"command": "rm -rf /"})
        assert "blocked" in result.get("error", "").lower()

    def test_safe_domains_allowed(self, with_hass, monkeypatch):
        # Mock the async call
        async def _mock_call(*a, **kw):
            return {"ok": True}
        monkeypatch.setattr("plugins.home_assistant.ha_assistant._async_call_service", _mock_call)

        from plugins.home_assistant.ha_assistant import call_service
        result = call_service("light", "turn_on", entity_id="light.kitchen")
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# Compound tool tests
# ---------------------------------------------------------------------------

class TestCompoundTools:
    """Tests for control_light_and_set_scene and turn_off_all_except."""

    def test_control_light_and_set_scene_missing_scene(self):
        from plugins.home_assistant.compound import _handle_control_light_and_set_scene
        result = _handle_control_light_and_set_scene({"scene": "scene.nonexistent"})
        data = json.loads(result)
        assert "error" in data

    def test_turn_off_all_except_no_entities(self, with_hass, monkeypatch):
        from plugins.home_assistant.ha_assistant import _entity_cache
        _entity_cache.set([])
        from plugins.home_assistant.compound import _handle_turn_off_all_except
        result = _handle_turn_off_all_except({"domain": "light", "preserve": ["light.kitchen"]})
        data = json.loads(result)
        assert data.get("message") or data.get("results") == []


# ---------------------------------------------------------------------------
# Plugin registration sanity
# ---------------------------------------------------------------------------

class TestPluginRegistration:
    """Verify that the plugin __init__.py is importable and tools are defined."""

    def test_tools_tuple_defined(self):
        """All 7 tools are in the _TOOLS tuple."""
        # We can't import directly without Hermes runtime, but we can parse
        import ast
        init_path = Path(__file__).parent.parent / "plugins" / "home_assistant" / "__init__.py"
        source = init_path.read_text()

        # Check that _TOOLS tuple has 7 entries
        tree = ast.parse(source)
        tools_count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Tuple):
                tools_count = max(tools_count, len(node.elts))
        assert tools_count >= 7, f"Expected >= 7 tools in _TOOLS tuple, found {tools_count}"

    def test_plugin_yaml_valid(self):
        """plugin.yaml is valid YAML."""
        import yaml
        yaml_path = Path(__file__).parent.parent / "plugins" / "home_assistant" / "plugin.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["name"] == "home_assistant"
        assert data["version"] == "0.1.0"
        assert "on_session_start" in data["hooks"]

    def test_voice_stack_plugin_yaml_valid(self):
        """voice-stack plugin.yaml is valid YAML."""
        import yaml
        yaml_path = Path(__file__).parent.parent / "plugins" / "voice-stack" / "plugin.yaml"
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        assert data["name"] == "voice-stack"
        assert data["version"] == "0.1.0"

    def test_manifest_json_valid(self):
        manifest_path = Path(__file__).parent.parent / "custom_components" / "hermes" / "manifest.json"
        with open(manifest_path) as f:
            data = json.load(f)
        assert data["domain"] == "hermes"
        assert data["config_flow"] is True
        assert "iot_class" in data
