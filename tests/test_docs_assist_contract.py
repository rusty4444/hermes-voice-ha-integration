"""Keep the Assist round-trip documentation tied to the shipped code.

Issues #33 and #60 came from README text that said the ``assist_query``
receiver still had to be implemented "on the Hermes Agent server side" and
quoted an error message the integration never speaks. The receiver ships in
``plugins/voice_stack`` and the spoken message lives in ``conversation.py``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _not_responding_message() -> str:
    source = (ROOT / "custom_components/hermes/conversation.py").read_text(encoding="utf-8")
    match = re.search(r'"(Sorry, Hermes is not responding[^"]*)"', source)
    assert match, "conversation.py no longer speaks the documented timeout message"
    return match.group(1)


def test_readme_quotes_the_message_assist_actually_speaks() -> None:
    message = _not_responding_message()
    assert message in README
    assert "Sorry, I couldn't reach Hermes" not in README


def test_readme_does_not_say_the_receiver_is_missing() -> None:
    assert "must be implemented on the Hermes Agent server side" not in README
    assert "the Hermes Agent server **must** handle" not in README
    assert "voice_stack" in README and "handle_assist_query" in README


def test_documented_receiver_handles_assist_query() -> None:
    receiver = (ROOT / "plugins/voice_stack/ws_receiver.py").read_text(encoding="utf-8")
    assert "async def handle_assist_query" in receiver
    assert 'if msg_type == "assist_query"' in receiver
