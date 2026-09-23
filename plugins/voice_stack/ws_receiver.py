"""Hermes ⇄ Home Assistant WebSocket receiver.

This module exposes the `/api/hermes/ws` endpoint that the Home Assistant
custom integration connects to. It is intentionally small and dependency-light:
Home Assistant sends JSON events/actions, and this receiver dispatches voice
control actions to the local voice stack tools.
"""

from __future__ import annotations

import asyncio
import contextvars
import errno
import hashlib
import hmac
import http.client
import importlib
import inspect
import json
import logging
import os
import socket
import sys
import threading
import time
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

try:
    from aiohttp import WSCloseCode, WSMsgType, web
    AIOHTTP_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in minimal installs
    WSCloseCode = None  # type: ignore[assignment]
    WSMsgType = None  # type: ignore[assignment]
    web = None  # type: ignore[assignment]
    AIOHTTP_AVAILABLE = False

if TYPE_CHECKING:  # pragma: no cover
    from aiohttp import web as aiohttp_web

logger = logging.getLogger(__name__)

DEFAULT_WS_HOST = "0.0.0.0"
DEFAULT_WS_PORT = 7860
DEFAULT_WS_PATH = "/api/hermes/ws"
DEFAULT_HEALTH_PATH = "/health"
SERVICE_ID = "hermes-ha-ws"
SHUTDOWN_TIMEOUT_SECONDS = 1.0

# The receiver is a process-wide singleton, but Hermes re-imports plugin modules
# freely — the gateway, every CLI session and the dashboard each get fresh module
# globals — so the live instance is recorded on `sys`, which survives re-imports,
# and the port is probed before binding. The record carries its OWNER (module
# file, Hermes profile, bind config and pid) so another profile cannot adopt or
# stop it. A fresh import of the same owner rebinds even when the source bytes are
# unchanged: Hermes force-reload creates a new PluginContext and assist handler,
# while the old server remains bound to the old module's globals.
_PROC_SINGLETON_ATTR = "_hermes_voice_stack_ws_receiver"
_BIND_PROBE_TIMEOUT = 1.5
_PROBE_MAX_BYTES = 8192
_WILDCARD_HOSTS = {"", "*", "0.0.0.0", "::"}

_WS_SERVER: Optional["HermesHAWebSocketServer"] = None
_WS_LOCK = threading.Lock()
_START_TIME = time.monotonic()
_MESSAGE_COUNTERS: dict[str, int] = {}
_COUNTER_LOCK = threading.Lock()
_VOICE_ACTION_RESERVED_KEYS = {"type", "action", "args"}
_AssistQueryHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]
_ASSIST_QUERY_HANDLER: Optional[_AssistQueryHandler] = None


def _record_message(msg_type: str) -> None:
    """Track receiver message counts for health/status responses."""
    key = msg_type or "<missing>"
    with _COUNTER_LOCK:
        _MESSAGE_COUNTERS[key] = _MESSAGE_COUNTERS.get(key, 0) + 1


def _message_counters_snapshot() -> dict[str, int]:
    with _COUNTER_LOCK:
        return dict(_MESSAGE_COUNTERS)


def set_assist_query_handler(handler: Optional[_AssistQueryHandler]) -> None:
    """Set the process-local handler for HA Assist query round-trips.

    The WebSocket receiver is intentionally framework-light, so the voice_stack
    plugin wires this during ``register(ctx)`` with a callback that can access
    the Hermes plugin context and LLM facade. Tests may pass ``None`` to reset
    the handler.
    """
    global _ASSIST_QUERY_HANDLER
    _ASSIST_QUERY_HANDLER = handler


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
        # Stable across processes for the same profile, without exposing its
        # filesystem path. The bind probe uses it to distinguish a harmless
        # duplicate from another profile occupying this profile's endpoint.
        "profile_id": _profile_identity(),
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


