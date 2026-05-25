"""Tests for the Home Assistant custom-component service helpers."""

from __future__ import annotations

from types import ModuleType, SimpleNamespace
from typing import Any
import sys

import pytest


def _install_homeassistant_stubs() -> None:
    """Install minimal HA module stubs so custom-component helpers can import."""
    modules = {
        "homeassistant": ModuleType("homeassistant"),
        "homeassistant.config_entries": ModuleType("homeassistant.config_entries"),
        "homeassistant.const": ModuleType("homeassistant.const"),
        "homeassistant.core": ModuleType("homeassistant.core"),
        "homeassistant.helpers": ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.entity": ModuleType("homeassistant.helpers.entity"),
        "homeassistant.helpers.event": ModuleType("homeassistant.helpers.event"),
        "homeassistant.helpers.typing": ModuleType("homeassistant.helpers.typing"),
        "homeassistant.components": ModuleType("homeassistant.components"),
        "homeassistant.components.http": ModuleType("homeassistant.components.http"),
    }
    for name, module in modules.items():
        sys.modules.setdefault(name, module)
    sys.modules["homeassistant.config_entries"].ConfigEntry = object
    sys.modules["homeassistant.const"].CONF_URL = "url"
    sys.modules["homeassistant.const"].CONF_TOKEN = "token"
    sys.modules["homeassistant.const"].Platform = SimpleNamespace(SENSOR="sensor")
    sys.modules["homeassistant.core"].HomeAssistant = object
    sys.modules["homeassistant.core"].ServiceCall = object
    sys.modules["homeassistant.core"].ServiceResponse = dict
    sys.modules["homeassistant.core"].SupportsResponse = SimpleNamespace(OPTIONAL="optional")
    sys.modules["homeassistant.helpers.entity"].Entity = object
    sys.modules["homeassistant.helpers.event"].async_track_state_change_event = lambda *a, **k: (lambda: None)
    sys.modules["homeassistant.helpers.typing"].ConfigType = dict
    sys.modules["homeassistant.components.http"].StaticPathConfig = lambda *a, **k: (a, k)


_install_homeassistant_stubs()

from custom_components.hermes.const import DOMAIN, normalize_wake_word
from custom_components.hermes import services as hermes_services


class FakeServiceRegistry:
    def __init__(self) -> None:
        self.registered: dict[tuple[str, str], Any] = {}
        self.schemas: dict[tuple[str, str], Any] = {}
        self.supports_response: dict[tuple[str, str], Any] = {}
        self.available: set[tuple[str, str]] = set()
        self.calls: list[dict[str, Any]] = []
        self.raise_on_call: Exception | None = None

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self.available or (domain, service) in self.registered

    def async_register(self, domain: str, service: str, handler: Any, **kwargs: Any) -> None:
        self.registered[(domain, service)] = handler
        self.schemas[(domain, service)] = kwargs.get("schema")
        self.supports_response[(domain, service)] = kwargs.get("supports_response")

    def async_remove(self, domain: str, service: str) -> None:
        self.registered.pop((domain, service), None)

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, Any],
        *,
        target: dict[str, Any] | None,
        blocking: bool,
        return_response: bool = False,
    ) -> dict[str, Any] | None:
        if self.raise_on_call:
            raise self.raise_on_call
        self.calls.append({
            "domain": domain,
            "service": service,
            "data": data,
            "target": target,
            "blocking": blocking,
            "return_response": return_response,
        })
        return {"changed": True} if return_response else None


class FakeStates:
    def __init__(self, states: list[Any]) -> None:
        self._states = states

    def async_all(self) -> list[Any]:
        return self._states


class FakeHass:
    def __init__(self) -> None:
        self.services = FakeServiceRegistry()
        self.states = FakeStates([])
        self.data: dict[str, Any] = {DOMAIN: {}}


class FakeCall:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data


class FakeBridge:
    connected = True

    def __init__(self) -> None:
        self.commands: list[dict[str, Any]] = []
        self._voice_ready = False
        self.media_player_entity = "media_player.default"

    async def async_relay_command(self, command: dict[str, Any]) -> dict[str, Any]:
        self.commands.append(command)
        return {"ok": True, "queued": False, "action": command["action"]}

    def status_snapshot(self) -> list[dict[str, Any]]:
        return [{"entity_id": "sensor.hermes_voice_ready", "state": "off", "attributes": {}}]


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("computer", ["computer"]),
        ("computer, hey jarvis\nok hermes", ["computer", "hey jarvis", "ok hermes"]),
        ([" computer ", "", "jarvis"], ["computer", "jarvis"]),
        (None, ["computer"]),
    ],
)
def test_normalize_wake_word(value: object, expected: list[str]) -> None:
    assert normalize_wake_word(value) == expected


def test_target_builder_merges_entity_area_device_and_explicit_target() -> None:
    target = hermes_services._build_target(
        {
            "target": {"entity_id": "light.kitchen"},
            "area_id": "living_room",
            "device_id": ["abc"],
        }
    )
    assert target == {"entity_id": "light.kitchen", "area_id": "living_room", "device_id": ["abc"]}


