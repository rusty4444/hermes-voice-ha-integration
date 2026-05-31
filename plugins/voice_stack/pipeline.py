"""Voice Pipeline Orchestrator.

Orchestrates the end-to-end voice interaction loop:

    Wake Word → STT → [Hermes Agent loop] → TTS → HA media_player

The pipeline runs in a background thread. When the wake word fires, it:
1. Records audio until silence / max duration
2. Transcribes via STT
3. Passes text to the Hermes agent via callback
4. Synthesises the agent's response via TTS
5. Plays the response through HA media_player or local audio
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class VoiceRecordingError(RuntimeError):
    """Raised when microphone capture fails before speech classification."""

# ---------------------------------------------------------------------------
# Audio recording helper
# ---------------------------------------------------------------------------

def record_audio(
    output_path: str,
    duration: float = 10.0,
    sample_rate: int = 16000,
    silence_timeout: float = 2.0,
    silence_threshold: float = 0.02,
) -> bool:
    """Record audio from the default microphone.

    Records until silence is detected for `silence_timeout` seconds
    or `duration` is reached.

    Returns True if audio was recorded, False on hardware error.
    """
    import numpy as np
    try:
        import sounddevice as sd
    except ImportError as exc:
        logger.error("sounddevice not installed — cannot record audio")
        raise VoiceRecordingError("sounddevice not installed — cannot record audio") from exc

    try:
        # Record raw audio
        audio_data = sd.rec(
            int(duration * sample_rate),
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
        )
        sd.wait()

        # Detect speech onset (simple energy threshold)
        rms = np.sqrt(np.mean(audio_data ** 2))
        if rms < silence_threshold:
            logger.debug("Audio too quiet (RMS=%.4f), discarding", rms)
            return False

        # Trim trailing silence
        frame_size = int(0.1 * sample_rate)  # 100ms frames
        energy = np.array([
            np.sqrt(np.mean(audio_data[i:i + frame_size] ** 2))
            for i in range(0, len(audio_data) - frame_size, frame_size)
        ])
        speech_frames = energy > silence_threshold
        if not speech_frames.any():
            return False

        # Find last speech frame
        last_speech = np.where(speech_frames)[0][-1]
        trim_end = min((last_speech + int(silence_timeout / 0.1)) * frame_size, len(audio_data))
        trimmed = audio_data[:trim_end]

        # Save as WAV
        import wave
        trimmed_int16 = (trimmed * 32767).astype(np.int16)
        with wave.open(output_path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(trimmed_int16.tobytes())

        duration_actual = len(trimmed) / sample_rate
        logger.info("Recorded %.1fs of audio to %s", duration_actual, output_path)
        return True

    except Exception as exc:
        logger.error("Audio recording failed: %s", exc)
        raise VoiceRecordingError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Audio playback
# ---------------------------------------------------------------------------

def play_audio_local(audio_path: str, device_id: Optional[int] = None) -> bool:
    """Play an audio file through local speakers via ffplay."""
    if not os.path.exists(audio_path):
        logger.error("Audio file not found: %s", audio_path)
        return False

    # Prefer ffplay (part of ffmpeg)
    for player in ("ffplay", "afplay", "aplay", "paplay"):
        if shutil.which(player):
            cmd = [player]
            if player == "ffplay":
                cmd += ["-autoexit", "-nodisp", "-loglevel", "quiet"]
                if device_id is not None:
                    cmd += ["-audio_device", str(device_id)]
            cmd.append(audio_path)
            try:
                subprocess.run(cmd, capture_output=True, timeout=30, check=True)
                return True
            except Exception as exc:
                logger.error("%s playback failed: %s", player, exc)
                return False

    logger.error("No audio player found (install ffmpeg)")
    return False


def play_audio_ha(audio_path: str, media_player_entity: str) -> bool:
    """Play an audio file through a Home Assistant media_player entity.

    Uses the Hermes HTTP server to serve the audio file, then calls
    media_player.play_media on the HA entity to stream it.
    """
    # Import the HA bridge to call services
    try:
        from ..home_assistant.ha_assistant import call_service
    except ImportError:
        logger.error("HA bridge not available — cannot use media_player playback")
        return False

    # Determine the audio URL (serve from Hermes HTTP server)
    audio_url = f"file://{audio_path}"

    result = call_service(
        "media_player",
        "play_media",
        entity_id=media_player_entity,
        data={
            "media_content_id": audio_url,
            "media_content_type": "music",
        },
    )
    if "error" in result:
        logger.error("HA media_player.play_media failed: %s", result["error"])
        return False
    return True


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------

class VoicePipelineState:
    """Encapsulates the mutable state of the voice pipeline."""

    def __init__(self) -> None:
        self.enabled: bool = False
        self.listening: bool = False
        self.wake_word_detected: bool = False
        self.last_transcript: str = ""
        self.last_confidence: float = 1.0
        self.total_interactions: int = 0
        self.total_errors: int = 0
        self.start_time: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        uptime = time.monotonic() - self.start_time if self.start_time else 0
        return {
            "enabled": self.enabled,
            "listening": self.listening,
            "wake_word_detected": self.wake_word_detected,
            "last_transcript": self.last_transcript[:100],
            "last_confidence": round(self.last_confidence, 3),
            "total_interactions": self.total_interactions,
            "total_errors": self.total_errors,
            "uptime_seconds": round(uptime, 1),
        }


# ---------------------------------------------------------------------------
# Voice System Prompt
# ---------------------------------------------------------------------------

VOICE_SYSTEM_PROMPT = """You are Hermes, a voice-controlled home assistant running entirely on-device.
No cloud. No latency. No subscription.

