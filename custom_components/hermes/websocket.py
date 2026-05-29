"""WebSocket utilities for Hermes Voice Assistant integration."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def send_conversation_to_hermes(
    hass: HomeAssistant,
    entry_id: str,
    text: str,
    context: dict[str, Any] | None,
    language: str,
) -> str:
    """Send conversation text to Hermes Agent via WebSocket and return response."""
    from . import HermesBridge
    
    # Get the bridge instance for this entry
    bridge: HermesBridge | None = hass.data.get(DOMAIN, {}).get(entry_id)
    if bridge is None:
        _LOGGER.error("Hermes bridge not found for entry %s", entry_id)
        return "Sorry, Hermes Agent is not connected."
    
    if not bridge.connected:
        _LOGGER.error("Hermes WebSocket not connected for entry %s", entry_id)
        return "Sorry, Hermes Agent is not connected."
    
    # Prepare the conversation payload
    payload = {
        "type": "conversation",
        "action": "process",
        "text": text,
        "language": language,
        "context": context or {},
    }
    
    # Send via WebSocket and wait for response
    try:
        # We need to wait for the response - this requires modifying the bridge
        # to support request/response pattern
        response = await bridge.send_conversation_request(payload)
        return response.get("text", "I didn't understand that.")
    except Exception as err:
        _LOGGER.error("Error sending conversation to Hermes: %s", err)
        return "Sorry, there was an error processing your request."
