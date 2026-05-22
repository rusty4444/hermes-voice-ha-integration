"""Audio I/O helpers for the Voice Stack plugin.

P0 stub — real microphone / playback wiring is deferred to P1.
All functions are safe to import at module level; hardware calls
are deferred to runtime handlers so missing audio libraries do
not crash Hermes startup.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional


def _check_audio_libs() -> bool:
    """Return True if sounddevice + numpy are importable."""
    try:
        import sounddevice as _  # noqa: F401
        import numpy as _          # noqa: F401
        return True
    except ImportError:
        return False


def list_playback_devices() -> Dict[str, Any]:
    """Return available audio output devices (non-fatal if unavailable)."""
    if not _check_audio_libs():
        return {"ok": False, "error": "audio libs not installed (pip install sounddevice numpy)"}
    import sounddevice as sd
    devices = sd.query_devices()
    outputs = [
        {"id": i, "name": d["name"], "default": d.get("default_output")}
        for i, d in enumerate(devices)
        if d.get("max_output_channels", 0) > 0
    ]
    return {"ok": True, "devices": outputs}


def play_audio_file(path: str, device_id: Optional[int] = None) -> Dict[str, Any]:
    """Play a WAV/OGG/MP3 file through the default audio device or *device_id*."""
    if shutil.which("ffplay") is None:
        return {"ok": False, "error": "ffplay not found (install ffmpeg)"}
    cmd = ["ffplay", "-autoexit", "-nodisp", "-loglevel", "quiet"]
    if device_id is not None:
        cmd += ["-audio_device", str(device_id)]
    cmd.append(path)
    proc = subprocess.run(cmd, capture_output=True, timeout=30)
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode}
