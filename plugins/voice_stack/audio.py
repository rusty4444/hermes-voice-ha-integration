"""Audio I/O helpers — deprecated, see pipeline.py instead.

This module is a backwards-compatibility shim. New code uses:
- plugins.voice_stack.pipeline.record_audio()
- plugins.voice_stack.pipeline.play_audio_local()
- plugins.voice_stack.pipeline.play_audio_ha()
"""

from plugins.voice_stack.pipeline import play_audio_local as play_audio_file  # noqa: F401
from plugins.voice_stack.pipeline import record_audio  # noqa: F401
