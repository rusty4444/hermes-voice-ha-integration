"""Hermes Assist conversation agent for Home Assistant pipelines.

Registers Hermes as a selectable conversation agent in Home Assistant
Assist, so HA Voice devices can route transcribed text to Hermes and
receive spoken responses through the configured TTS pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from homeassistant.components.conversation import (
        ConversationEntity,
        ConversationInput,
        ConversationResult,
    )
    from homeassistant.helpers import intent
except ImportError:  # pragma: no cover - HA stubs / older cores
    ConversationEntity = object  # type: ignore[misc,assignment]
    ConversationInput = object  # type: ignore[misc,assignment]
    ConversationResult = object  # type: ignore[misc,assignment]
    intent = None  # type: ignore[assignment]

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

AGENT_ID = f"{DOMAIN}_assist"
AGENT_NAME = "Hermes"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hermes conversation agent from a config entry."""
    bridge = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if bridge is None:
        _LOGGER.warning("Hermes conversation: no bridge found for entry %s", entry.entry_id)
        return

    async_add_entities([HermesConversationAgent(bridge, entry.entry_id)])


class HermesConversationAgent(ConversationEntity):
    """Conversation agent that routes Assist pipeline text to Hermes."""

    _attr_has_entity_name = True
    _attr_name = AGENT_NAME
    _attr_icon = "mdi:robot"

    def __init__(self, bridge: Any, entry_id: str) -> None:
        """Initialise the Hermes conversation agent."""
        self._bridge = bridge
        self._attr_unique_id = f"{DOMAIN}_{entry_id}_conversation"

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages for this agent."""
        return ["en"]

    @staticmethod
    def _make_error_result(
        language: str,
        speech: str,
        conversation_id: str | None = None,
    ) -> ConversationResult:
        """Build a ConversationResult with an error speech response."""
        response = intent.IntentResponse(language=language)
        response.async_set_speech(speech)
        return ConversationResult(
            response=response,
            conversation_id=conversation_id,
        )

    async def async_process(self, user_input: ConversationInput) -> ConversationResult:
        """Process a conversation input from the Assist pipeline.

        Forwards the user text to Hermes over the WebSocket bridge
        and returns the agent's response.
        """
        text = (user_input.text or "").strip()
        language = getattr(user_input, "language", None) or "en"

        if not text:
            return self._make_error_result(
                language,
                "I didn't catch that. Could you repeat?",
                user_input.conversation_id,
            )

        conversation_id = user_input.conversation_id

        try:
            result = await self._bridge.async_send_conversation_query(
                text=text,
                conversation_id=conversation_id,
                language=language,
            )
        except (ConnectionError, TimeoutError) as exc:
            _LOGGER.warning("Hermes conversation query failed: %s", exc)
            return self._make_error_result(
                language,
                "Sorry, Hermes is not responding right now.",
                conversation_id,
            )
        except Exception as exc:
            _LOGGER.error("Unexpected error in Hermes conversation: %s", exc)
            return self._make_error_result(
                language,
                "Something went wrong. Please try again.",
                conversation_id,
            )

        response_text = result.get("text", "")
        speech_data = result.get("speech", {})
        if speech_data:
            response_speech = speech_data.get("plain", {}).get("speech", response_text)
        else:
            response_speech = response_text

        if not response_speech:
            response_speech = "I processed your request but got no response."

        response = intent.IntentResponse(language=language)
        response.async_set_speech(response_speech)

        return ConversationResult(
            response=response,
            conversation_id=result.get("conversation_id", conversation_id),
        )
