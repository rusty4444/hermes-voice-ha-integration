"""Hermes ⇄ Home Assistant WebSocket receiver.

This module exposes the `/api/hermes/ws` endpoint that the Home Assistant
custom integration connects to. It is intentionally small and dependency-light:
Home Assistant sends JSON events/actions, and this receiver dispatches voice
control actions to the local voice stack tools.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

try:
    from aiohttp import WSMsgType, web
    AIOHTTP_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in minimal installs
    WSMsgType = None  # type: ignore[assignment]
    web = None  # type: ignore[assignment]
    AIOHTTP_AVAILABLE = False

if TYPE_CHECKING:  # pragma: no cover
    from aiohttp import web as aiohttp_web

logger = logging.getLogger(__name__)

DEFAULT_WS_HOST = "0.0.0.0"
DEFAULT_WS_PORT = 7860
DEFAULT_WS_PATH = "/api/hermes/ws"

_WS_SERVER: Optional["HermesHAWebSocketServer"] = None
_WS_LOCK = threading.Lock()
_START_TIME = time.monotonic()
_MESSAGE_COUNTERS: dict[str, int] = {}
_COUNTER_LOCK = threading.Lock()
_VOICE_ACTION_RESERVED_KEYS = {"type", "action", "args"}


def _record_message(msg_type: str) -> None:
    """Track receiver message counts for health/status responses."""
    key = msg_type or "<missing>"
    with _COUNTER_LOCK:
        _MESSAGE_COUNTERS[key] = _MESSAGE_COUNTERS.get(key, 0) + 1


def _message_counters_snapshot() -> dict[str, int]:
    with _COUNTER_LOCK:
        return dict(_MESSAGE_COUNTERS)


def receiver_status(server: Optional["HermesHAWebSocketServer"] = None) -> dict[str, Any]:
    """Return process-local receiver health data safe for HA status probes."""
    active_connections = 0
    total_connections = 0
    running = False
    bound: dict[str, Any] = {}
    target = server or _WS_SERVER
    if target is not None:
        active_connections = target.active_connections
        total_connections = target.total_connections
        running = target.running
        bound = {"host": target.host, "port": target.port, "path": target.path}
    return {
        "ok": True,
        "service": "hermes-ha-ws",
        "running": running,
        "uptime_seconds": round(time.monotonic() - _START_TIME, 1),
        "auth_required": bool(_configured_token()),
        "active_connections": active_connections,
        "total_connections": total_connections,
        "message_counters": _message_counters_snapshot(),
        **bound,
    }


def _with_request_id(payload: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Preserve caller request IDs for HA-side correlation."""
    if "id" in payload and "id" not in response:
        response = {**response, "id": payload["id"]}
    return response


def _json_loads_maybe(value: Any) -> dict[str, Any]:
    """Parse tool-handler JSON strings into dicts; wrap non-JSON values."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
            return {"value": parsed}
        except json.JSONDecodeError:
            return {"message": value}
    return {"value": value}


def _configured_token() -> str:
    """Return the optional bearer token accepted by the HA WebSocket endpoint."""
    return (
        os.getenv("HERMES_HA_WS_TOKEN")
        or os.getenv("API_SERVER_KEY")
        or os.getenv("HERMES_API_KEY")
        or ""
    ).strip()


def _auth_ok(headers: Mapping[str, str]) -> bool:
    """Validate Authorization when a receiver token is configured."""
    token = _configured_token()
    if not token:
        return True
    auth = headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return False
    supplied = auth[7:].strip()
    return hmac.compare_digest(supplied, token)


def handle_voice_action(payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a HA-originated voice action to voice_stack handlers.

    Supported actions:
    - enable  -> voice_enable
    - disable -> voice_disable
    - status  -> voice_status
    """
    action = str(payload.get("action", "")).strip().lower()
    args = dict(payload.get("args") or {})
    for key, value in payload.items():
        if key not in _VOICE_ACTION_RESERVED_KEYS and key not in args:
            args[key] = value

    from . import (
        _handle_voice_disable,
        _handle_voice_enable,
        _handle_voice_status,
    )

    handlers: dict[str, Callable[[dict], str]] = {
        "enable": _handle_voice_enable,
        "disable": _handle_voice_disable,
        "status": _handle_voice_status,
    }
    handler = handlers.get(action)
    if handler is None:
        return {
            "ok": False,
            "error": f"Unsupported voice action: {action or '<missing>'}",
            "supported_actions": sorted(handlers),
        }

    try:
        result = _json_loads_maybe(handler(args))
        ok = bool(result.get("ok", True)) if "error" not in result else False
        return {"ok": ok, "action": action, "result": result}
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        logger.exception("voice_action %s failed", action)
        return {"ok": False, "action": action, "error": str(exc)}


