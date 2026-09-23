"""Bind idempotency, receiver identity and owner boundaries.

Every Hermes process that loads this plugin (the gateway, every CLI session, the
dashboard) re-imports the module with fresh globals and calls ``register()``, so
several of them legitimately race for the same port. Only the first one may bind;
the others must stay quiet about a port a Hermes receiver already serves — and
must still shout about a port somebody else's service holds.

Identity is decided by the receiver's own unauthenticated ``/health`` payload
(``service == "hermes-ha-ws"``), never by an HTTP status: a protected foreign API
answers 401, an unrelated upgrade endpoint answers 426, generic validation
answers 400.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import logging
import multiprocessing
import os
import socket
import sys
import threading
import time
import types
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

import pytest
from aiohttp import ClientSession, WSServerHandshakeError

from plugins.voice_stack import ws_receiver

MODULE_PATH = Path(ws_receiver.__file__).resolve()
WS_PATH = ws_receiver.DEFAULT_WS_PATH

requires_aiohttp = pytest.mark.skipif(
    not ws_receiver.AIOHTTP_AVAILABLE,
    reason="aiohttp is not a dev extra; the receiver only serves with it installed",
)


# --------------------------------------------------------------------------- #
# Doubles                                                                     #
# --------------------------------------------------------------------------- #


class _FakeService:
    """A minimal HTTP service holding a port, with a scriptable responder.

    ``responder(target) -> (status, payload)`` decides what each request gets,
    so a test can model both a foreign API and another Hermes receiver.
    """

    def __init__(
        self,
        responder: Callable[[str], tuple[int, Optional[dict[str, Any]]]],
        *,
        family: int = socket.AF_INET,
        host: str = "127.0.0.1",
    ) -> None:
        self._responder = responder
        self._sock = socket.socket(family, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, 0))
        self._sock.listen(8)
        bound = self._sock.getsockname()
        self.host, self.port = str(bound[0]), int(bound[1])
        self._stopped = False
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._stopped:
            try:
                conn, _ = self._sock.accept()
            except OSError:  # pragma: no cover - closed while accepting
                return
            with conn:
                try:
                    request = conn.recv(4096).decode("latin-1", "replace")
                    parts = request.split(" ", 2)
                    target = parts[1] if len(parts) > 1 else "/"
                    status, payload = self._responder(target)
                    if payload is None:
                        conn.sendall(
                            f"HTTP/1.1 {status} X\r\nContent-Length: 0\r\n"
                            "Connection: close\r\n\r\n".encode()
                        )
                    else:
                        body = json.dumps(payload).encode()
                        conn.sendall(
                            (
                                f"HTTP/1.1 {status} X\r\n"
                                "Content-Type: application/json\r\n"
                                f"Content-Length: {len(body)}\r\n"
                                "Connection: close\r\n\r\n"
                            ).encode()
                            + body
                        )
                except OSError:  # pragma: no cover - client went away
                    pass

    def close(self) -> None:
        self._stopped = True
        try:
            self._sock.close()
        except OSError:  # pragma: no cover - already closed
            pass
        self._thread.join(timeout=5)


def _identity_responder(
    path: str = WS_PATH, *, include_profile: bool = True
) -> Callable[[str], tuple[int, Optional[dict[str, Any]]]]:
    """Answers like this receiver's /health route."""

    def responder(target: str) -> tuple[int, Optional[dict[str, Any]]]:
        if target.split("?")[0] != ws_receiver.DEFAULT_HEALTH_PATH:
            return 404, None
        payload = {
            "type": "status",
            "service": ws_receiver.SERVICE_ID,
            "running": True,
            "host": "0.0.0.0",
            "port": 0,
            "path": path,
        }
        if include_profile:
            payload["profile_id"] = ws_receiver._profile_identity()
        return 200, payload

    return responder


def _protected_api_responder(target: str) -> tuple[int, Optional[dict[str, Any]]]:
    """A foreign, token-protected API: 401 on everything, including /health."""
    return 401, None


