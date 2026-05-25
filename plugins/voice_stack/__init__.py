"""Voice stack plugin — local wake-word → STT → LLM → TTS → HA media_player.

P1: Real engine implementations replacing P0 stubs.

Registered tools:
- voice_status   — show engine availability and pipeline state
- voice_enable   — enable continuous voice mode with HA media_player
- voice_disable  — disable voice mode
- voice_speak    — TTS-only: speak text through the configured TTS engine
- voice_listen   — one-shot: listen for a command, transcribe, and return
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy engine import (engines have heavy deps — only load when needed)
# ---------------------------------------------------------------------------

_pipeline: Optional[Any] = None  # VoicePipeline instance
_pipeline_lock = threading.Lock()
_voice_ready = threading.Event()

_wake_word_engine: Optional[Any] = None
_stt_engine: Optional[Any] = None
_tts_engine: Optional[Any] = None


def _get_config() -> Dict[str, Any]:
    """Load voice stack config from plugin.yaml or env."""
    return {
        "wake_word": {
            "engine": os.getenv("HERMES_WAKE_WORD_ENGINE", "porcupine"),
            "keyword": os.getenv("HERMES_WAKE_WORD", "computer"),
        },
        "stt": {
            "engine": os.getenv("HERMES_STT_ENGINE", "faster-whisper"),
            "model_size": os.getenv("HERMES_STT_MODEL", "tiny"),
        },
        "tts": {
            "engine": os.getenv("HERMES_TTS_ENGINE", "edge"),
            "voice": os.getenv("HERMES_TTS_VOICE", "en-US-AriaNeural"),
        },
        "media_player_entity": os.getenv("HERMES_MEDIA_PLAYER", ""),
        "max_record_duration": float(os.getenv("HERMES_RECORD_DURATION", "10")),
        "silence_timeout": float(os.getenv("HERMES_SILENCE_TIMEOUT", "2.0")),
        "confidence_threshold": float(os.getenv("HERMES_STT_CONFIDENCE", "0.70")),
    }


def _init_engines() -> bool:
    """Initialise TTS + STT engines from config. Returns True if both ready."""
    global _tts_engine, _stt_engine, _wake_word_engine
    config = _get_config()

    # TTS
    from plugins.voice_stack.engines.tts import create_tts_engine
    try:
        _tts_engine = create_tts_engine(
            engine_type=config["tts"]["engine"],
            voice=config["tts"]["voice"],
        )
    except Exception as exc:
        logger.warning("TTS engine init failed: %s", exc)
        _tts_engine = None

    # STT
    from plugins.voice_stack.engines.stt import create_stt_engine
    try:
        _stt_engine = create_stt_engine(
            engine_type=config["stt"]["engine"],
            model_size=config["stt"].get("model_size", "tiny"),
        )
    except Exception as exc:
        logger.warning("STT engine init failed: %s", exc)
        _stt_engine = None

    # Wake Word (optional — voice mode works without it via voice_listen)
    from plugins.voice_stack.engines.wake_word import create_wake_word_engine
    try:
        _wake_word_engine = create_wake_word_engine(
            engine_type=config["wake_word"]["engine"],
            keywords=[config["wake_word"]["keyword"]],
        )
    except Exception as exc:
        logger.warning("Wake word engine init failed: %s", exc)
        _wake_word_engine = None

    tts_ok = _tts_engine is not None and _tts_engine.available()
    stt_ok = _stt_engine is not None and _stt_engine.available()
    logger.info("Voice engines: TTS=%s STT=%s WakeWord=%s", tts_ok, stt_ok, _wake_word_engine is not None)

    if tts_ok and stt_ok:
        _voice_ready.set()
    return tts_ok and stt_ok


def _check_voice_available() -> bool:
    """Check if voice engines are available (check_fn for tools)."""
    return _voice_ready.is_set()


def _ensure_voice_ready() -> bool:
    """Lazy-init engines on first tool call."""
    if not _voice_ready.is_set():
        return _init_engines()
    return True


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def _handle_voice_status(args: dict, **kw) -> str:
    """Show Voice Stack engine states and pipeline status."""
    _ensure_voice_ready()

    def _engine_status(engine, name: str) -> Dict[str, Any]:
        if engine is None:
            return {"status": "not_configured"}
        try:
            avail = engine.available()
        except Exception:
            avail = False
        return {"status": "ready" if avail else "unavailable"}

    engines = {
        "wake_word": _engine_status(_wake_word_engine, "wake_word"),
        "stt": _engine_status(_stt_engine, "stt"),
        "tts": _engine_status(_tts_engine, "tts"),
    }

    # Get voice list for TTS
    tts_voices: list = []
    if _tts_engine and _tts_engine.available():
        try:
            tts_voices = _tts_engine.list_voices()
        except Exception:
            pass

    pipeline_state: Dict[str, Any] = {}
    if _pipeline:
        pipeline_state = _pipeline.state.to_dict()

    result: Dict[str, Any] = {
        "engines": engines,
        "tts_voices": tts_voices[:10],  # Limit to 10
        "pipeline": pipeline_state,
        "ready": _voice_ready.is_set(),
    }
    return json.dumps(result, default=str)


def _handle_voice_enable(args: dict, **kw) -> str:
    """Enable continuous voice mode with wake word and HA media_player."""
    global _pipeline

    _ensure_voice_ready()
    if not _voice_ready.is_set():
        return json.dumps({
            "ok": False,
            "error": "Voice engines not available. Check voice_status for details.",
        })

    with _pipeline_lock:
        if _pipeline and _pipeline.state.enabled:
            return json.dumps({"ok": True, "message": "Voice mode already enabled."})

        config = _get_config()
        media_player = args.get("media_player_entity") or config["media_player_entity"] or None

        from plugins.voice_stack.pipeline import VoicePipeline

        # Define the callback that sends user text to Hermes
        # In production this is wired by the Hermes tool dispatch system.
        # For now, the callback uses the HA tool bridge directly.
        def _voice_callback(text: str) -> str:
            """Called when STT produces text. This is where Hermes processes it."""
            logger.info("Voice callback received: %s", text)
            try:
                from plugins.home_assistant.ha_assistant import (
                    search_entities,
                    call_service,
                )
            except ImportError:
                return "The Home Assistant bridge is not available."
            # For P1, delegate the actual LLM processing to the Hermes agent
            # via a registered hook. The response here is a placeholder —
            # the Hermes agent loop handles full NLU.
            return (
                f"I heard: {text}. "
                "Voice processing is active — Hermes is listening."
            )

        _pipeline = VoicePipeline(
            callback=_voice_callback,
            wake_word_engine=_wake_word_engine,
            stt_engine=_stt_engine,
            tts_engine=_tts_engine,
            media_player_entity=media_player,
            max_record_duration=config["max_record_duration"],
            silence_timeout=config["silence_timeout"],
            confidence_threshold=config["confidence_threshold"],
        )

        if not _pipeline.available:
            _pipeline = None
            return json.dumps({"ok": False, "error": "Engines not all available."})

        started = _pipeline.start()
        if not started:
            _pipeline = None
            return json.dumps({"ok": False, "error": "Voice pipeline failed to start."})
    return json.dumps({"ok": True, "message": "Voice mode enabled. Wake word active."})



def _handle_voice_disable(args: dict, **kw) -> str:
    """Disable voice mode."""
    global _pipeline
    with _pipeline_lock:
        if _pipeline:
            _pipeline.stop()
            _pipeline = None
            return json.dumps({"ok": True, "message": "Voice mode disabled."})
    return json.dumps({"ok": True, "message": "Voice mode was not active."})


def _handle_voice_speak(args: dict, **kw) -> str:
    """Speak text through TTS engine + playback."""
    _ensure_voice_ready()
    if not _tts_engine or not _tts_engine.available():
        return json.dumps({"ok": False, "error": "TTS engine not available."})

    text = args.get("text", "")
    if not text:
        return json.dumps({"ok": False, "error": "No text provided."})

    try:
        from plugins.voice_stack.pipeline import play_audio_local, play_audio_ha

        audio_path = _tts_engine.synthesize(text)
        media_player = args.get("media_player_entity") or _get_config().get("media_player_entity", "")
        if media_player:
            ok = play_audio_ha(audio_path, media_player)
        else:
            ok = play_audio_local(audio_path)

        return json.dumps({"ok": ok, "audio_path": audio_path})
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)})


def _handle_voice_listen(args: dict, **kw) -> str:
    """One-shot: record audio, transcribe, and return text.

    This is a simpler alternative to continuous voice mode.
    Useful for testing STT or for push-to-talk workflows.
    """
    _ensure_voice_ready()
    if not _stt_engine or not _stt_engine.available():
        return json.dumps({"ok": False, "error": "STT engine not available.", "error_category": "engine_unavailable"})

    config = _get_config()
    try:
        duration = float(args.get("duration", config["max_record_duration"]))
    except (TypeError, ValueError):
        return json.dumps({"ok": False, "error": "duration must be numeric", "error_category": "invalid_duration"})
    if duration <= 0 or duration > 60:
        return json.dumps({"ok": False, "error": "duration must be between 0 and 60 seconds", "error_category": "invalid_duration"})
    language = args.get("language", None)

    import tempfile
    from plugins.voice_stack.pipeline import record_audio

    cache_dir = Path.home() / ".hermes" / "voice_cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return json.dumps({"ok": False, "error": str(exc), "error_category": "cache_unavailable"})

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(cache_dir)) as tmp:
        audio_path = tmp.name

    try:
        recorded = record_audio(audio_path, duration=duration)
        if not recorded:
            return json.dumps({"ok": False, "error": "No speech detected.", "error_category": "no_speech"})
        try:
            result = _stt_engine.transcribe_with_confidence(audio_path, language=language)
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc), "error_category": "transcription_failed"})
        return json.dumps({
            "ok": True,
            "text": result.get("text", ""),
            "confidence": round(result.get("confidence", 1.0), 3),
            "language": result.get("language", "unknown"),
        })
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc), "error_category": "recording_failed"})
    finally:
        try:
            os.unlink(audio_path)
        except OSError:
            pass


def _handle_voice_prompt(args: dict, **kw) -> str:
    """Return the voice-optimised system prompt with current HA context."""
    from plugins.voice_stack.pipeline import build_voice_system_prompt

    areas = None
    entities = None
    try:
        from plugins.home_assistant.ha_assistant import search_entities
    except ImportError:
        pass
    else:
        try:
            entities = search_entities().get("entities", [])[:30]
        except Exception:
            pass

    prompt = build_voice_system_prompt(areas=areas, entities=entities)
    return json.dumps({"ok": True, "prompt": prompt})


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

VOICE_STATUS_SCHEMA = {
    "name": "voice_status",
    "description": (
        "Report the current state of the Voice Stack engines "
        "(wake word, STT, TTS, media_player) and pipeline."
    ),
    "parameters": {"type": "object", "properties": {}},
}

VOICE_ENABLE_SCHEMA = {
    "name": "voice_enable",
    "description": (
        "Enable continuous voice mode — wake word detection, STT, "
        "Hermes LLM round-trip, and TTS playback through HA media_player. "
        "The pipeline runs in the background until disabled."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "media_player_entity": {
                "type": "string",
                "description": "HA media_player entity for TTS output (e.g. media_player.kitchen_speaker). "
                               "If omitted, uses HERMES_MEDIA_PLAYER env var or local speakers.",
            },
        },
    },
}

VOICE_DISABLE_SCHEMA = {
    "name": "voice_disable",
    "description": "Disable continuous voice mode.",
    "parameters": {"type": "object", "properties": {}},
}

VOICE_SPEAK_SCHEMA = {
    "name": "voice_speak",
    "description": (
        "Speak text through the configured TTS engine and output to "
        "the configured media player or local speakers."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to speak.",
            },
            "media_player_entity": {
                "type": "string",
                "description": "Optional HA media_player to output to.",
            },
        },
        "required": ["text"],
    },
}

VOICE_LISTEN_SCHEMA = {
    "name": "voice_listen",
    "description": (
        "One-shot listen: record audio from the microphone, transcribe it, "
        "and return the text. Useful for testing or push-to-talk workflows."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "duration": {
                "type": "number",
                "description": "Maximum recording duration in seconds (default: 10).",
            },
            "language": {
                "type": "string",
                "description": "Language code (e.g. 'en', 'fr'). Pass to STT engine.",
            },
        },
    },
}

VOICE_PROMPT_SCHEMA = {
    "name": "voice_prompt",
    "description": (
        "Return the voice-optimised system prompt with current Home Assistant "
        "context injected. Use this when Hermes is about to enter a voice "
        "interaction to ensure concise, natural spoken responses."
    ),
    "parameters": {"type": "object", "properties": {}},
}


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

_TOOLS = (
    ("voice_status",  VOICE_STATUS_SCHEMA,  _handle_voice_status,  "🎙️"),
    ("voice_enable",  VOICE_ENABLE_SCHEMA,  _handle_voice_enable,  "🔊"),
    ("voice_disable", VOICE_DISABLE_SCHEMA, _handle_voice_disable, "🔇"),
    ("voice_speak",   VOICE_SPEAK_SCHEMA,   _handle_voice_speak,   "🗣️"),
    ("voice_listen",  VOICE_LISTEN_SCHEMA,  _handle_voice_listen,  "👂"),
    ("voice_prompt",  VOICE_PROMPT_SCHEMA,  _handle_voice_prompt,  "📋"),
)


def register(ctx) -> None:
    """Register Voice Stack tools with Hermes.

    Registration is unconditional — tools that require unavailable engines
    return descriptive errors rather than being hidden, so users can see
    what's missing via voice_status.
    """
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="voice_stack",
            schema=schema,
            handler=handler,
            emoji=emoji,
        )
    # Start the HA-facing WebSocket receiver used by the Home Assistant
    # custom integration at /api/hermes/ws. It is fire-and-forget: when the
    # port is already occupied or aiohttp is unavailable, the warning is logged
    # and normal tool registration still succeeds.
    try:
        from plugins.voice_stack.ws_receiver import start_ws_receiver
        start_ws_receiver()
    except Exception as exc:
        logger.warning("Hermes HA WebSocket receiver did not start: %s", exc)

    # Run availability check in background so voice_status is accurate
    _init_engines()
