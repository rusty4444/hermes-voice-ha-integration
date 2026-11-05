"""Config flow for the Hermes Home Assistant integration."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigEntry, OptionsFlow
from homeassistant.const import CONF_URL, CONF_TOKEN
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    DOMAIN,
    CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER,
    CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL,
    CONF_LOCAL_INTENTS, DEFAULT_LOCAL_INTENTS, LOCAL_INTENTS_OPTIONS,
    CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE, CONF_TTS_VOICE, DEFAULT_TTS_VOICE,
    CONF_STT_ENGINE, DEFAULT_STT_ENGINE, CONF_STT_MODEL, DEFAULT_STT_MODEL,
    CONF_WAKE_WORD_ENGINE, DEFAULT_WAKE_WORD_ENGINE,
    CONF_WAKE_WORD, DEFAULT_WAKE_WORD,
    CONF_MEDIA_PLAYER, DEFAULT_MEDIA_PLAYER,
    TTS_ENGINE_OPTIONS, STT_ENGINE_OPTIONS, WAKE_WORD_ENGINE_OPTIONS,
    CONF_PANEL_DEVICE, CONF_PANEL_HUD_ENTITY, CONF_PANEL_LIGHT_ENTITY,
    CONF_PANEL_VOLUME_ENTITY, CONF_PANEL_HUD_MAX_LENGTH,
    CONF_PANEL_BRIGHTNESS_MIN, CONF_PANEL_BRIGHTNESS_MAX,
    CONF_PANEL_VOLUME_MIN, CONF_PANEL_VOLUME_MAX,
    DEFAULT_PANEL_HUD_MAX_LENGTH, PANEL_HUD_MAX_LENGTH_LIMIT,
    DEFAULT_PANEL_BRIGHTNESS_MIN, DEFAULT_PANEL_BRIGHTNESS_MAX,
    DEFAULT_PANEL_VOLUME_MIN, DEFAULT_PANEL_VOLUME_MAX,
    PANEL_HUD_DOMAINS, PANEL_LIGHT_DOMAINS, PANEL_VOLUME_DOMAINS,
    normalize_list, normalize_wake_word,
)
from .panel import bounded_int, entity_or_empty

_PANEL_ENTITY_FIELDS = (
    (CONF_PANEL_HUD_ENTITY, PANEL_HUD_DOMAINS),
    (CONF_PANEL_LIGHT_ENTITY, PANEL_LIGHT_DOMAINS),
    (CONF_PANEL_VOLUME_ENTITY, PANEL_VOLUME_DOMAINS),
)
_PANEL_NUMBER_FIELDS = (
    (CONF_PANEL_HUD_MAX_LENGTH, DEFAULT_PANEL_HUD_MAX_LENGTH, 1, PANEL_HUD_MAX_LENGTH_LIMIT),
    (CONF_PANEL_BRIGHTNESS_MIN, DEFAULT_PANEL_BRIGHTNESS_MIN, 0, 100),
    (CONF_PANEL_BRIGHTNESS_MAX, DEFAULT_PANEL_BRIGHTNESS_MAX, 0, 100),
    (CONF_PANEL_VOLUME_MIN, DEFAULT_PANEL_VOLUME_MIN, 0, 100),
    (CONF_PANEL_VOLUME_MAX, DEFAULT_PANEL_VOLUME_MAX, 0, 100),
)


def _parse_panel_options(user_input: dict) -> dict:
    """Normalise the panel page. Empty device or entity means disabled."""
    parsed: dict = {
        CONF_PANEL_DEVICE: str(user_input.get(CONF_PANEL_DEVICE) or "").strip(),
    }
    for key, domains in _PANEL_ENTITY_FIELDS:
        parsed[key] = entity_or_empty(user_input.get(key), domains)
    for key, default, low, high in _PANEL_NUMBER_FIELDS:
        parsed[key] = bounded_int(user_input.get(key), default, low, high)
    return parsed


def _panel_range_errors(parsed: dict) -> dict[str, str]:
    errors: dict[str, str] = {}
    if parsed[CONF_PANEL_BRIGHTNESS_MIN] > parsed[CONF_PANEL_BRIGHTNESS_MAX]:
        errors[CONF_PANEL_BRIGHTNESS_MIN] = "panel_min_above_max"
    if parsed[CONF_PANEL_VOLUME_MIN] > parsed[CONF_PANEL_VOLUME_MAX]:
        errors[CONF_PANEL_VOLUME_MIN] = "panel_min_above_max"
    return errors


def _parse_list(value) -> list[str]:
    """Accept list, tuple, or newline/comma-separated string."""
    return normalize_list(value)


def _parse_entity_filter(value) -> list[str]:
    """Accept list input or comma/newline-separated text."""
    return _parse_list(value)


def _parse_wake_word(value) -> list[str]:
    """Wake words can be a single string or comma-separated list."""
    return normalize_wake_word(value)


def _parse_local_intents(value) -> str:
    """Accept only a known local-intents mode; anything else means "off"."""
    mode = str(value or "").strip().lower()
    return mode if mode in LOCAL_INTENTS_OPTIONS else DEFAULT_LOCAL_INTENTS


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
                    options=_default_options(),
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_URL, default="http://hermes.local:7860"):
                    selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.URL)
                    ),
                vol.Required(CONF_TOKEN): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }),
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HermesOptionsFlow(config_entry)


def _default_options() -> dict:
    """Default option set for a newly created config entry."""
    return {
        CONF_ENTITY_FILTER: DEFAULT_ENTITY_FILTER,
        CONF_VERIFY_SSL: DEFAULT_VERIFY_SSL,
        CONF_TTS_ENGINE: DEFAULT_TTS_ENGINE,
        CONF_TTS_VOICE: DEFAULT_TTS_VOICE,
        CONF_STT_ENGINE: DEFAULT_STT_ENGINE,
        CONF_STT_MODEL: DEFAULT_STT_MODEL,
        CONF_WAKE_WORD_ENGINE: DEFAULT_WAKE_WORD_ENGINE,
        CONF_WAKE_WORD: normalize_wake_word(DEFAULT_WAKE_WORD),
        CONF_MEDIA_PLAYER: DEFAULT_MEDIA_PLAYER,
        CONF_LOCAL_INTENTS: DEFAULT_LOCAL_INTENTS,
    }


class HermesOptionsFlow(OptionsFlow):
    """Multi-step options flow for Hermes."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._pending: dict | None = None

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        """Step 1 — entity allow-list and SSL verification."""
        current = dict(self._config_entry.options or {})

        if user_input is not None:
            self._pending = {
                CONF_ENTITY_FILTER: _parse_entity_filter(
                    user_input.get(CONF_ENTITY_FILTER)
                ),
                CONF_VERIFY_SSL: bool(
                    user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)
                ),
                CONF_LOCAL_INTENTS: _parse_local_intents(
                    user_input.get(CONF_LOCAL_INTENTS, DEFAULT_LOCAL_INTENTS)
                ),
            }
            # Always drop through to voice step after init
            return await self.async_step_voice()

        current_filter = ", ".join(
            current.get(CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER)
        )
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
                vol.Optional(
                    CONF_LOCAL_INTENTS,
                    default=current.get(CONF_LOCAL_INTENTS, DEFAULT_LOCAL_INTENTS),
                ): vol.In(LOCAL_INTENTS_OPTIONS),
            }),
        )

    async def async_step_voice(self, user_input: dict | None = None) -> FlowResult:
        """Step 2 — voice pipeline configuration."""
        current = dict(self._config_entry.options or {})
        if self._pending:
            current.update(self._pending)

        if user_input is not None:
            tts_engine = str(
                user_input.get(CONF_TTS_ENGINE, current.get(CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE))
            ).strip()
            stt_engine = str(
                user_input.get(CONF_STT_ENGINE, current.get(CONF_STT_ENGINE, DEFAULT_STT_ENGINE))
            ).strip()
            ww_engine = str(
                user_input.get(CONF_WAKE_WORD_ENGINE, current.get(CONF_WAKE_WORD_ENGINE, DEFAULT_WAKE_WORD_ENGINE))
            ).strip()

            merged: dict = {
                # carry forward everything
                CONF_ENTITY_FILTER: current.get(CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER),
                CONF_VERIFY_SSL: current.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                # voice values
                CONF_TTS_ENGINE: tts_engine,
                CONF_TTS_VOICE: str(
                    user_input.get(CONF_TTS_VOICE, current.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE))
                ).strip(),
                CONF_STT_ENGINE: stt_engine,
                CONF_STT_MODEL: str(
                    user_input.get(CONF_STT_MODEL, current.get(CONF_STT_MODEL, DEFAULT_STT_MODEL))
                ).strip(),
                CONF_WAKE_WORD_ENGINE: ww_engine,
                CONF_WAKE_WORD: _parse_wake_word(
                    user_input.get(CONF_WAKE_WORD, current.get(CONF_WAKE_WORD, DEFAULT_WAKE_WORD))
                ),
                CONF_MEDIA_PLAYER: str(
                    user_input.get(CONF_MEDIA_PLAYER, current.get(CONF_MEDIA_PLAYER, DEFAULT_MEDIA_PLAYER))
                ).strip(),
                CONF_LOCAL_INTENTS: _parse_local_intents(
                    current.get(CONF_LOCAL_INTENTS, DEFAULT_LOCAL_INTENTS)
                ),
            }
            self._pending = merged
            return await self.async_step_panel()

        current_tts_engine = current.get(CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE)
        current_stt_engine = current.get(CONF_STT_ENGINE, DEFAULT_STT_ENGINE)
        current_ww_engine = current.get(CONF_WAKE_WORD_ENGINE, DEFAULT_WAKE_WORD_ENGINE)
        current_ww = ", ".join(normalize_wake_word(current.get(CONF_WAKE_WORD, DEFAULT_WAKE_WORD)))
        current_mp = current.get(CONF_MEDIA_PLAYER, DEFAULT_MEDIA_PLAYER)

        return self.async_show_form(
            step_id="voice",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_TTS_ENGINE,
                    default=current_tts_engine,
                    description={"suggested_value": current_tts_engine},
                ): vol.In(TTS_ENGINE_OPTIONS),
                vol.Optional(
                    CONF_TTS_VOICE,
                    default=current.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE),
                    description={"suggested_value": current.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE)},
                ): str,
                vol.Required(
                    CONF_STT_ENGINE,
                    default=current_stt_engine,
                    description={"suggested_value": current_stt_engine},
                ): vol.In(STT_ENGINE_OPTIONS),
                vol.Optional(
                    CONF_STT_MODEL,
                    default=current.get(CONF_STT_MODEL, DEFAULT_STT_MODEL),
                    description={"suggested_value": current.get(CONF_STT_MODEL, DEFAULT_STT_MODEL)},
                ): str,
                vol.Required(
                    CONF_WAKE_WORD_ENGINE,
                    default=current_ww_engine,
                    description={"suggested_value": current_ww_engine},
                ): vol.In(WAKE_WORD_ENGINE_OPTIONS),
                vol.Optional(
                    CONF_WAKE_WORD,
                    default=current_ww,
                    description={"suggested_value": current_ww},
                ): str,
                vol.Optional(
                    CONF_MEDIA_PLAYER,
                    default=current_mp,
                    description={"suggested_value": current_mp},
                ): str,
            }),
        )

    async def async_step_panel(self, user_input: dict | None = None) -> FlowResult:
        """Step 3 — optional voice-panel control through [HW:...] markers.

        Leaving the device empty keeps the feature off. Device and entity
        fields use ``suggested_value`` rather than ``default`` so clearing a
        field in the UI really clears it.
        """
        current = dict(self._config_entry.options or {})
        if self._pending:
            current.update(self._pending)
        errors: dict[str, str] = {}

        if user_input is not None:
            parsed = _parse_panel_options(user_input)
            errors = _panel_range_errors(parsed)
            if not errors:
                current.update(parsed)
                return self.async_create_entry(title="", data=current)
            current.update(parsed)

        schema: dict = {
            vol.Optional(
                CONF_PANEL_DEVICE,
                description={"suggested_value": current.get(CONF_PANEL_DEVICE) or None},
            ): selector.DeviceSelector(selector.DeviceSelectorConfig()),
        }
        for key, domains in _PANEL_ENTITY_FIELDS:
            schema[vol.Optional(
                key,
                description={"suggested_value": current.get(key) or None},
            )] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=list(domains))
            )
        for key, default, low, high in _PANEL_NUMBER_FIELDS:
            schema[vol.Optional(
                key,
                default=bounded_int(current.get(key), default, low, high),
            )] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=low,
                    max=high,
                    step=1,
                    mode=selector.NumberSelectorMode.BOX,
                )
            )

        return self.async_show_form(
            step_id="panel",
            data_schema=vol.Schema(schema),
            errors=errors,
        )