def _foreign_health_responder(target: str) -> tuple[int, Optional[dict[str, Any]]]:
    """Somebody else's service that does expose a /health of its own."""
    return 200, {"service": "not-hermes", "path": WS_PATH}


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@pytest.fixture(autouse=True)
def _clean_receiver() -> Iterator[None]:
    """Never leak a started receiver (or its sys record) into another test."""
    yield
    record = getattr(sys, ws_receiver._PROC_SINGLETON_ATTR, None)
    if isinstance(record, dict):
        server = record.get("server")
        if server is not None:
            server.stop()
        delattr(sys, ws_receiver._PROC_SINGLETON_ATTR)
    ws_receiver._WS_SERVER = None


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No ambient receiver config leaks into a test's expectations."""
    monkeypatch.setenv("HERMES_HA_WS_ENABLED", "1")
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profile"))
    monkeypatch.delenv("HERMES_HA_WS_TOKEN", raising=False)


def _load_module(name: str, path: Path = MODULE_PATH):
    """Load the receiver module again, as Hermes does for every process."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


async def _assist_response_text(port: int, path: str) -> str:
    """Send one real Assist query to the live receiver."""
    async with ClientSession() as session:
        async with session.ws_connect(f"http://127.0.0.1:{port}{path}") as ws:
            await ws.receive_json()  # hello
            await ws.send_json(
                {
                    "type": "assist_query",
                    "text": "Which plugin context is live?",
                    "conversation_id": "reload-test",
                }
            )
            response = await ws.receive_json()
            return str(response["text"])


def _receiver_process(
    profile_home: str,
    port: int,
    hold_open: bool,
    stop_event: Any,
    result_queue: Any,
) -> None:
    """Run one independently scoped receiver process for ownership tests."""
    os.environ["HERMES_HOME"] = profile_home
    os.environ["HERMES_HA_WS_ENABLED"] = "1"
    os.environ.pop("HERMES_HA_WS_TOKEN", None)
    module = _load_module(f"ws_receiver_process_{os.getpid()}")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    module.logger.addHandler(handler)
    module.logger.setLevel(logging.INFO)
    try:
        server = module.start_ws_receiver(
            host="127.0.0.1", port=port, path=WS_PATH
        )
        result_queue.put(
            {"started": server is not None and server.running, "log": stream.getvalue()}
        )
        if server is not None and hold_open:
            stop_event.wait(10)
        if server is not None:
            server.stop()
    finally:
        module.logger.removeHandler(handler)


# --------------------------------------------------------------------------- #
# Identity: the /health marker decides, not the HTTP status                    #
# --------------------------------------------------------------------------- #


def test_probe_requires_the_service_marker() -> None:
    service = _FakeService(_identity_responder())
    try:
        identity = ws_receiver._probe_receiver("127.0.0.1", service.port)
    finally:
        service.close()

    assert identity is not None
    assert identity["service"] == ws_receiver.SERVICE_ID


def test_probe_ignores_a_protected_foreign_api() -> None:
    """A 401 is not identity: a foreign protected API answers 401 too."""
    service = _FakeService(_protected_api_responder)
    try:
        assert ws_receiver._probe_receiver("127.0.0.1", service.port) is None
    finally:
        service.close()


def test_probe_ignores_a_foreign_health_endpoint() -> None:
    service = _FakeService(_foreign_health_responder)
    try:
        assert ws_receiver._probe_receiver("127.0.0.1", service.port) is None
    finally:
        service.close()


def test_probe_is_none_when_nothing_listens(free_port: int) -> None:
    assert ws_receiver._probe_receiver("127.0.0.1", free_port) is None


def test_probe_hosts_covers_both_loopbacks_for_a_wildcard() -> None:
    assert ws_receiver._probe_hosts("0.0.0.0") == ["127.0.0.1", "::1"]
    assert ws_receiver._probe_hosts("::") == ["127.0.0.1", "::1"]
    assert ws_receiver._probe_hosts("192.168.31.5") == ["192.168.31.5"]


def test_probe_finds_an_ipv6_only_receiver_on_a_wildcard_bind() -> None:
    try:
        service = _FakeService(_identity_responder(), family=socket.AF_INET6, host="::1")
    except OSError:  # pragma: no cover - no IPv6 in this environment
        pytest.skip("IPv6 loopback is unavailable")
    try:
        identity = ws_receiver._probe_receiver("::", service.port)
    finally:
        service.close()

    assert identity is not None
    assert identity["service"] == ws_receiver.SERVICE_ID


def test_is_port_conflict_matches_both_errno_and_message() -> None:
    assert ws_receiver._is_port_conflict(OSError(98, "Address already in use"))
    assert ws_receiver._is_port_conflict(
        OSError(
            "error while attempting to bind on address ('0.0.0.0', 7860): "
            "address already in use"
        )
    )
    assert not ws_receiver._is_port_conflict(OSError(99, "Cannot assign requested address"))


@requires_aiohttp
def test_profile_scope_overrides_launch_receiver_config_and_token(
    free_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A routed profile must not read receiver settings or auth from os.environ."""
    module = _load_module("ws_receiver_scoped_config")
    scoped_values = {
        "HERMES_HA_WS_ENABLED": "1",
        "HERMES_HA_WS_HOST": "127.0.0.1",
        "HERMES_HA_WS_PORT": str(free_port),
        "HERMES_HA_WS_PATH": WS_PATH,
        "HERMES_HA_WS_TOKEN": "owner-profile-token",
    }
    real_import_module = module.importlib.import_module

    def scoped_import(name: str, *args: Any, **kwargs: Any):
        if name == "agent.secret_scope":
            return types.SimpleNamespace(
                get_secret=lambda key, default=None: scoped_values.get(key, default)
            )
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(module.importlib, "import_module", scoped_import)
    monkeypatch.setenv("HERMES_HA_WS_ENABLED", "0")
    monkeypatch.setenv("HERMES_HA_WS_PORT", str(free_port + 1))
    monkeypatch.setenv("HERMES_HA_WS_TOKEN", "launch-profile-token")

    server = module.start_ws_receiver()
    assert server is not None and server.running
    assert (server.host, server.port, server.path) == (
        "127.0.0.1",
        free_port,
        WS_PATH,
    )

    async def handshake_status(token: str) -> int:
        headers = {"Authorization": f"Bearer {token}"}
        async with ClientSession() as session:
            try:
                async with session.ws_connect(
                    f"http://127.0.0.1:{free_port}{WS_PATH}", headers=headers
                ) as client:
                    await client.receive_json()
                    return 101
            except WSServerHandshakeError as exc:
                return exc.status

    try:
        assert asyncio.run(handshake_status("owner-profile-token")) == 101
        assert asyncio.run(handshake_status("launch-profile-token")) == 401
    finally:
        server.stop()


