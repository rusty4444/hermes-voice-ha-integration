"""Config flow for the Hermes Home Assistant integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow
from homeassistant.const import CONF_URL, CONF_TOKEN
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER, CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL


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
                        CONF_ENTITY_FILTER: DEFAULT_ENTITY_FILTER,
                        CONF_VERIFY_SSL: DEFAULT_VERIFY_SSL,
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
        """Manage options: entity filter + SSL verification."""
        if user_input is not None:
            # Combine with existing data (don't lose URL/TOKEN)
            data = dict(self.config_entry.data)
            data[CONF_ENTITY_FILTER] = user_input.get(CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER)
            data[CONF_VERIFY_SSL] = user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
            return self.async_create_entry(title="", data=data)

        current = self.config_entry.data
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(
                    CONF_ENTITY_FILTER,
                    description={"suggested_value": current.get(CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER)},
                    default=current.get(CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER),
                ): vol.Any(list, None),
                vol.Optional(
                    CONF_VERIFY_SSL,
                    default=current.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                ): bool,
            }),
        )

    async def async_step_allowlist(self, user_input: dict | None = None) -> FlowResult:
        """Configure the HA entity allow-list (Hermes security layer)."""
        import json
        from pathlib import Path

        _FILE = Path.home() / ".hermes" / "ha_allow_list.json"

        if user_input is not None:
            # Read existing, merge, write back
            existing = {}
            if _FILE.exists():
                try:
                    existing = json.loads(_FILE.read_text())
                except Exception:
                    existing = {}
            enabled = user_input.get("allowlist_enabled", False)
            rules_raw = user_input.get("allowlist_rules", "")

            try:
                rules = json.loads(rules_raw) if rules_raw.strip() else []
            except Exception:
                return self.async_show_form(
                    step_id="allowlist",
                    data_schema=vol.Schema({
                        vol.Required("allowlist_enabled", default=False): bool,
                        vol.Optional("allowlist_rules", default=""): str,
                    }),
                    errors={"allowlist_rules": "invalid_json"},
                )

            new_config = {"enabled": enabled, "rules": rules}
            _FILE.parent.mkdir(parents=True, exist_ok=True)
            _FILE.write_text(json.dumps(new_config, indent=2))
            return self.async_create_entry(title="", data=self.config_entry.data)

        # Show current allowlist state
        current_rules = ""
        if _FILE.exists():
            try:
                data = json.loads(_FILE.read_text())
                current_rules = json.dumps(data.get("rules", []), indent=2)
            except Exception:
                pass

        return self.async_show_form(
            step_id="allowlist",
            data_schema=vol.Schema({
                vol.Required("allowlist_enabled", default=False): bool,
                vol.Optional("allowlist_rules", default=current_rules): str,
            }),
        )
