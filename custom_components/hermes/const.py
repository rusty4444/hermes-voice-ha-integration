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

# Conversation agent: local (Home Assistant native) intent handling
CONF_LOCAL_INTENTS = "local_intents"
LOCAL_INTENTS_OFF = "off"
LOCAL_INTENTS_ANSWERS = "answers"
LOCAL_INTENTS_COMMANDS = "commands"
LOCAL_INTENTS_OPTIONS = [
    LOCAL_INTENTS_OFF,
    LOCAL_INTENTS_ANSWERS,
    LOCAL_INTENTS_COMMANDS,
]

# Opt-in voice-panel control through inline [HW:...] markers (#58). Every
# route stays disabled until a panel device and its entity are configured.
CONF_PANEL_DEVICE = "panel_device_id"
CONF_PANEL_HUD_ENTITY = "panel_hud_entity"
CONF_PANEL_LIGHT_ENTITY = "panel_light_entity"
CONF_PANEL_VOLUME_ENTITY = "panel_volume_entity"
CONF_PANEL_HUD_MAX_LENGTH = "panel_hud_max_length"
CONF_PANEL_BRIGHTNESS_MIN = "panel_brightness_min"
CONF_PANEL_BRIGHTNESS_MAX = "panel_brightness_max"
CONF_PANEL_VOLUME_MIN = "panel_volume_min"
CONF_PANEL_VOLUME_MAX = "panel_volume_max"
PANEL_HUD_DOMAINS = ("text", "input_text")
PANEL_LIGHT_DOMAINS = ("light",)
PANEL_VOLUME_DOMAINS = ("number", "input_number")
DEFAULT_PANEL_HUD_MAX_LENGTH = 60
PANEL_HUD_MAX_LENGTH_LIMIT = 255
DEFAULT_PANEL_BRIGHTNESS_MIN = 10
DEFAULT_PANEL_BRIGHTNESS_MAX = 100
DEFAULT_PANEL_VOLUME_MIN = 20
DEFAULT_PANEL_VOLUME_MAX = 80

# Defaults
DEFAULT_ENTITY_FILTER: list[str] = []
DEFAULT_VERIFY_SSL: bool = True
DEFAULT_LOCAL_INTENTS: str = LOCAL_INTENTS_OFF

# Engine / model defaults
DEFAULT_TTS_ENGINE = "edge"
DEFAULT_TTS_VOICE = "en-US-AriaNeural"
DEFAULT_STT_ENGINE = "faster-whisper"
DEFAULT_STT_MODEL = "tiny"
DEFAULT_WAKE_WORD_ENGINE = "porcupine"
DEFAULT_WAKE_WORD = "computer"
DEFAULT_MEDIA_PLAYER = ""
DEFAULT_QUERY_LIMIT = 50
MAX_QUERY_TEXT_LENGTH = 4096

# WebSocket message type constants
WS_TYPE_ASSIST_QUERY = "assist_query"
WS_TYPE_ASSIST_RESPONSE = "assist_response"
WS_TYPE_HERMES_EVENT = "hermes_event"
WS_TYPE_STATE_ACK = "state_ack"
WS_TYPE_STATE_CHANGED = "state_changed"


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
