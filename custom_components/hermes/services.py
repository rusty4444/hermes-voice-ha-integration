"""Hermes Home Assistant services."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_HERMES_COMMAND = "hermes_command"
SERVICE_VOICE_SETTINGS = "voice_settings"


async def async_register_services(hass: HomeAssistant) -> None:
    """Register HA-native services used by the Hermes integration."""

    async def _handle_hermes_command(call: ServiceCall) -> None:
        domain = call.data.get("domain", "")
        service = call.data.get("service", "")
        entity_id = call.data.get("entity_id")
        data = dict(call.data.get("data") or {})

        if not domain or not service:
            _LOGGER.warning("Ignoring Hermes command with missing domain/service: %s", call.data)
            return

        target = {"entity_id": entity_id} if entity_id else None
        await hass.services.async_call(
            domain,
            service,
            data,
            target=target,
            blocking=False,
        )
        _LOGGER.info("Hermes command dispatched: %s.%s entity=%s", domain, service, entity_id)

    async def _handle_voice_settings(call: ServiceCall) -> None:
        query = str(call.data.get("query", "")).lower().strip()
        action = str(call.data.get("action") or query).lower().strip()

        if action in {"enable", "disable", "status"}:
            for bridge in hass.data.get(DOMAIN, {}).values():
                if hasattr(bridge, "async_relay_command"):
                    await bridge.async_relay_command({"type": "voice_settings", "action": action})
            _LOGGER.info("Hermes voice action requested: %s", action)
            return

        matches: list[dict[str, Any]] = []
        for state in hass.states.async_all():
            friendly_name = str(state.attributes.get("friendly_name", ""))
            haystack = f"{state.entity_id} {friendly_name}".lower()
            if not query or query in haystack:
                matches.append({
                    "entity_id": state.entity_id,
                    "state": state.state,
                    "attributes": dict(state.attributes),
                })
        _LOGGER.info("Hermes voice settings query=%r matched %d entities", query, len(matches))

    if not hass.services.has_service(DOMAIN, SERVICE_HERMES_COMMAND):
        hass.services.async_register(DOMAIN, SERVICE_HERMES_COMMAND, _handle_hermes_command)
    if not hass.services.has_service(DOMAIN, SERVICE_VOICE_SETTINGS):
        hass.services.async_register(DOMAIN, SERVICE_VOICE_SETTINGS, _handle_voice_settings)

    _LOGGER.info("Hermes services registered: %s, %s", SERVICE_HERMES_COMMAND, SERVICE_VOICE_SETTINGS)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister Hermes services when the final config entry unloads."""
    for service in (SERVICE_HERMES_COMMAND, SERVICE_VOICE_SETTINGS):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