def _profile_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read one profile-scoped environment value, failing closed in multiplex.

    Hermes keeps profile ``.env`` values in a ContextVar because ``os.environ``
    belongs to the whole process. Import lazily so the receiver remains usable in
    standalone tests; only an unavailable Hermes API permits the legacy fallback.
    Exceptions from ``get_secret`` deliberately propagate rather than leaking a
    launch profile's process environment into a routed profile.
    """
    try:
        get_secret = getattr(importlib.import_module("agent.secret_scope"), "get_secret")
    except (ImportError, AttributeError):
        return os.environ.get(name, default)
    return get_secret(name, default)


def _configured_token() -> str:
    """Return the optional bearer token accepted by the HA WebSocket endpoint."""
    return (
        _profile_env("HERMES_HA_WS_TOKEN")
        or _profile_env("API_SERVER_KEY")
        or _profile_env("HERMES_API_KEY")
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


def _assist_response(
    payload: dict[str, Any],
    *,
    text: str,
    ok: bool = True,
    error: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an ``assist_response`` preserving HA correlation fields."""
    conversation_id = payload.get("conversation_id")
    response: dict[str, Any] = {
        "type": "assist_response",
        "ok": ok,
        "text": text,
        "conversation_id": conversation_id,
        "language": payload.get("language"),
        "speech": {"plain": {"speech": text}},
    }
    if error:
        response["error"] = error
    if extra:
        response.update(dict(extra))
    return _with_request_id(payload, response)


async def handle_assist_query(payload: dict[str, Any]) -> dict[str, Any]:
    """Process a Home Assistant Assist query and return ``assist_response``.

    HA's conversation platform sends ``assist_query`` and waits for an
    ``assist_response`` with the same ``conversation_id``. Returning a typed
    response even for errors avoids the HA side timing out on unsupported or
    failed messages.
    """
    text = str(payload.get("text") or "").strip()
    if not text:
        return _assist_response(
            payload,
            ok=False,
            text="I didn't catch that. Could you repeat?",
            error="empty assist_query text",
        )

    handler = _ASSIST_QUERY_HANDLER
    if handler is None:
        return _assist_response(
            payload,
            ok=False,
            text="Hermes voice handling is not available right now.",
            error="assist_query handler is not configured",
        )

    try:
        result = handler(payload)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            result = {"text": str(result)}
        response_text = str(result.get("text") or "").strip()
        if not response_text:
            response_text = "I processed that, but did not get a spoken response."
        extra = {
            k: v
            for k, v in result.items()
            if k not in {"type", "ok", "text", "conversation_id", "language", "speech", "error"}
        }
        return _assist_response(
            payload,
            ok=bool(result.get("ok", True)),
            text=response_text,
            error=result.get("error"),
            extra=extra,
        )
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        logger.exception("assist_query failed")
        return _assist_response(
            payload,
            ok=False,
            text="Sorry, Hermes hit an error while processing that.",
            error=str(exc),
        )


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