def handle_ha_ws_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle one JSON payload from Home Assistant."""
    msg_type = str(payload.get("type", "")).strip().lower()
    _record_message(msg_type)

    if msg_type == "voice_action":
        result = handle_voice_action(payload)
        return _with_request_id(payload, {"type": "voice_action_result", **result})

    if msg_type == "state_changed":
        # P0 receiver behaviour: acknowledge state pushes so HA knows Hermes
        # accepted the event. Context ingestion can be layered on this later.
        return _with_request_id(payload, {
            "type": "ack",
            "ok": True,
            "received": "state_changed",
            "entity_id": payload.get("entity_id"),
        })

    if msg_type == "ping":
        return _with_request_id(payload, {"type": "pong", "ok": True})

    if msg_type == "status":
        return _with_request_id(payload, {"type": "status", **receiver_status()})

    return _with_request_id(payload, {"type": "error", "ok": False, "error": f"Unsupported message type: {msg_type or '<missing>'}"})


class HermesHAWebSocketServer:
    """Small aiohttp WebSocket server for HA-originated Hermes messages."""

    def __init__(self, host: str = DEFAULT_WS_HOST, port: int = DEFAULT_WS_PORT, path: str = DEFAULT_WS_PATH) -> None:
        if not AIOHTTP_AVAILABLE:
            raise RuntimeError("aiohttp is required for Hermes HA WebSocket receiver")
        self.host = host
        self.port = int(port)
        self.path = path
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._runner: Optional["aiohttp_web.AppRunner"] = None
        self._started = threading.Event()
        self._stopped = threading.Event()
        self._active_connections = 0
        self._total_connections = 0
        self._connections_lock = threading.Lock()

    @property
    def active_connections(self) -> int:
        with self._connections_lock:
            return self._active_connections

    @property
    def total_connections(self) -> int:
        with self._connections_lock:
            return self._total_connections

    def _connection_opened(self) -> None:
        with self._connections_lock:
            self._active_connections += 1
            self._total_connections += 1

    def _connection_closed(self) -> None:
        with self._connections_lock:
            self._active_connections = max(0, self._active_connections - 1)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._started.is_set()

    def start(self) -> bool:
        """Start the receiver in a daemon thread. Returns False if already running."""
        if self.running:
            return False
        self._stopped.clear()
        self._thread = threading.Thread(target=self._run_thread, name="hermes-ha-ws", daemon=True)
        self._thread.start()
        self._started.wait(timeout=5.0)
        return self.running

    def stop(self) -> None:
        """Stop the receiver."""
        if not self._loop or not self.running:
            return
        future = asyncio.run_coroutine_threadsafe(self._shutdown(), self._loop)
        try:
            future.result(timeout=5.0)
        except Exception as exc:  # pragma: no cover - defensive shutdown path
            logger.warning("Hermes HA WebSocket shutdown failed: %s", exc)
        if self._thread:
            self._thread.join(timeout=5.0)

    def _run_thread(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._start_async())
            self._started.set()
            logger.info("Hermes HA WebSocket receiver listening on %s:%s%s", self.host, self.port, self.path)
            loop.run_forever()
        except Exception as exc:
            logger.warning("Hermes HA WebSocket receiver failed to start: %s", exc)
            self._started.set()
        finally:
            try:
                loop.run_until_complete(self._shutdown())
            except Exception:
                pass
            loop.close()
            self._stopped.set()

    async def _start_async(self) -> None:
        assert web is not None
        app = web.Application()
        app.router.add_get(self.path, self._handle_ws)
        app.router.add_get("/health", self._handle_health)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        self._runner = runner

    async def _shutdown(self) -> None:
        runner = self._runner
        self._runner = None
        if runner is not None:
            await runner.cleanup()
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

    async def _handle_health(self, request: "aiohttp_web.Request") -> "aiohttp_web.Response":
        assert web is not None
        return web.json_response({"type": "status", **receiver_status(self)})

    async def _handle_ws(self, request: "aiohttp_web.Request") -> "aiohttp_web.WebSocketResponse":
        assert web is not None
        assert WSMsgType is not None
        if not _auth_ok(request.headers):
            raise web.HTTPUnauthorized(text="Invalid bearer token")

        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._connection_opened()
        await ws.send_json({"type": "hello", "ok": True, "service": "hermes-ha-ws"})

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                        if not isinstance(payload, dict):
                            raise ValueError("payload must be a JSON object")
                        response = handle_ha_ws_payload(payload)
                    except Exception as exc:
                        response = {"type": "error", "ok": False, "error": str(exc)}
                    await ws.send_json(response)
                elif msg.type == WSMsgType.ERROR:
                    logger.debug("HA WebSocket closed with error: %s", ws.exception())
                    break
        finally:
            self._connection_closed()
        return ws


def start_ws_receiver(host: Optional[str] = None, port: Optional[int] = None, path: Optional[str] = None) -> Optional[HermesHAWebSocketServer]:
    """Start the singleton HA WebSocket receiver if enabled."""
    if os.getenv("HERMES_HA_WS_ENABLED", "1").strip().lower() in {"0", "false", "no", "off"}:
        logger.info("Hermes HA WebSocket receiver disabled by HERMES_HA_WS_ENABLED")
        return None
    if not AIOHTTP_AVAILABLE:
        logger.warning("Hermes HA WebSocket receiver unavailable: aiohttp is not installed")
        return None

    resolved_host = host or os.getenv("HERMES_HA_WS_HOST", DEFAULT_WS_HOST)
    resolved_port = int(port or os.getenv("HERMES_HA_WS_PORT", str(DEFAULT_WS_PORT)))
    resolved_path = path or os.getenv("HERMES_HA_WS_PATH", DEFAULT_WS_PATH)

    global _WS_SERVER
    with _WS_LOCK:
        if _WS_SERVER and _WS_SERVER.running:
            return _WS_SERVER
        _WS_SERVER = HermesHAWebSocketServer(resolved_host, resolved_port, resolved_path)
        _WS_SERVER.start()
        return _WS_SERVER if _WS_SERVER.running else None


def stop_ws_receiver() -> None:
    """Stop the singleton receiver."""
    global _WS_SERVER
    with _WS_LOCK:
        server = _WS_SERVER
        _WS_SERVER = None
    if server is not None:
        server.stop()