def test_profile_scope_failure_does_not_fall_back_to_launch_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fail-closed Hermes resolver error must not expose os.environ credentials."""
    module = _load_module("ws_receiver_scoped_failure")
    real_import_module = module.importlib.import_module

    class ScopeError(RuntimeError):
        pass

    def get_secret(_name: str, _default: Optional[str] = None) -> Optional[str]:
        raise ScopeError("missing profile scope")

    def failing_import(name: str, *args: Any, **kwargs: Any):
        if name == "agent.secret_scope":
            return types.SimpleNamespace(get_secret=get_secret)
        return real_import_module(name, *args, **kwargs)

    monkeypatch.setattr(module.importlib, "import_module", failing_import)
    monkeypatch.setenv("HERMES_HA_WS_TOKEN", "launch-profile-token")

    with pytest.raises(ScopeError, match="missing profile scope"):
        module._configured_token()


# --------------------------------------------------------------------------- #
# Liveness                                                                    #
# --------------------------------------------------------------------------- #


@requires_aiohttp
def test_running_requires_a_completed_bind() -> None:
    """``_started`` alone must never report a live receiver.

    A failed bind sets ``_started`` too (the caller must not wait forever), so
    judging on it handed back a dead server while the thread was still cleaning
    up.
    """
    server = ws_receiver.HermesHAWebSocketServer("127.0.0.1", 0, WS_PATH)
    assert not server.running
    server._started.set()  # the startup attempt finished — it failed
    assert not server.running
    server._ready.set()  # bound... but there is no live thread either
    assert not server.running


@requires_aiohttp
def test_stop_closes_an_active_client_and_terminates_the_thread(
    free_port: int,
) -> None:
    """Unload must not orphan Home Assistant's long-lived connection."""
    module = _load_module("ws_receiver_active_unload")
    server = module.start_ws_receiver(
        host="127.0.0.1", port=free_port, path=WS_PATH
    )
    assert server is not None and server.running

    async def stop_while_connected():
        async with ClientSession() as session:
            ws = await session.ws_connect(
                f"http://127.0.0.1:{free_port}{WS_PATH}"
            )
            await ws.receive_json()
            assert server.active_connections == 1
            started = time.monotonic()
            await asyncio.to_thread(module.stop_ws_receiver)
            elapsed = time.monotonic() - started
            close_message = await asyncio.wait_for(ws.receive(), timeout=2)
            await ws.close()
            return elapsed, close_message.type, ws.closed

    elapsed, close_type, client_closed = asyncio.run(stop_while_connected())

    assert elapsed < 2
    assert close_type in {
        ws_receiver.WSMsgType.CLOSE,
        ws_receiver.WSMsgType.CLOSED,
        ws_receiver.WSMsgType.CLOSING,
    }
    assert client_closed
    assert not server.running
    assert server._thread is not None and not server._thread.is_alive()


