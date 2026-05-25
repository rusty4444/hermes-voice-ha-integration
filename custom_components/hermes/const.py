"""Constants for the Hermes Home Assistant integration."""

from __future__ import annotations

DOMAIN = "hermes"

# Config flow keys
CONF_URL = "url"
CONF_TOKEN = "token"
CONF_ENTITY_FILTER = "entity_filter"
CONF_VERIFY_SSL = "verify_ssl"

# Voice / media-pipeline options (OptionsFlow)
CONF_TTS_ENGINE = "tts_engine"
CONF_TTS_VOICE = "tts_voice"
CONF_STT_ENGINE = "stt_engine"
CONF_STT_MODEL = "stt_model"
CONF_WAKE_WORD_ENGINE = "wake_word_engine"
CONF_WAKE_WORD = "wake_word"
CONF_MEDIA_PLAYER = "media_player_entity"

# Defaults
DEFAULT_ENTITY_FILTER: list[str] = []
DEFAULT_VERIFY_SSL: bool = True

# Engine / model defaults
DEFAULT_TTS_ENGINE = "edge"
DEFAULT_TTS_VOICE = "en-US-AriaNeural"
DEFAULT_STT_ENGINE = "faster-whisper"
DEFAULT_STT_MODEL = "tiny"
DEFAULT_WAKE_WORD_ENGINE = "porcupine"
DEFAULT_WAKE_WORD = "computer"
DEFAULT_MEDIA_PLAYER = ""
DEFAULT_QUERY_LIMIT = 50


def normalize_list(value: object) -> list[str]:
    """Normalize list-like option values from HA forms and stored options."""
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value).replace("\n", ",").split(",") if part.strip()]


def normalize_wake_word(value: object = DEFAULT_WAKE_WORD) -> list[str]:
    """Normalize wake-word config to a list of keyword strings."""
    parsed = normalize_list(value)
    return parsed or [DEFAULT_WAKE_WORD]

# Valid enum values (used for select dropdowns)
TTS_ENGINE_OPTIONS = ["edge", "piper", "elevenlabs", "openai"]
STT_ENGINE_OPTIONS = ["faster-whisper", "whisper-cpp"]
WAKE_WORD_ENGINE_OPTIONS = ["porcupine", "openwakeword", "command"]