Current time: {current_time}
Home areas: {areas}
Key entities: {entities}

RULES:
1. Respond CONCISELY — this is voice. One sentence when possible, at most two.
2. Use ha_call_service to control devices.
3. Use ha_search_entities to find entities by name, domain, or area.
4. If ambiguous, ask a brief clarifying question (≤7 words).
5. Never return internal state JSON — summarise in plain English.
6. After calling a service, confirm success in ≤5 words (e.g. "Done. Light is off.")
7. If a service fails, tell the user what went wrong in one sentence.
8. Use the user's name if known, but don't overdo it.

VOICE-ONLY CONSTRAINTS:
- No markdown, code blocks, or bullet points
- No URLs or file paths
- Spell out numbers naturally (e.g. "twenty-two degrees" not "22°C")
- Prefer "living room" over "living_room"
- Never say "entity_id" or "service" — speak like a person"""


def build_voice_system_prompt(
    current_time: Optional[str] = None,
    areas: Optional[Dict[str, Any]] = None,
    entities: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Build a voice-optimised system prompt with current context."""
    from datetime import datetime

    if current_time is None:
        current_time = datetime.now().strftime("%A, %B %d %Y at %I:%M %p")

    areas_str = json.dumps(areas, indent=2) if areas else "Unknown"

    if entities is None:
        entities_str = "No entity data loaded"
    elif len(entities) > 20:
        # Summarise for the prompt
        by_domain: Dict[str, int] = {}
        for e in entities:
            domain = e.get("entity_id", "").split(".")[0]
            by_domain[domain] = by_domain.get(domain, 0) + 1
        entities_str = f"{len(entities)} entities across {len(by_domain)} domains: {json.dumps(by_domain)}"
    else:
        entities_str = json.dumps(entities, indent=2)

    return VOICE_SYSTEM_PROMPT.format(
        current_time=current_time,
        areas=areas_str,
        entities=entities_str,
    )


# ---------------------------------------------------------------------------
# Pipeline Orchestrator
# ---------------------------------------------------------------------------