@pytest.mark.asyncio
async def test_hermes_command_returns_structured_success() -> None:
    hass = FakeHass()
    hass.services.available.add(("light", "turn_on"))
    await hermes_services.async_register_services(hass)  # type: ignore[arg-type]

    handler = hass.services.registered[(DOMAIN, hermes_services.SERVICE_HERMES_COMMAND)]
    response = await handler(
        FakeCall(
            {
                "domain": "light",
                "service": "turn_on",
                "entity_id": "light.kitchen",
                "data": {"brightness": 128},
                "blocking": True,
                "return_response": True,
            }
        )
    )

    assert response["ok"] is True
    assert response["domain"] == "light"
    assert response["service"] == "turn_on"
    assert response["blocking"] is True
    assert response["return_response"] is True
    assert response["result"] == {"changed": True}
    assert hass.services.calls == [
        {
            "domain": "light",
            "service": "turn_on",
            "data": {"brightness": 128},
            "target": {"entity_id": "light.kitchen"},
            "blocking": True,
            "return_response": True,
        }
    ]


@pytest.mark.asyncio
async def test_hermes_command_rejects_missing_service() -> None:
    hass = FakeHass()
    await hermes_services.async_register_services(hass)  # type: ignore[arg-type]

    handler = hass.services.registered[(DOMAIN, hermes_services.SERVICE_HERMES_COMMAND)]
    response = await handler(FakeCall({"domain": "light", "service": "explode"}))

    assert response == {"ok": False, "error": "service_not_found", "domain": "light", "service": "explode"}
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_hermes_command_returns_structured_error_on_exception() -> None:
    hass = FakeHass()
    hass.services.available.add(("light", "turn_on"))
    hass.services.raise_on_call = RuntimeError("boom")
    await hermes_services.async_register_services(hass)  # type: ignore[arg-type]

    handler = hass.services.registered[(DOMAIN, hermes_services.SERVICE_HERMES_COMMAND)]
    response = await handler(FakeCall({"domain": "light", "service": "turn_on", "area_id": "kitchen"}))

    assert response["ok"] is False
    assert response["error"] == "service_call_failed"
    assert response["message"] == "boom"
    assert response["target"] == {"area_id": "kitchen"}


@pytest.mark.asyncio
async def test_voice_settings_status_and_enable_return_per_entry_results() -> None:
    hass = FakeHass()
    bridge = FakeBridge()
    hass.data[DOMAIN]["entry-1"] = bridge
    await hermes_services.async_register_services(hass)  # type: ignore[arg-type]

    handler = hass.services.registered[(DOMAIN, hermes_services.SERVICE_VOICE_SETTINGS)]
    status = await handler(FakeCall({"action": "status", "entry_id": "entry-1"}))
    assert status["ok"] is True
    assert status["results"]["entry-1"]["connected"] is True

    enable = await handler(
        FakeCall(
            {
                "action": "enable",
                "entry_id": "entry-1",
                "media_player_entity": "media_player.living_room",
                "args": {"duration": 3},
            }
        )
    )
    assert enable["ok"] is True
    assert bridge.commands == [
        {
            "type": "voice_settings",
            "action": "enable",
            "media_player_entity": "media_player.living_room",
            "args": {"duration": 3},
        }
    ]


@pytest.mark.asyncio
async def test_voice_settings_enable_uses_configured_media_player_when_omitted() -> None:
    hass = FakeHass()
    bridge = FakeBridge()
    hass.data[DOMAIN]["entry-1"] = bridge
    await hermes_services.async_register_services(hass)  # type: ignore[arg-type]

    handler = hass.services.registered[(DOMAIN, hermes_services.SERVICE_VOICE_SETTINGS)]
    response = await handler(FakeCall({"action": "enable", "entry_id": "entry-1"}))

    assert response["ok"] is True
    assert bridge.commands[-1]["media_player_entity"] == "media_player.default"


@pytest.mark.asyncio
async def test_voice_settings_query_returns_limited_matches() -> None:
    hass = FakeHass()
    hass.states = FakeStates(
        [
            SimpleNamespace(entity_id="light.kitchen", state="on", attributes={"friendly_name": "Kitchen Light"}),
            SimpleNamespace(entity_id="light.bedroom", state="off", attributes={"friendly_name": "Bedroom Light"}),
            SimpleNamespace(entity_id="switch.kitchen_fan", state="off", attributes={"friendly_name": "Kitchen Fan"}),
        ]
    )
    await hermes_services.async_register_services(hass)  # type: ignore[arg-type]

    handler = hass.services.registered[(DOMAIN, hermes_services.SERVICE_VOICE_SETTINGS)]
    response = await handler(FakeCall({"query": "kitchen", "limit": 1, "include_attributes": False}))

    assert response == {
        "ok": True,
        "query": "kitchen",
        "count": 1,
        "limit": 1,
        "matches": [{"entity_id": "light.kitchen", "state": "on"}],
    }
