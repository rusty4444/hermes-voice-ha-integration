"""Hermes Home Assistant services."""

from __future__ import annotations

import logging
from typing import Any

try:
    import voluptuous as vol
except ModuleNotFoundError:  # pragma: no cover - Home Assistant provides voluptuous
    class _VolFallback:
        ALLOW_EXTRA = object()

        def Schema(self, schema: Any, *args: Any, **kwargs: Any) -> Any:
            return schema

        def Required(self, key: str, *args: Any, **kwargs: Any) -> str:
            return key

        def Optional(self, key: str, *args: Any, **kwargs: Any) -> str:
            return key

        def Any(self, *args: Any, **kwargs: Any) -> Any:
            return object

    vol = _VolFallback()  # type: ignore[assignment]

try:
    from homeassistant.core import HomeAssistant, ServiceCall
except ModuleNotFoundError:  # pragma: no cover - lets pure unit tests import helpers
    class HomeAssistant:  # type: ignore[no-redef]
        pass

    class ServiceCall:  # type: ignore[no-redef]
        data: dict[str, Any]

try:
    from homeassistant.core import SupportsResponse
except (ImportError, ModuleNotFoundError):  # pragma: no cover - older HA/test stubs
    class SupportsResponse:  # type: ignore[no-redef]
        OPTIONAL = "optional"

from .const import DEFAULT_QUERY_LIMIT, DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_HERMES_COMMAND = "hermes_command"
SERVICE_VOICE_SETTINGS = "voice_settings"


def _as_bool(value: Any, default: bool = False) -> bool:
    """Parse bool-ish service values from HA forms/API calls."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _as_int(value: Any, default: int, minimum: int = 1, maximum: int = 500) -> int:
    """Parse and clamp integer service values."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _build_target(call_data: dict[str, Any]) -> dict[str, Any] | None:
    """Build a Home Assistant service target from entity/area/device fields."""
    target: dict[str, Any] = {}
    explicit = call_data.get("target")
    if isinstance(explicit, dict):
        target.update({k: v for k, v in explicit.items() if v not in (None, "", [])})
    for key in ("entity_id", "area_id", "device_id"):
        value = call_data.get(key)
        if value not in (None, "", []):
            target[key] = value
    return target or None


def _bridge_status(bridge: Any) -> dict[str, Any]:
    """Return a compact status payload for a bridge-like object."""
    if hasattr(bridge, "status_snapshot"):
        snapshot = bridge.status_snapshot()
    else:
        snapshot = []
    return {
        "connected": bool(getattr(bridge, "connected", False)),
        "voice_ready": bool(getattr(bridge, "_voice_ready", False)),
        "status": snapshot,
    }


def _iter_target_bridges(hass: HomeAssistant, entry_id: str | None = None) -> list[tuple[str, Any]]:
    """Return bridge entries targeted by a service call."""
    entries = list(hass.data.get(DOMAIN, {}).items())
    if entry_id:
        entries = [(eid, bridge) for eid, bridge in entries if eid == entry_id]
    return entries


def _entity_matches(state: Any, query: str) -> bool:
    """Return whether a HA state object matches a voice-settings query."""
    friendly_name = str(getattr(state, "attributes", {}).get("friendly_name", ""))
    haystack = f"{state.entity_id} {friendly_name}".lower()
    return not query or query in haystack


def _state_payload(state: Any, include_attributes: bool = True) -> dict[str, Any]:
    """Convert a Home Assistant state object into service response data."""
    payload = {"entity_id": state.entity_id, "state": state.state}
    if include_attributes:
        payload["attributes"] = dict(getattr(state, "attributes", {}) or {})
    return payload


COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required("domain"): str,
        vol.Required("service"): str,
        vol.Optional("entity_id"): vol.Any(str, list),
        vol.Optional("area_id"): vol.Any(str, list),
        vol.Optional("device_id"): vol.Any(str, list),
        vol.Optional("target"): dict,
        vol.Optional("data", default={}): dict,
        vol.Optional("blocking", default=True): bool,
        vol.Optional("return_response", default=False): bool,
    },
    extra=getattr(vol, "ALLOW_EXTRA", True),
)

VOICE_SCHEMA = vol.Schema(
    {
        vol.Optional("action"): str,
        vol.Optional("query", default=""): str,
        vol.Optional("entry_id"): str,
        vol.Optional("media_player_entity"): str,
        vol.Optional("args", default={}): dict,
        vol.Optional("limit", default=DEFAULT_QUERY_LIMIT): int,
        vol.Optional("include_attributes", default=True): bool,
    },
    extra=getattr(vol, "ALLOW_EXTRA", True),
)


