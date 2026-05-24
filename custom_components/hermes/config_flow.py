"""Config flow for the Hermes Home Assistant integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigEntry, OptionsFlow
from homeassistant.const import CONF_URL, CONF_TOKEN
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER, CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL


def _parse_entity_filter(value) -> list[str]:
    """Accept list input or comma/newline-separated text from the options form."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in str(value).replace("\n", ",").split(",") if part.strip()]


class HermesConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hermes."""

    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            url = user_input.get(CONF_URL, "").strip().rstrip("/")
            if not url:
                errors[CONF_URL] = "url_required"
            elif not url.startswith(("http://", "https://")):
                errors[CONF_URL] = "url_invalid"

            token = user_input.get(CONF_TOKEN, "").strip()
            if not token:
                errors[CONF_TOKEN] = "token_required"

            if not errors:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Hermes ({url})",
                    data={CONF_URL: url, CONF_TOKEN: token},
                    options={
                        CONF_ENTITY_FILTER: DEFAULT_ENTITY_FILTER,
                        CONF_VERIFY_SSL: DEFAULT_VERIFY_SSL,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_URL, default="http://homeassistant.local:7860"): str,
                vol.Required(CONF_TOKEN): str,
            }),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HermesOptionsFlow(config_entry)


class HermesOptionsFlow(OptionsFlow):
    """Options flow for Hermes."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Manage entity filter + SSL verification."""
        current = dict(self.config_entry.options or {})
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={
                    CONF_ENTITY_FILTER: _parse_entity_filter(user_input.get(CONF_ENTITY_FILTER)),
                    CONF_VERIFY_SSL: bool(user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)),
                },
            )

        current_filter = ", ".join(current.get(CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_ENTITY_FILTER,
                    default=current_filter,
                    description={"suggested_value": current_filter},
                ): str,
                vol.Optional(
                    CONF_VERIFY_SSL,
                    default=current.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                ): bool,
            }),
        )