@requires_aiohttp
def test_stop_cancels_an_in_flight_assist_request(
    free_port: int,
) -> None:
    """A model request must not retain the old PluginContext after unload."""
    module = _load_module("ws_receiver_in_flight_unload")
    handler_started = threading.Event()
    handler_cancelled = threading.Event()

    async def blocked_handler(_payload: dict[str, Any]) -> dict[str, Any]:
        handler_started.set()
        try:
            await asyncio.Event().wait()
            raise AssertionError("blocked handler unexpectedly resumed")
        finally:
            handler_cancelled.set()

    module.set_assist_query_handler(blocked_handler)
    server = module.start_ws_receiver(
        host="127.0.0.1", port=free_port, path=WS_PATH
    )
    assert server is not None and server.running

    async def stop_during_request():
        async with ClientSession() as session:
            ws = await session.ws_connect(
                f"http://127.0.0.1:{free_port}{WS_PATH}"
            )
            await ws.receive_json()
            await ws.send_json(
                {
                    "type": "assist_query",
                    "text": "wait forever",
                    "conversation_id": "in-flight-stop",
                }
            )
            assert await asyncio.to_thread(handler_started.wait, 2)
            started = time.monotonic()
            await asyncio.to_thread(module.stop_ws_receiver)
            elapsed = time.monotonic() - started
            close_message = await asyncio.wait_for(ws.receive(), timeout=2)
            await ws.close()
            return elapsed, close_message.type

    elapsed, close_type = asyncio.run(stop_during_request())

    assert elapsed < 2
    assert handler_cancelled.wait(1)
    assert close_type in {
        ws_receiver.WSMsgType.CLOSE,
        ws_receiver.WSMsgType.CLOSED,
        ws_receiver.WSMsgType.CLOSING,
    }
    assert not server.running
    assert server.active_connections == 0
    assert server._thread is not None and not server._thread.is_alive()


