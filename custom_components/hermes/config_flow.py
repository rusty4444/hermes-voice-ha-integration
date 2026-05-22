"""Config flow for the Hermes Home Assistant integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_URL, CONF_TOKEN
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER


class HermesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hermes."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate the Hermes URL
            url = user_input.get(CONF_URL, "").strip().rstrip("/")
            if not url:
                errors[CONF_URL] = "url_required"
            elif not url.startswith(("http://", "https://")):
                errors[CONF_URL] = "url_invalid"

            token = user_input.get(CONF_TOKEN, "").strip()
            if not token:
                errors[CONF_TOKEN] = "token_required"

            if not errors:
                return self.async_create_entry(
                    title=f"Hermes ({url})",
                    data={
                        CONF_URL: url,
                        CONF_TOKEN: token,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_URL, default="http://homeassistant.local:8123"): str,
                vol.Required(CONF_TOKEN): str,
            }),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return HermesOptionsFlow(config_entry)


class HermesOptionsFlow:
    """Options flow for Hermes."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_ENTITY_FILTER,
                    default=DEFAULT_ENTITY_FILTER,
                ): vol.Any(list, None),
            }),
        )
