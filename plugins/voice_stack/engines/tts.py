"""TTS Engine — text-to-speech synthesis.

Concrete engines:
- EdgeTTSEngine: Microsoft Edge TTS (free, good quality, requires network)
- PiperTTSEngine: Piper TTS (offline, fast, ~100MB per voice model)
- CommandTTSEngine: Generic CLI TTS (for custom engines)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Cache dir for TTS output
_TTS_CACHE_DIR = Path(os.getenv("HERMES_VOICE_CACHE", str(Path.home() / ".hermes" / "voice_cache")))
_TTS_CACHE_DIR.mkdir(parents=True, exist_ok=True)


class TTSEngine(ABC):
    """Abstract TTS engine interface."""

    @abstractmethod
    def available(self) -> bool:
        """Return True if this engine's dependencies are installed."""
        ...

    @abstractmethod
    def synthesize(self, text: str, voice: Optional[str] = None) -> str:
        """Synthesise text to an audio file. Returns the file path."""
        ...

    @abstractmethod
    def list_voices(self) -> list[Dict[str, str]]:
        """Return available voice names with metadata."""
        ...


# ---------------------------------------------------------------------------
# Edge TTS (Microsoft — free, good quality, requires network)
# ---------------------------------------------------------------------------

# Cache voice list for 1 hour
_EDGE_VOICES_CACHE: Optional[list[Dict[str, str]]] = None
_EDGE_VOICES_CACHE_TS: float = 0.0


