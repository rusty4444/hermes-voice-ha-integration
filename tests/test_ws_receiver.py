"""Tests for the Home Assistant WebSocket receiver."""

from __future__ import annotations

import pytest

from plugins.voice_stack import ws_receiver
import plugins.voice_stack as voice_stack


@pytest.fixture(autouse=True)
def _reset_assist_handler():
    ws_receiver.set_assist_query_handler(None)
    yield
    ws_receiver.set_assist_query_handler(None)


@pytest.mark.asyncio
async def test_assist_query_returns_response_from_configured_handler():
    """assist_query should produce assist_response instead of timing out."""

    async def handler(payload: dict) -> dict:
        assert payload["text"] == "Hello Hermes"
        return {"text": "Hello from Hermes", "provider": "test-provider"}

    ws_receiver.set_assist_query_handler(handler)

    response = await ws_receiver.handle_ha_ws_payload_async(
        {
            "id": "req-1",
            "type": "assist_query",
            "text": "Hello Hermes",
            "conversation_id": "conv-1",
            "language": "en",
        }
    )

    assert response["id"] == "req-1"
    assert response["type"] == "assist_response"
    assert response["ok"] is True
    assert response["text"] == "Hello from Hermes"
    assert response["conversation_id"] == "conv-1"
    assert response["speech"]["plain"]["speech"] == "Hello from Hermes"
    assert response["provider"] == "test-provider"


@pytest.mark.asyncio
async def test_assist_query_without_handler_returns_spoken_fallback():
    """Missing handler should resolve HA's pending future with a fallback."""

    response = await ws_receiver.handle_ha_ws_payload_async(
        {
            "type": "assist_query",
            "text": "Are you there?",
            "conversation_id": "conv-2",
        }
    )

    assert response["type"] == "assist_response"
    assert response["ok"] is False
    assert response["conversation_id"] == "conv-2"
    assert "not available" in response["text"]
    assert response["speech"]["plain"]["speech"] == response["text"]


@pytest.mark.asyncio
async def test_assist_query_handler_exception_returns_spoken_error():
    """Handler exceptions should not fall back to unsupported-message errors."""

    def handler(_payload: dict) -> dict:
        raise RuntimeError("boom")

    ws_receiver.set_assist_query_handler(handler)

    response = await ws_receiver.handle_ha_ws_payload_async(
        {
            "id": "req-3",
            "type": "assist_query",
            "text": "break",
            "conversation_id": "conv-3",
        }
    )

    assert response["id"] == "req-3"
    assert response["type"] == "assist_response"
    assert response["ok"] is False
    assert response["error"] == "boom"
    assert response["conversation_id"] == "conv-3"


def test_sync_payload_handler_still_reports_unsupported_for_unknown_types():
    """Existing synchronous handler semantics are preserved."""

    response = ws_receiver.handle_ha_ws_payload({"id": "x", "type": "banana"})

    assert response == {
        "id": "x",
        "type": "error",
        "ok": False,
        "error": "Unsupported message type: banana",
    }


@pytest.mark.asyncio
async def test_voice_stack_assist_handler_uses_ctx_llm():
    """The registered voice-stack handler should call Hermes plugin LLM access."""

    class _Result:
        text = "LLM reply"
        provider = "provider-x"
        model = "model-y"

    class _Llm:
        def __init__(self):
            self.calls = []

        async def acomplete(self, **kwargs):
            self.calls.append(kwargs)
            return _Result()

    class _Ctx:
        def __init__(self):
            self.llm = _Llm()

    ctx = _Ctx()

    result = await voice_stack._handle_assist_query_with_llm(
        ctx,
        {
            "text": "What is the weather?",
            "language": "en-AU",
            "conversation_id": "conv-4",
        },
    )

    assert result == {
        "ok": True,
        "text": "LLM reply",
        "conversation_id": "conv-4",
        "provider": "provider-x",
        "model": "model-y",
    }
    assert ctx.llm.calls[0]["purpose"] == "voice_stack.assist_query"
    assert "What is the weather?" in ctx.llm.calls[0]["messages"][1]["content"]
