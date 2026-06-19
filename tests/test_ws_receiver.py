"""Tests for the Hermes HA WebSocket receiver."""

from __future__ import annotations

import pytest

from plugins.voice_stack import ws_receiver


@pytest.mark.asyncio
async def test_assist_query_without_handler_returns_assist_response() -> None:
    ws_receiver.set_assist_query_handler(None)

    response = await ws_receiver.async_handle_ha_ws_payload(
        {
            "id": "req-1",
            "type": "assist_query",
            "text": "hello",
            "conversation_id": "conv-1",
            "language": "en",
        }
    )

    assert response["id"] == "req-1"
    assert response["type"] == "assist_response"
    assert response["ok"] is False
    assert response["conversation_id"] == "conv-1"
    assert response["speech"]["plain"]["speech"] == response["text"]
    assert response["error"] == "assist_handler_unavailable"


@pytest.mark.asyncio
async def test_assist_query_dispatches_registered_async_handler() -> None:
    async def handler(payload: dict) -> dict:
        return {"text": f"Heard: {payload['text']}", "extra": "kept"}

    ws_receiver.set_assist_query_handler(handler)
    try:
        response = await ws_receiver.async_handle_ha_ws_payload(
            {
                "id": "req-2",
                "type": "assist_query",
                "text": "turn on the kitchen light",
                "conversation_id": "conv-2",
                "language": "en-AU",
            }
        )
    finally:
        ws_receiver.set_assist_query_handler(None)

    assert response["id"] == "req-2"
    assert response["type"] == "assist_response"
    assert response["ok"] is True
    assert response["conversation_id"] == "conv-2"
    assert response["language"] == "en-AU"
    assert response["text"] == "Heard: turn on the kitchen light"
    assert response["speech"]["plain"]["speech"] == response["text"]
    assert response["extra"] == "kept"


def test_sync_dispatcher_keeps_assist_query_out_of_unsupported_fallback() -> None:
    response = ws_receiver.handle_ha_ws_payload(
        {"id": "req-3", "type": "assist_query", "text": "hello"}
    )

    assert response["id"] == "req-3"
    assert response["type"] == "error"
    assert response["error"] == "assist_query requires the async WebSocket dispatcher"
    assert "Unsupported message type" not in response["error"]
