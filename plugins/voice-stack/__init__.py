"""Voice stack plugin — local wake-word → STT → LLM → TTS → HA media_player.

This is the P1 scaffold (skeleton only). The P0 foundation delegates to the
home_assistant plugin for all HA connectivity.

Registered tools (no-op checks until P1 is implemented):
- voice_status  — show engine availability / current state
- voice_enable  — enable voice mode for the active session
- voice_disable — disable voice mode
"""

from __future__ import annotations

from plugins.voice_stack import audio as _audio_impl

logger = __import__("logging").getLogger(__name__)


# ---------------------------------------------------------------------------
# Availability gate — engines are stubs until P1 wiring is complete.
# These tools remain registered so `hermes tools` surfaces them, but
# check_fn prevents dispatch until the real engines are wired in.
# ---------------------------------------------------------------------------

_VOICE_AVAILABLE = False   # becomes True when P1 wake-word/STT/TTS wired


def _check_voice_available() -> bool:
    return _VOICE_AVAILABLE


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _handle_voice_status(args: dict, **kw) -> str:
    """Show Voice Stack engine states."""
    engines = {
        "wake_word": "stub",
        "stt": "stub",
        "tts": "stub",
        "media_player": _VOICE_AVAILABLE,
        "ready": _VOICE_AVAILABLE,
    }
    import json

    class _Enc(json.JSONEncoder):
        def default(self, o):
            return str(o)

    return json.dumps({"engines": engines, "ready": _VOICE_AVAILABLE})


def _handle_voice_enable(args: dict, **kw) -> str:
    """Enable voice mode for the active session (P1: no-op fallback)."""
    if not _VOICE_AVAILABLE:
        return (
            "Voice stack is not yet fully implemented in this release. "
            "Track progress: https://github.com/rusty4444/hermes-voice-ha-integration"
        )
    return "Voice mode is already enabled."


def _handle_voice_disable(args: dict, **kw) -> str:
    """Disable voice mode for the active session."""
    return "Voice mode is not active."


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

VOICE_STATUS_SCHEMA = {
    "name": "voice_status",
    "description": (
        "Report the current state of the Voice Stack engines "
        "(wake word, STT, TTS, media_player)."
    ),
    "parameters": {"type": "object", "properties": {}},
}

VOICE_ENABLE_SCHEMA = {
    "name": "voice_enable",
    "description": (
        "Enable voice mode for the active session — wake word, "
        "STT, LLM round-trip, and TTS playback are all activated."
    ),
    "parameters": {"type": "object", "properties": {}},
}

VOICE_DISABLE_SCHEMA = {
    "name": "voice_disable",
    "description": "Disable voice mode for the active session.",
    "parameters": {"type": "object", "properties": {}},
}


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

_TOOLS = (
    ("voice_status",  VOICE_STATUS_SCHEMA,  _handle_voice_status,  "🎙️"),
    ("voice_enable",  VOICE_ENABLE_SCHEMA,  _handle_voice_enable,  "🔊"),
    ("voice_disable", VOICE_DISABLE_SCHEMA, _handle_voice_disable, "🔇"),
)


def register(ctx) -> None:
    """Register Voice Stack tools."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="voice_stack",
            schema=schema,
            handler=handler,
            check_fn=_check_voice_available,
            emoji=emoji,
        )