@requires_aiohttp
def test_reset_during_hello_does_not_leak_connection_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A peer reset during the first write still runs connection cleanup."""

    class ResetOnHelloWebSocket:
        async def prepare(self, _request: Any) -> None:
            return None

        async def send_json(self, _payload: dict[str, Any]) -> None:
            raise ConnectionResetError("peer reset before hello")

    monkeypatch.setattr(
        ws_receiver.web,
        "WebSocketResponse",
        lambda **_kwargs: ResetOnHelloWebSocket(),
    )
    server = ws_receiver.HermesHAWebSocketServer("127.0.0.1", 0, WS_PATH)
    request: Any = types.SimpleNamespace(headers={})

    with pytest.raises(ConnectionResetError, match="peer reset before hello"):
        asyncio.run(server._handle_ws(request))

    assert not server._websockets
    assert not server._request_tasks
    assert server.active_connections == 0
    assert server.total_connections == 1


# --------------------------------------------------------------------------- #
# Owner boundaries: reuse, reload and other profiles                          #
# --------------------------------------------------------------------------- #


@requires_aiohttp
def test_repeated_start_in_same_module_reuses_the_receiver(free_port: int) -> None:
    module = _load_module("ws_receiver_repeated_start")
    first = module.start_ws_receiver(host="127.0.0.1", port=free_port, path=WS_PATH)
    assert first is not None and first.running
    try:
        second = module.start_ws_receiver(host="127.0.0.1", port=free_port, path=WS_PATH)
        assert second is first
    finally:
        first.stop()


@requires_aiohttp
def test_reload_rebinds_and_uses_the_new_assist_handler(
    free_port: int, caplog: pytest.LogCaptureFixture
) -> None:
    """A reload must serve the new context even when source bytes are unchanged.

    Hermes force-reload evicts and freshly imports the module after creating a
    new PluginContext. Reusing the old receiver would leave its bound methods
    resolving the previous module's assist handler.
    """
    first_module = _load_module("ws_receiver_stale_first")
    first_module.set_assist_query_handler(lambda _payload: {"text": "old context"})
    first = first_module.start_ws_receiver(host="127.0.0.1", port=free_port, path=WS_PATH)
    assert first is not None and first.running

    second = None

    try:
        second_module = _load_module("ws_receiver_stale_second")
        second_module.set_assist_query_handler(lambda _payload: {"text": "new context"})

        async def reload_with_open_connection():
            async with ClientSession() as session:
                old_ws = await session.ws_connect(
                    f"http://127.0.0.1:{free_port}{WS_PATH}"
                )
                await old_ws.receive_json()  # hello from the old module
                replacement = await asyncio.to_thread(
                    second_module.start_ws_receiver,
                    "127.0.0.1",
                    free_port,
                    WS_PATH,
                )
                close_message = await asyncio.wait_for(old_ws.receive(), timeout=2)
                assert close_message.type in {
                    ws_receiver.WSMsgType.CLOSE,
                    ws_receiver.WSMsgType.CLOSED,
                    ws_receiver.WSMsgType.CLOSING,
                }
                await old_ws.close()
            text = await _assist_response_text(free_port, WS_PATH)
            return replacement, text

        with caplog.at_level(logging.INFO, logger=second_module.__name__):
            second, response_text = asyncio.run(reload_with_open_connection())

        assert second is not None and second is not first
        assert second.running
        assert not first.running
        assert first._thread is not None and not first._thread.is_alive()
        assert "rebinding" in caplog.text
        assert response_text == "new context"
    finally:
        first.stop()
        if second is not None:
            second.stop()


@requires_aiohttp
def test_receiver_thread_preserves_the_owner_context(
    free_port: int,
) -> None:
    """Assist callbacks must run in the profile scope that started the server."""
    active_profile = ContextVar("test_receiver_profile", default="launch-profile")
    token = active_profile.set("named-profile")
    module = _load_module("ws_receiver_profile_context")
    module.set_assist_query_handler(
        lambda _payload: {"text": active_profile.get()}
    )
    server = module.start_ws_receiver(
        host="127.0.0.1", port=free_port, path=WS_PATH
    )
    assert server is not None and server.running
    active_profile.reset(token)

    try:
        assert active_profile.get() == "launch-profile"
        assert asyncio.run(_assist_response_text(free_port, WS_PATH)) == "named-profile"
    finally:
        server.stop()


@requires_aiohttp
def test_another_profile_module_does_not_adopt_the_receiver(
    tmp_path: Path,
    free_port: int,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin loaded from another profile keeps its hands off.

    It must not reuse — or stop — a receiver another profile's module started.
    """
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profiles" / "a"))
    first_module = _load_module("ws_receiver_profile_a")
    first = first_module.start_ws_receiver(host="127.0.0.1", port=free_port, path=WS_PATH)
    assert first is not None and first.running

    try:
        # Multiplex profiles can load the same project/bundled source path under
        # different profile scopes. The profile home, not just __file__, must
        # keep the second module from stopping or adopting the first receiver.
        monkeypatch.setenv("HERMES_HOME", str(tmp_path / "profiles" / "b"))
        other_module = _load_module("ws_receiver_profile_b")
        with caplog.at_level(logging.INFO, logger=other_module.__name__):
            adopted = other_module.start_ws_receiver(
                host="127.0.0.1", port=free_port, path=WS_PATH
            )

        assert adopted is None
        assert first.running
        assert "not reusing the receiver" in caplog.text
    finally:
        first.stop()


@requires_aiohttp
def test_start_is_quiet_when_another_process_serves_the_port(
    free_port: int, caplog: pytest.LogCaptureFixture
) -> None:
    serving_module = _load_module("ws_receiver_other_process")
    serving = serving_module.start_ws_receiver(host="127.0.0.1", port=free_port, path=WS_PATH)
    assert serving is not None and serving.running
    # Another process's record is not on our sys, so drop ours to model that.
    delattr(sys, ws_receiver._PROC_SINGLETON_ATTR)

    try:
        other_module = _load_module("ws_receiver_third")
        with caplog.at_level(logging.INFO, logger=other_module.__name__):
            started = other_module.start_ws_receiver(
                host="127.0.0.1", port=free_port, path=WS_PATH
            )

        assert started is None
        assert "already served" in caplog.text
        assert "failed to start" not in caplog.text
    finally:
        serving.stop()


