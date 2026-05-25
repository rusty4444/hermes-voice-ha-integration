"""Static behavioural checks for the HA custom component wiring.

The local test environment intentionally does not install Home Assistant. These
checks protect HA-facing wiring that would otherwise be easy to regress while
keeping the test suite lightweight and fully mocked.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _source(rel_path: str) -> str:
    return (ROOT / rel_path).read_text()


def test_async_setup_entry_passes_voice_options_to_bridge() -> None:
    source = _source("custom_components/hermes/__init__.py")
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "HermesBridge"]
    assert calls, "async_setup_entry should construct HermesBridge"
    keyword_names = {kw.arg for call in calls for kw in call.keywords}
    assert {
        "tts_engine",
        "tts_voice",
        "stt_engine",
        "stt_model",
        "wake_word_engine",
        "wake_word",
        "media_player_entity",
    } <= keyword_names


def test_bridge_normalizes_wake_word_and_forwards_voice_args() -> None:
    source = _source("custom_components/hermes/__init__.py")
    assert "self.wake_word = normalize_wake_word(wake_word)" in source
    assert '"tts_engine": self.tts_engine' in source
    assert '"wake_word": self.wake_word' in source
    assert '**dict(command.get("args") or {})' in source


def test_empty_entity_filter_tracks_all_state_changes_without_none() -> None:
    source = _source("custom_components/hermes/__init__.py")
    assert "entity_filter = normalize_list(" in source
    assert "if entity_filter:" in source
    assert 'hass.bus.async_listen("state_changed", bridge.on_state_change)' in source
    assert "tracked_entities = entity_filter or None" not in source


def test_options_flow_preserves_pending_init_values_until_final_create() -> None:
    source = _source("custom_components/hermes/config_flow.py")
    voice_method = source.split("async def async_step_voice", 1)[1].split("return self.async_show_form", 1)[0]
    assert "current.update(self._pending)" in voice_method
    assert "self._pending = None" not in voice_method
    assert "CONF_WAKE_WORD: normalize_wake_word(DEFAULT_WAKE_WORD)" in source


def test_status_sensor_unique_ids_are_entry_scoped() -> None:
    source = _source("custom_components/hermes/sensor.py")
    assert 'self._attr_unique_id = f"{DOMAIN}_{entry_id}_{description.key}"' in source
    assert "HermesStatusSensor(coordinator, desc, entry.entry_id)" in source