async def handle_ha_ws_payload_async(payload: dict[str, Any]) -> dict[str, Any]:
    """Async wrapper for payloads that may need a Hermes LLM round-trip."""
    msg_type = str(payload.get("type", "")).strip().lower()
    if msg_type == "assist_query":
        _record_message(msg_type)
        return await handle_assist_query(payload)
    return handle_ha_ws_payload(payload)


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
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._active_connections = 0
        self._total_connections = 0
        self._connections_lock = threading.Lock()
        # Accessed only by this server's event-loop thread. Explicitly closing
        # every socket is required before AppRunner.cleanup(); otherwise aiohttp
        # can wait indefinitely for Home Assistant's long-lived connection.
        self._websockets: set["aiohttp_web.WebSocketResponse"] = set()
        # The aiohttp request task owns any in-flight Assist coroutine. Closing
        # its socket alone does not cancel that coroutine, so unload must cancel
        # and drain these tasks before AppRunner waits for request completion.
        self._request_tasks: set[asyncio.Task[Any]] = set()

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
        """True only when the socket is actually bound and serving.

        ``_started`` is set for both outcomes (the caller must not wait forever),
        so a failed bind — thread still alive inside its cleanup — would otherwise
        report ``running=True`` and hand back a dead server.
        """
        return self._ready.is_set() and self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        """Start the receiver in a daemon thread. Returns False if already running."""
        if self.running:
            return False
        self._stopped.clear()
        # Plugin registration runs inside the owning profile's ContextVar scope.
        # A bare thread would lose that scope and make Assist callbacks resolve
        # the launch profile's model configuration and credentials instead.
        thread_context = contextvars.copy_context()
        self._thread = threading.Thread(
            target=thread_context.run,
            args=(self._run_thread,),
            name="hermes-ha-ws",
            daemon=True,
        )
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
            self._ready.set()
            self._started.set()
            logger.info("Hermes HA WebSocket receiver listening on %s:%s%s", self.host, self.port, self.path)
            loop.run_forever()
        except Exception as exc:
            identity = _probe_receiver(self.host, self.port) if _is_port_conflict(exc) else None
            if identity is not None:
                _log_existing_receiver(identity, self.host, self.port, self.path)
            else:
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
        runner = web.AppRunner(app, shutdown_timeout=SHUTDOWN_TIMEOUT_SECONDS)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        self._runner = runner

    async def _shutdown(self) -> None:
        self._ready.clear()
        sockets = tuple(self._websockets)
        current_task = asyncio.current_task()
        request_tasks = tuple(
            task
            for task in self._request_tasks
            if task is not current_task and not task.done()
        )
        for task in request_tasks:
            task.cancel()
        if request_tasks:
            _done, pending = await asyncio.wait(
                request_tasks, timeout=SHUTDOWN_TIMEOUT_SECONDS
            )
            if pending:
                logger.warning(
                    "Hermes HA WebSocket receiver: %d request task(s) did not "
                    "finish after cancellation",
                    len(pending),
                )
        if sockets:
            close_kwargs = (
                {"code": WSCloseCode.GOING_AWAY, "message": b"receiver shutting down"}
                if WSCloseCode is not None
                else {}
            )
            close_tasks = {
                asyncio.create_task(ws.close(**close_kwargs)) for ws in sockets
            }
            _closed, close_pending = await asyncio.wait(
                close_tasks, timeout=SHUTDOWN_TIMEOUT_SECONDS
            )
            for task in close_pending:
                task.cancel()
            if close_pending:
                logger.warning(
                    "Hermes HA WebSocket receiver: force-closing %d unresponsive "
                    "WebSocket(s)",
                    len(close_pending),
                )
            await asyncio.gather(*close_tasks, return_exceptions=True)
        runner = self._runner
        self._runner = None
        if runner is not None:
            await runner.cleanup()
        self._request_tasks.clear()
        self._websockets.clear()
        with self._connections_lock:
            self._active_connections = 0
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
        request_task = asyncio.current_task()
        if request_task is not None:
            self._request_tasks.add(request_task)
        self._websockets.add(ws)
        self._connection_opened()

        try:
            await ws.send_json({"type": "hello", "ok": True, "service": "hermes-ha-ws"})
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        payload = json.loads(msg.data)
                        if not isinstance(payload, dict):
                            raise ValueError("payload must be a JSON object")
                        response = await handle_ha_ws_payload_async(payload)
                    except Exception as exc:
                        response = {"type": "error", "ok": False, "error": str(exc)}
                    await ws.send_json(response)
                elif msg.type == WSMsgType.ERROR:
                    logger.debug("HA WebSocket closed with error: %s", ws.exception())
                    break
        finally:
            if request_task is not None:
                self._request_tasks.discard(request_task)
            self._websockets.discard(ws)
            self._connection_closed()
        return ws


def _is_port_conflict(exc: BaseException) -> bool:
    """True when the exception is an 'address already in use' bind failure."""
    if getattr(exc, "errno", None) == errno.EADDRINUSE:
        return True
    return "address already in use" in str(exc).lower()


def _probe_hosts(host: str) -> list[str]:
    """Loopback addresses to probe for a receiver bound to ``host``.

    A wildcard bind may be IPv4-only, IPv6-only or dual-stack depending on the
    platform and the socket options, so both loopback addresses are tried; a
    specific host is probed as given.
    """
    if host.strip() in _WILDCARD_HOSTS:
        return ["127.0.0.1", "::1"]
    return [host]