@requires_aiohttp
def test_cross_process_probe_distinguishes_same_and_other_profiles(
    tmp_path: Path, free_port: int
) -> None:
    """Only another process for the same profile is a harmless duplicate."""
    process_context = multiprocessing.get_context("spawn")
    stop_event = process_context.Event()
    results = process_context.Queue()
    profile_a = str(tmp_path / "profiles" / "a")
    profile_b = str(tmp_path / "profiles" / "b")
    owner = process_context.Process(
        target=_receiver_process,
        args=(profile_a, free_port, True, stop_event, results),
    )
    owner.start()
    try:
        owner_result = results.get(timeout=10)
        assert owner_result["started"] is True

        same_profile = process_context.Process(
            target=_receiver_process,
            args=(profile_a, free_port, False, stop_event, results),
        )
        same_profile.start()
        same_result = results.get(timeout=10)
        same_profile.join(timeout=10)
        assert same_profile.exitcode == 0
        assert same_result["started"] is False
        assert "another process for this profile" in same_result["log"]

        other_profile = process_context.Process(
            target=_receiver_process,
            args=(profile_b, free_port, False, stop_event, results),
        )
        other_profile.start()
        other_result = results.get(timeout=10)
        other_profile.join(timeout=10)
        assert other_profile.exitcode == 0
        assert other_result["started"] is False
        assert "different or unidentified profile" in other_result["log"]
        assert "configure a different HERMES_HA_WS_PORT" in other_result["log"]
    finally:
        stop_event.set()
        owner.join(timeout=10)
        if owner.is_alive():  # pragma: no cover - defensive child cleanup
            owner.terminate()
            owner.join(timeout=5)
    assert owner.exitcode == 0


@requires_aiohttp
def test_start_warns_when_a_foreign_service_holds_the_port(
    free_port: int, caplog: pytest.LogCaptureFixture
) -> None:
    service = _FakeService(_protected_api_responder)
    try:
        with caplog.at_level(logging.INFO, logger=ws_receiver.__name__):
            started = ws_receiver.start_ws_receiver(
                host="127.0.0.1", port=service.port, path=WS_PATH
            )
    finally:
        service.close()

    assert not started
    assert "failed to start" in caplog.text


@requires_aiohttp
def test_start_warns_when_a_hermes_receiver_serves_another_path(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Same receiver, different config: quiet is wrong, the port is not ours to use."""
    service = _FakeService(_identity_responder(path="/api/other/ws"))
    try:
        with caplog.at_level(logging.INFO, logger=ws_receiver.__name__):
            started = ws_receiver.start_ws_receiver(
                host="127.0.0.1", port=service.port, path=WS_PATH
            )
    finally:
        service.close()

    assert started is None
    assert "instead of" in caplog.text


@requires_aiohttp
def test_start_warns_when_receiver_health_has_no_profile_identity(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An older or unidentified receiver must not suppress a profile conflict."""
    service = _FakeService(_identity_responder(include_profile=False))
    try:
        with caplog.at_level(logging.INFO, logger=ws_receiver.__name__):
            started = ws_receiver.start_ws_receiver(
                host="127.0.0.1", port=service.port, path=WS_PATH
            )
    finally:
        service.close()

    assert started is None
    assert "different or unidentified profile" in caplog.text


@requires_aiohttp
@pytest.mark.parametrize("token", [None, "secret-token"])
def test_probe_reads_identity_in_both_token_modes(
    token: Optional[str], free_port: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The health route is the identity source and is not token protected."""
    if token is None:
        monkeypatch.delenv("HERMES_HA_WS_TOKEN", raising=False)
    else:
        monkeypatch.setenv("HERMES_HA_WS_TOKEN", token)

    module = _load_module(f"ws_receiver_token_{token is not None}")
    server = module.start_ws_receiver(host="127.0.0.1", port=free_port, path=WS_PATH)
    assert server is not None and server.running
    try:
        identity = module._probe_receiver("127.0.0.1", free_port)
        assert identity is not None
        assert identity["service"] == module.SERVICE_ID
        assert identity["auth_required"] is (token is not None)
    finally:
        server.stop()