async def async_register_services(hass: HomeAssistant) -> None:
    """Register HA-native services used by the Hermes integration."""

    async def _handle_hermes_command(call: ServiceCall) -> dict[str, Any]:
        call_data = dict(call.data)
        domain = str(call_data.get("domain", "")).strip()
        service = str(call_data.get("service", "")).strip()
        service_data = dict(call_data.get("data") or {})
        target = _build_target(call_data)
        blocking = _as_bool(call_data.get("blocking"), default=True)
        return_response = _as_bool(call_data.get("return_response"), default=False)

        if not domain or not service:
            return {"ok": False, "error": "domain_and_service_required", "domain": domain, "service": service}

        if not hass.services.has_service(domain, service):
            _LOGGER.warning("Hermes command rejected; service not found: %s.%s", domain, service)
            return {"ok": False, "error": "service_not_found", "domain": domain, "service": service}

        try:
            try:
                result = await hass.services.async_call(
                    domain,
                    service,
                    service_data,
                    target=target,
                    blocking=blocking,
                    return_response=return_response,
                )
            except TypeError:
                result = await hass.services.async_call(
                    domain,
                    service,
                    service_data,
                    target=target,
                    blocking=blocking,
                )
        except Exception as exc:  # noqa: BLE001 - HA integrations return structured service errors
            _LOGGER.warning("Hermes command failed: %s.%s: %s", domain, service, exc)
            return {
                "ok": False,
                "error": "service_call_failed",
                "message": str(exc),
                "domain": domain,
                "service": service,
                "target": target,
            }

        _LOGGER.info("Hermes command dispatched: %s.%s target=%s", domain, service, target)
        response: dict[str, Any] = {
            "ok": True,
            "domain": domain,
            "service": service,
            "target": target,
            "blocking": blocking,
            "return_response": return_response,
        }
        if result is not None:
            response["result"] = result
        return response

    async def _handle_voice_settings(call: ServiceCall) -> dict[str, Any]:
        call_data = dict(call.data)
        query = str(call_data.get("query", "")).lower().strip()
        action = str(call_data.get("action") or query).lower().strip()
        entry_id = str(call_data.get("entry_id") or "").strip() or None
        limit = _as_int(call_data.get("limit"), DEFAULT_QUERY_LIMIT, minimum=1, maximum=500)
        include_attributes = _as_bool(call_data.get("include_attributes"), default=True)

        if action in {"enable", "disable", "status"}:
            entries = _iter_target_bridges(hass, entry_id)
            if entry_id and not entries:
                return {"ok": False, "error": "entry_not_found", "entry_id": entry_id}

            results: dict[str, Any] = {}
            for bridge_entry_id, bridge in entries:
                if action == "status":
                    results[bridge_entry_id] = _bridge_status(bridge)
                    continue
                if not hasattr(bridge, "async_relay_command"):
                    results[bridge_entry_id] = {"ok": False, "error": "bridge_not_relay_capable"}
                    continue
                media_player_entity = call_data.get("media_player_entity") or getattr(bridge, "media_player_entity", "")
                results[bridge_entry_id] = await bridge.async_relay_command(
                    {
                        "type": "voice_settings",
                        "action": action,
                        "media_player_entity": media_player_entity,
                        "args": dict(call_data.get("args") or {}),
                    }
                )
            if action == "status":
                ok = bool(results) or entry_id is None
            else:
                ok = all(result.get("ok", False) for result in results.values()) if results else False
            _LOGGER.info("Hermes voice action requested: %s entries=%d", action, len(results))
            return {"ok": ok, "action": action, "entry_id": entry_id, "results": results}

        matches: list[dict[str, Any]] = []
        for state in hass.states.async_all():
            if _entity_matches(state, query):
                matches.append(_state_payload(state, include_attributes=include_attributes))
                if len(matches) >= limit:
                    break
        _LOGGER.info("Hermes voice settings query=%r matched %d entities", query, len(matches))
        return {"ok": True, "query": query, "count": len(matches), "limit": limit, "matches": matches}

    def _register_service(name: str, handler: Any, schema: Any) -> None:
        try:
            hass.services.async_register(
                DOMAIN,
                name,
                handler,
                schema=schema,
                supports_response=SupportsResponse.OPTIONAL,
            )
        except TypeError:  # Older Home Assistant cores without service responses.
            hass.services.async_register(DOMAIN, name, handler, schema=schema)

    if not hass.services.has_service(DOMAIN, SERVICE_HERMES_COMMAND):
        _register_service(SERVICE_HERMES_COMMAND, _handle_hermes_command, COMMAND_SCHEMA)
    if not hass.services.has_service(DOMAIN, SERVICE_VOICE_SETTINGS):
        _register_service(SERVICE_VOICE_SETTINGS, _handle_voice_settings, VOICE_SCHEMA)

    _LOGGER.info("Hermes services registered: %s, %s", SERVICE_HERMES_COMMAND, SERVICE_VOICE_SETTINGS)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister Hermes services when the final config entry unloads."""
    for service in (SERVICE_HERMES_COMMAND, SERVICE_VOICE_SETTINGS):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