class VoicePipeline:
    """Orchestrates the voice pipeline: WakeWord → STT → LLM → TTS → Playback.

    Usage:
        pipeline = VoicePipeline(callback=handle_user_text)
        pipeline.start()
        # ... wake word triggers recording → STT → callback → TTS ...
        pipeline.stop()
    """

    def __init__(
        self,
        callback: Callable[[str], str],
        *,
        wake_word_engine: Any = None,
        stt_engine: Any = None,
        tts_engine: Any = None,
        media_player_entity: Optional[str] = None,
        max_record_duration: float = 10.0,
        silence_timeout: float = 2.0,
        confidence_threshold: float = 0.70,
    ) -> None:
        self._callback = callback  # (text: str) -> response: str
        self._wake_word = wake_word_engine
        self._stt = stt_engine
        self._tts = tts_engine
        self._media_player_entity = media_player_entity
        self._max_record_duration = max_record_duration
        self._silence_timeout = silence_timeout
        self._confidence_threshold = confidence_threshold

        self._thread: Optional[threading.Thread] = None
        self._state = VoicePipelineState()
        self._lock = threading.Lock()

    @property
    def state(self) -> VoicePipelineState:
        return self._state

    @property
    def available(self) -> bool:
        """Return True if at minimum TTS and STT engines are available."""
        tts_ok = self._tts is not None and self._tts.available()
        stt_ok = self._stt is not None and self._stt.available()
        return tts_ok and stt_ok

    def start(self) -> bool:
        """Start the voice pipeline in a background thread."""
        if not self.available:
            logger.error("Cannot start voice pipeline: engines not available")
            return False

        if self._thread and self._thread.is_alive():
            logger.warning("Voice pipeline already running")
            return False

        self._state.enabled = True
        self._state.start_time = time.monotonic()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="voice-pipeline")
        self._thread.start()
        logger.info("Voice pipeline started")
        return True

    def stop(self) -> None:
        """Stop the voice pipeline."""
        self._state.enabled = False
        if self._wake_word:
            self._wake_word.stop()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("Voice pipeline stopped")

    def _run_loop(self) -> None:
        """Main voice pipeline loop (runs in background thread)."""
        while self._state.enabled:
            try:
                self._state.listening = True

                # 1. Wait for wake word
                if self._wake_word:
                    detected = self._wake_word.listen(timeout_seconds=5.0)
                    if not detected:
                        continue
                    self._state.wake_word_detected = True

                # 2. Record audio
                cache_dir = Path.home() / ".hermes" / "voice_cache"
                cache_dir.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(cache_dir)) as tmp:
                    audio_path = tmp.name

                try:
                    recorded = record_audio(
                        audio_path,
                        duration=self._max_record_duration,
                        silence_timeout=self._silence_timeout,
                    )
                except Exception:
                    try:
                        os.unlink(audio_path)
                    except OSError:
                        pass
                    raise
                if not recorded:
                    os.unlink(audio_path)
                    continue

                # 3. STT
                stt_result = self._stt.transcribe_with_confidence(audio_path)
                transcript = stt_result.get("text", "").strip()
                confidence = stt_result.get("confidence", 1.0)

                self._state.last_transcript = transcript
                self._state.last_confidence = confidence

                # Clean up audio file
                try:
                    os.unlink(audio_path)
                except OSError:
                    pass

                if not transcript:
                    continue

                # Low confidence → ask for confirmation
                if confidence < self._confidence_threshold:
                    self._speak(f"Did you say: {transcript}?")
                    # TODO: implement confirmation loop (P2)
                    continue

                logger.info("Voice input: \"%s\" (confidence=%.2f)", transcript, confidence)

                # 4. LLM callback
                response = self._callback(transcript)

                if not response:
                    continue

                # 5. TTS synthesis + playback
                if not self._speak(response):
                    continue

                self._state.total_interactions += 1
                self._state.wake_word_detected = False

            except Exception as exc:
                logger.error("Voice pipeline error: %s", exc, exc_info=True)
                self._state.total_errors += 1
                time.sleep(1.0)  # Back off on error
            finally:
                self._state.listening = False

    def _speak(self, text: str) -> bool:
        """Speak text through TTS + playback with retry fallback."""
        for attempt in (1, 2):
            try:
                audio_path = self._tts.synthesize(text)
                if not audio_path:
                    raise RuntimeError("TTS engine returned no audio path")
                if self._media_player_entity:
                    played = play_audio_ha(audio_path, self._media_player_entity)
                else:
                    played = play_audio_local(audio_path)
                if not played:
                    raise RuntimeError("Audio playback failed")
                return True
            except Exception as exc:
                logger.warning("TTS speak failed (attempt %d/2): %s", attempt, exc)
                if attempt == 1:
                    time.sleep(0.5)  # brief backoff before retry
                else:
                    logger.error("TTS speak failed after 2 attempts: %s", exc)
        return False