def _health_identity(host: str, port: int, timeout: float) -> Optional[dict[str, Any]]:
    """Return the parsed ``/health`` payload served on ``host:port``, or None.

    The receiver's health route is unauthenticated and states what it is, which
    is the only trustworthy identity signal: an HTTP status is not identity (a
    protected foreign API answers 401, an unrelated upgrade endpoint answers
    426, generic validation answers 400), so the payload's service marker decides
    whether the port belongs to a Hermes receiver.
    """
    connection: Optional[http.client.HTTPConnection] = None
    try:
        connection = http.client.HTTPConnection(host, port, timeout=timeout)
        connection.request("GET", DEFAULT_HEALTH_PATH, headers={"Connection": "close"})
        response = connection.getresponse()
        if response.status != 200:
            return None
        payload = json.loads(response.read(_PROBE_MAX_BYTES).decode("utf-8", "replace"))
    except (OSError, ValueError, http.client.HTTPException):
        return None
    finally:
        if connection is not None:
            try:
                connection.close()
            except OSError:  # pragma: no cover - defensive
                pass
    return payload if isinstance(payload, dict) else None


def _probe_receiver(host: str, port: int, timeout: float = _BIND_PROBE_TIMEOUT) -> Optional[dict[str, Any]]:
    """Return the identity payload of the Hermes receiver serving ``host:port``.

    Any Hermes process can load the plugin and several of them legitimately try
    the same port, so the caller must not bind when this returns a payload — and
    must still report a genuine conflict when it returns None.
    """
    for probe_host in _probe_hosts(host):
        payload = _health_identity(probe_host, port, timeout)
        if payload is not None and payload.get("service") == SERVICE_ID:
            return payload
    return None


def _profile_scope() -> str:
    """Return the active Hermes profile home without requiring Hermes in tests."""
    try:
        get_hermes_home = getattr(importlib.import_module("hermes_constants"), "get_hermes_home")
    except (ImportError, AttributeError):
        home = os.getenv("HERMES_HOME", "")
    else:
        try:
            home = os.fspath(get_hermes_home())
        except Exception:  # pragma: no cover - fail-soft outside Hermes runtime
            home = os.getenv("HERMES_HOME", "")
    return os.path.realpath(os.path.expanduser(home)) if home else ""


def _profile_identity() -> str:
    """Opaque cross-process identity for the active Hermes profile."""
    scope = _profile_scope()
    return hashlib.sha256(scope.encode("utf-8")).hexdigest() if scope else ""


def _module_owner() -> tuple[str, str]:
    """Stable owner boundary: source file plus active Hermes profile."""
    return (os.path.realpath(__file__), _profile_scope())


def _owner_record() -> Optional[dict[str, Any]]:
    """The receiver recorded on ``sys`` by whichever module started it."""
    record = getattr(sys, _PROC_SINGLETON_ATTR, None)
    return record if isinstance(record, dict) else None


def _record_owner(server: "HermesHAWebSocketServer", config: tuple[str, int, str]) -> None:
    setattr(
        sys,
        _PROC_SINGLETON_ATTR,
        {
            "server": server,
            "owner": _module_owner(),
            "config": config,
            "pid": os.getpid(),
        },
    )


def _adoptable_receiver(
    resolved_host: str, resolved_port: int, resolved_path: str
) -> tuple[Optional["HermesHAWebSocketServer"], Optional["HermesHAWebSocketServer"]]:
    """Decide what to do with a receiver another module recorded on ``sys``.

    Returns ``(reuse, stale)``. Local ``_WS_SERVER`` handles reuse before this
    function is called. Therefore a live same-owner record reached here belongs
    to an earlier import and is always stale: even unchanged source was imported
    with a new PluginContext and assist handler, while the old server still calls
    functions in the previous module's globals.
    """
    record = _owner_record()
    if record is None:
        return None, None

    server = record.get("server")
    same_owner = record.get("owner") == _module_owner()
    same_config = record.get("config") == (resolved_host, resolved_port, resolved_path)
    if record.get("pid") == os.getpid() and same_owner and same_config:
        if not getattr(server, "running", False):
            return None, None
        logger.info(
            "Hermes HA WebSocket receiver: %s was reloaded for profile %s — "
            "rebinding it to the new plugin context",
            _module_owner()[0],
            _module_owner()[1] or "<default>",
        )
        return None, server

    if server is not None:
        logger.warning(
            "Hermes HA WebSocket receiver: not reusing the receiver registered by "
            "%s (profile %s, pid %s, %s) — this module is %s (profile %s) with %s",
            record.get("owner", ("?", "?"))[0],
            record.get("owner", ("?", "?"))[1] or "<default>",
            record.get("pid"),
            record.get("config"),
            _module_owner()[0],
            _module_owner()[1] or "<default>",
            (resolved_host, resolved_port, resolved_path),
        )
    return None, None


