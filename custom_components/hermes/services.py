"""Hermes HA services — exposed to Hermes tool calling via HA WebSocket.

Register the ``hermes_command`` service so Hermes can invoke HA services
without going through the REST API.  This is a native WebSocket service
call path (P2 goal from the plan).  The P1 stub is replaced by this module.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.entity import Entity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_HERMES_COMMAND = "hermes_command"
SERVICE_VOICE_SETTINGS = "voice_settings"


async def async_register_services(hass: HomeAssistant) -> None:
    """Register HA services for Hermes → HA control.

    Called from ``HermesBridge.async_register_services()`` during setup.
    """

    async def _handle_hermes_command(call: ServiceCall) -> dict[str, Any]:
        from plugins.home_assistant.ha_assistant import call_service as sync_call_service

        domain = call.data.get("domain", "")
        service = call.data.get("service", "")
        entity_id = call.data.get("entity_id")
        data = call.data.get("data") or {}

        result = sync_call_service(domain, service, entity_id=entity_id, data=data)
        _LOGGER.info(
            "Hermes command: %s.%s → entity=%s → %s",
            domain, service, entity_id, "ok" if "error" not in result else result["error"],
        )
        return result

    async def _handle_voice_settings(call: ServiceCall) -> dict[str, Any]:
        from plugins.home_assistant.ha_assistant import search_entities

        query = call.data.get("query", "")
        search_result = search_entities(query=query)
        entities = search_result.get("entities", [])
        _LOGGER.info(
            "Hermes voice settings query='%s' → %d results", query, len(entities),
        )
        return {"entities": entities}

    # Register both services
    hass.services.async_register(DOMAIN, SERVICE_HERMES_COMMAND, _handle_hermes_command)
    hass.services.async_register(DOMAIN, SERVICE_VOICE_SETTINGS, _handle_voice_settings)

    _LOGGER.info("Hermes services registered: %s, %s", SERVICE_HERMES_COMMAND, SERVICE_VOICE_SETTINGS)