class EdgeTTSEngine(TTSEngine):
    """Microsoft Edge TTS engine via edge-tts CLI.

    Voice names: en-US-AriaNeural, en-US-GuyNeural, en-GB-SoniaNeural, etc.
    Full list at: https://learn.microsoft.com/en-us/azure/ai-services/speech-service/language-support
    """

    def __init__(self, voice: str = "en-US-AriaNeural") -> None:
        self._voice = voice

    def available(self) -> bool:
        return shutil.which("edge-tts") is not None

    def synthesize(self, text: str, voice: Optional[str] = None) -> str:
        voice = voice or self._voice
        output_path = str(_TTS_CACHE_DIR / f"tts_edge_{hash(text) & 0x7FFFFFFF}.mp3")

        # edge-tts --voice en-US-AriaNeural --text "..." --write-media output.mp3
        result = subprocess.run(
            [
                "edge-tts",
                "--voice", voice,
                "--text", text,
                "--write-media", output_path,
            ],
            capture_output=True,
            timeout=30,
            text=True,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip() or result.stdout.strip()
            raise RuntimeError(f"edge-tts failed (exit {result.returncode}): {stderr}")

        return output_path

    def list_voices(self) -> list[Dict[str, str]]:
        global _EDGE_VOICES_CACHE, _EDGE_VOICES_CACHE_TS
        import time
        now = time.monotonic()
        if _EDGE_VOICES_CACHE is not None and (now - _EDGE_VOICES_CACHE_TS) < 3600:
            return _EDGE_VOICES_CACHE  # type: ignore[return-value]

        result = subprocess.run(
            ["edge-tts", "--list-voices"],
            capture_output=True, timeout=15, text=True,
        )
        voices: list[Dict[str, str]] = []
        if result.returncode == 0:
            import json
            try:
                data = json.loads(result.stdout)
                for entry in data:
                    voices.append({
                        "name": entry.get("ShortName", "unknown"),
                        "locale": entry.get("Locale", "unknown"),
                        "gender": entry.get("Gender", "unknown"),
                    })
            except json.JSONDecodeError:
                logger.warning("Could not parse edge-tts voice list JSON")
                # Fallback: return known good voices
                voices = [
                    {"name": "en-US-AriaNeural", "locale": "en-US", "gender": "Female"},
                    {"name": "en-US-GuyNeural", "locale": "en-US", "gender": "Male"},
                    {"name": "en-GB-SoniaNeural", "locale": "en-GB", "gender": "Female"},
                    {"name": "en-GB-RyanNeural", "locale": "en-GB", "gender": "Male"},
                    {"name": "en-AU-NatashaNeural", "locale": "en-AU", "gender": "Female"},
                ]
        _EDGE_VOICES_CACHE = voices
        _EDGE_VOICES_CACHE_TS = now
        return voices


# ---------------------------------------------------------------------------
# Piper TTS (offline, fast, ~100MB per voice model)
# ---------------------------------------------------------------------------

class PiperTTSEngine(TTSEngine):
    """Piper TTS — local neural TTS, no network required.

    Install: pip install piper-tts
    Download voices: https://huggingface.co/rhasspy/piper-voices

    Default model: en_US-lessac-medium (female, US English)
    """

    def __init__(self, voice: str = "en_US-lessac-medium") -> None:
        self._voice = voice

    def available(self) -> bool:
        return shutil.which("piper") is not None

    def synthesize(self, text: str, voice: Optional[str] = None) -> str:
        voice = voice or self._voice
        output_path = str(_TTS_CACHE_DIR / f"tts_piper_{hash(text) & 0x7FFFFFFF}.wav")

        model_path = _find_piper_model(voice)
        if not model_path:
            raise RuntimeError(
                f"Piper voice model '{voice}' not found. "
                f"Download from https://huggingface.co/rhasspy/piper-voices"
            )

        # piper --model <model> --output_file <output.wav>
        proc = subprocess.run(
            ["piper", "--model", model_path, "--output_file", output_path],
            input=text,
            capture_output=True,
            timeout=30,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"piper failed (exit {proc.returncode}): {proc.stderr.strip()}")

        return output_path

    def list_voices(self) -> list[Dict[str, str]]:
        """Return available Piper voice models found on disk."""
        voices: list[Dict[str, str]] = []
        model_dirs = [
            Path.home() / ".local" / "share" / "piper-tts",
            Path.home() / ".config" / "piper",
            Path("/usr/share/piper-tts"),
        ]
        for d in model_dirs:
            if d.is_dir():
                for f in sorted(d.glob("*.onnx")):
                    voices.append({
                        "name": f.stem,
                        "locale": _guess_locale(f.stem),
                        "gender": _guess_gender(f.stem),
                    })
        return voices


# ---------------------------------------------------------------------------
# Command TTS (generic CLI wrapper — for custom engines)
# ---------------------------------------------------------------------------

class CommandTTSEngine(TTSEngine):
    """Generic CLI-based TTS engine.

    Config: tts.command = ["espeak", "-w", "{output}", "{text}"]
    The {text} and {output} placeholders are substituted at runtime.
    """

    def __init__(self, command: list[str]) -> None:
        self._command = command

    def available(self) -> bool:
        return shutil.which(self._command[0]) is not None if self._command else False

    def synthesize(self, text: str, voice: Optional[str] = None) -> str:
        output_path = str(_TTS_CACHE_DIR / f"tts_cmd_{hash(text) & 0x7FFFFFFF}.wav")
        cmd = [part.replace("{text}", text).replace("{output}", output_path) for part in self._command]
        result = subprocess.run(cmd, capture_output=True, timeout=30, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"TTS command failed (exit {result.returncode}): {result.stderr.strip()}")
        return output_path

    def list_voices(self) -> list[Dict[str, str]]:
        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_piper_model(voice_name: str) -> Optional[str]:
    """Search standard locations for a Piper ONNX model file."""
    search_paths = [
        Path.home() / ".local" / "share" / "piper-tts",
        Path.home() / ".config" / "piper",
        Path("/usr/share/piper-tts"),
        Path.home() / ".hermes" / "voices",
    ]
    for d in search_paths:
        candidate = d / f"{voice_name}.onnx"
        if candidate.is_file():
            return str(candidate)
    return None


def _guess_locale(voice_name: str) -> str:
    """Guess locale from Piper voice name (e.g. en_US -> en-US)."""
    parts = voice_name.split("-")[0].split("_")
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}"
    return parts[0] if parts else "unknown"


def _guess_gender(voice_name: str) -> str:
    """Guess gender from Piper voice name."""
    name_lower = voice_name.lower()
    female_indicators = ["female", "f", "lessac", "amy", "kathleen", "ljspeech"]
    male_indicators = ["male", "m", "ryan", "joe", "kusal", "alan"]
    if any(i in name_lower for i in female_indicators):
        return "Female"
    if any(i in name_lower for i in male_indicators):
        return "Male"
    return "Unknown"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_tts_engine(engine_type: str = "edge", **kwargs: Any) -> TTSEngine:
    """Create a TTS engine instance by name.

    Args:
        engine_type: "edge", "piper", or "command"
        **kwargs: Passed to engine constructor (voice, command, etc.)
    """
    if engine_type == "edge":
        return EdgeTTSEngine(voice=kwargs.get("voice", "en-US-AriaNeural"))
    elif engine_type == "piper":
        return PiperTTSEngine(voice=kwargs.get("voice", "en_US-lessac-medium"))
    elif engine_type == "command":
        cmd = kwargs.get("command", ["espeak", "-w", "{output}", "{text}"])
        return CommandTTSEngine(command=cmd)
    else:
        raise ValueError(
            f"Unknown TTS engine '{engine_type}'. Valid: edge, piper, command"
        )
