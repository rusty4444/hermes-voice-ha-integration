"""Conversation agent for Hermes Voice Assistant integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.conversation import (
    AbstractConversationAgent,
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from ..const import DOMAIN
from ..websocket import send_conversation_to_hermes

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Set up the conversation agent from a config entry."""
    agent = HermesConversationAgent(hass, entry)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = agent

    # Register the conversation agent with Home Assistant
    from homeassistant.components.conversation import async_set_agent
    async_set_agent(hass, entry, agent)

    _LOGGER.debug("Hermes conversation agent set up for entry %s", entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unload a conversation agent."""
    agent: HermesConversationAgent | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id)
    if agent is not None:
        from homeassistant.components.conversation import async_unset_agent
        async_unset_agent(hass, entry)
        _LOGGER.debug("Hermes conversation agent unset for entry %s", entry.entry_id)


class HermesConversationAgent(AbstractConversationAgent):
    """Hermes conversation agent."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self._attr_name = "Hermes Agent"
        self._attr_supported_language = "en"

    @property
    def supported_languages(self) -> list[str]:
        """Return a list of supported languages."""
        return ["en"]

    async def async_process(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Process a sentence."""
        _LOGGER.debug("Processing conversation input: %s", user_input.text)

        # Send the user's text to Hermes Agent via WebSocket
        try:
            response_text = await send_conversation_to_hermes(
                self.hass,
                self.entry.entry_id,
                user_input.text,
                user_input.context,
                user_input.language,
                user_input.conversation_id,
            )
        except Exception as err:
            _LOGGER.error("Error communicating with Hermes Agent: %s", err)
            return ConversationResult(
                response="Sorry, I'm having trouble connecting to the Hermes Agent.",
                conversation_id=user_input.conversation_id,
            )

        # Return the response from Hermes
        return ConversationResult(
            response=response_text,
            conversation_id=user_input.conversation_id,
        )