def _log_existing_receiver(
    identity: dict[str, Any], host: str, port: int, path: str
) -> None:
    """Classify a probed receiver as a duplicate or visible configuration conflict."""
    served_path = identity.get("path")
    served_profile = str(identity.get("profile_id") or "")
    current_profile = _profile_identity()
    same_profile = bool(
        served_profile
        and current_profile
        and hmac.compare_digest(served_profile, current_profile)
    )
    if same_profile and served_path == path:
        logger.info(
            "Hermes HA WebSocket receiver already served on %s:%s%s by "
            "another process for this profile — not binding again",
            host,
            port,
            path,
        )
    elif not same_profile:
        logger.warning(
            "Hermes HA WebSocket receiver: port %s is held by a Hermes receiver "
            "for a different or unidentified profile (serving %s); this profile's "
            "receiver at %s will not start — configure a different HERMES_HA_WS_PORT",
            port,
            served_path,
            path,
        )
    else:
        logger.warning(
            "Hermes HA WebSocket receiver: port %s is held by this profile's Hermes "
            "receiver serving %s instead of %s — not binding again",
            port,
            served_path,
            path,
        )


def start_ws_receiver(host: Optional[str] = None, port: Optional[int] = None, path: Optional[str] = None) -> Optional[HermesHAWebSocketServer]:
    """Start the singleton HA WebSocket receiver if enabled."""
    enabled = str(_profile_env("HERMES_HA_WS_ENABLED", "1") or "").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        logger.info("Hermes HA WebSocket receiver disabled by HERMES_HA_WS_ENABLED")
        return None
    if not AIOHTTP_AVAILABLE:
        logger.warning("Hermes HA WebSocket receiver unavailable: aiohttp is not installed")
        return None

    resolved_host = host if host is not None else str(
        _profile_env("HERMES_HA_WS_HOST", DEFAULT_WS_HOST) or DEFAULT_WS_HOST
    )
    resolved_port_value: int | str = (
        port
        if port is not None
        else (_profile_env("HERMES_HA_WS_PORT", str(DEFAULT_WS_PORT)) or str(DEFAULT_WS_PORT))
    )
    resolved_port = int(resolved_port_value)
    resolved_path = path if path is not None else str(
        _profile_env("HERMES_HA_WS_PATH", DEFAULT_WS_PATH) or DEFAULT_WS_PATH
    )

    global _WS_SERVER
    with _WS_LOCK:
        if _WS_SERVER and _WS_SERVER.running:
            return _WS_SERVER

        reuse, stale = _adoptable_receiver(resolved_host, resolved_port, resolved_path)
        if reuse is not None:
            _WS_SERVER = reuse
            return reuse
        if stale is not None:
            # Release the port so the reloaded code can take it over.
            stale.stop()

        identity = _probe_receiver(resolved_host, resolved_port)
        if identity is not None:
            _log_existing_receiver(
                identity, resolved_host, resolved_port, resolved_path
            )
            return None

        _WS_SERVER = HermesHAWebSocketServer(resolved_host, resolved_port, resolved_path)
        _WS_SERVER.start()
        if _WS_SERVER.running:
            _record_owner(_WS_SERVER, (resolved_host, resolved_port, resolved_path))
            return _WS_SERVER
        return None


def stop_ws_receiver() -> None:
    """Stop the singleton receiver."""
    global _ASSIST_QUERY_HANDLER, _WS_SERVER
    with _WS_LOCK:
        server = _WS_SERVER
        _WS_SERVER = None
        # Release the PluginContext captured by register(); a disabled or
        # unloaded plugin must not leave stale model access reachable.
        _ASSIST_QUERY_HANDLER = None
    record = _owner_record()
    if server is not None and record is not None and record.get("server") is server:
        try:
            delattr(sys, _PROC_SINGLETON_ATTR)
        except AttributeError:  # pragma: no cover - defensive
            pass
    if server is not None:
        server.stop()
