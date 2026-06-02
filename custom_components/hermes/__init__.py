"""Home Assistant custom integration: Hermes Voice Assistant.

Connects Home Assistant to a running Hermes Agent instance via WebSocket.
Provides:
- Config flow for HA URL + token
- WebSocket-backed entity-state push to Hermes
- Event forwarding (entity state changes → Hermes context)
- Service registration (expose HA services to Hermes tool calling)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER, CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL, CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE, CONF_TTS_VOICE, DEFAULT_TTS_VOICE, CONF_STT_ENGINE, DEFAULT_STT_ENGINE, CONF_STT_MODEL, DEFAULT_STT_MODEL, CONF_WAKE_WORD_ENGINE, DEFAULT_WAKE_WORD_ENGINE, CONF_WAKE_WORD, DEFAULT_WAKE_WORD, CONF_MEDIA_PLAYER, DEFAULT_MEDIA_PLAYER, normalize_list, normalize_wake_word, WS_TYPE_ASSIST_QUERY, WS_TYPE_ASSIST_RESPONSE, WS_TYPE_HERMES_EVENT, WS_TYPE_STATE_ACK, WS_TYPE_STATE_CHANGED
from .frontend import async_register_resources as _register_frontend

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.CONVERSATION]

# Minimum interval between state-change pushes (seconds)
_PUSH_INTERVAL = timedelta(seconds=0.2)
_LAST_PUSH: dict[str, float] = {}


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the Hermes integration via configuration.yaml (legacy)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hermes from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    url = entry.data.get(CONF_URL, "http://localhost:8123")
    token = entry.data.get(CONF_TOKEN, "")
    options = entry.options or {}
    entity_filter = normalize_list(options.get(CONF_ENTITY_FILTER, entry.data.get(CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER)))
    verify_ssl = options.get(CONF_VERIFY_SSL, entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))

    bridge = HermesBridge(
        hass,
        url,
        token,
        entity_filter,
        verify_ssl,
        tts_engine=options.get(CONF_TTS_ENGINE, entry.data.get(CONF_TTS_ENGINE, DEFAULT_TTS_ENGINE)),
        tts_voice=options.get(CONF_TTS_VOICE, entry.data.get(CONF_TTS_VOICE, DEFAULT_TTS_VOICE)),
        stt_engine=options.get(CONF_STT_ENGINE, entry.data.get(CONF_STT_ENGINE, DEFAULT_STT_ENGINE)),
        stt_model=options.get(CONF_STT_MODEL, entry.data.get(CONF_STT_MODEL, DEFAULT_STT_MODEL)),
        wake_word_engine=options.get(CONF_WAKE_WORD_ENGINE, entry.data.get(CONF_WAKE_WORD_ENGINE, DEFAULT_WAKE_WORD_ENGINE)),
        wake_word=options.get(CONF_WAKE_WORD, entry.data.get(CONF_WAKE_WORD, DEFAULT_WAKE_WORD)),
        media_player_entity=options.get(CONF_MEDIA_PLAYER, entry.data.get(CONF_MEDIA_PLAYER, DEFAULT_MEDIA_PLAYER)),
    )
    hass.data[DOMAIN][entry.entry_id] = bridge

    # Connect WebSocket to Hermes Agent
    await bridge.async_connect()

    # Register state-change listener. Home Assistant does not accept None as
    # entity_ids; when no filter is configured, listen for all state_changed
    # events directly on the event bus.
    if entity_filter:
        entry.async_on_unload(
            async_track_state_change_event(
                hass,
                entity_filter,
                bridge.on_state_change,
            )
        )
    else:
        entry.async_on_unload(hass.bus.async_listen("state_changed", bridge.on_state_change))

    # Register HA services exposed to Hermes
    await bridge.async_register_services()

    # Register HermesActionBar Lovelace card resource
    await _register_frontend(hass)

    # Forward setup to supported entity platforms.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    _LOGGER.info("Hermes integration set up — URL: %s, entities tracked: %d",
                 url, len(entity_filter))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    bridge: HermesBridge | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if bridge:
        await bridge.async_shutdown()
    if not hass.data.get(DOMAIN):
        from .services import async_unregister_services
        async_unregister_services(hass)
    return unload_ok


class HermesBridge:
    """Bidirectional bridge between Home Assistant and a running Hermes Agent.

    Responsibilities:
    - Push entity state changes to Hermes (via Hermes WebSocket)
    - Expose HA services so Hermes tooling can discover them
    - Accept command requests from Hermes (via HA service calls)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        hermes_url: str,
        hermes_token: str,
        entity_filter: list[str],
        verify_ssl: bool = True,
        tts_engine: str = DEFAULT_TTS_ENGINE,
        tts_voice: str = DEFAULT_TTS_VOICE,
        stt_engine: str = DEFAULT_STT_ENGINE,
        stt_model: str = DEFAULT_STT_MODEL,
        wake_word_engine: str = DEFAULT_WAKE_WORD_ENGINE,
        wake_word: str | list[str] = DEFAULT_WAKE_WORD,
        media_player_entity: str = DEFAULT_MEDIA_PLAYER,
    ) -> None:
        self.hass = hass
        self.hermes_url = hermes_url.rstrip("/")
        self.hermes_token = hermes_token
        self.entity_filter = entity_filter
        self.verify_ssl = verify_ssl
        self.tts_engine = tts_engine
        self.tts_voice = tts_voice
        self.stt_engine = stt_engine
        self.stt_model = stt_model
        self.wake_word_engine = wake_word_engine
        self.wake_word = normalize_wake_word(wake_word)
        self.media_player_entity = media_player_entity
        self._session: Any = None
        self._ws: Any = None
        self._connected = False
        self._pending: list[dict[str, Any]] = []
        self._start_time = time.monotonic()
        self._total_interactions = 0
        self._total_errors = 0
        self._voice_ready = False
        self._reader_task: asyncio.Task | None = None
        # Map of conversation_id → asyncio.Future for routing Hermes responses
        self._pending_queries: dict[str, asyncio.Future] = {}

    @property
    def connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # State change → Hermes
    # ------------------------------------------------------------------

    async def on_state_change(self, event: Any) -> None:
        """Forward state change events to Hermes (rate-limited)."""
        entity_id = event.data.get("entity_id", "")
        if not entity_id:
            return

        # Rate limit per entity
        now = time.monotonic()
        last = _LAST_PUSH.get(entity_id, 0)
        if now - last < _PUSH_INTERVAL.total_seconds():
            return
        _LAST_PUSH[entity_id] = now

        new_state = event.data.get("new_state")
        if new_state is None:
            return

        payload = {
            "type": WS_TYPE_STATE_CHANGED,
            "entity_id": entity_id,
            "state": new_state.state,
            "attributes": dict(new_state.attributes),
            "last_changed": str(new_state.last_changed) if new_state.last_changed else None,
        }

        if self._connected and self._ws:
            try:
                await self._ws.send_json(payload)
            except Exception:
                _LOGGER.debug("Hermes WebSocket send failed — queuing")
                self._pending.append(payload)
        else:
            self._pending.append(payload)
            # Cap pending queue
            if len(self._pending) > 1000:
                self._pending = self._pending[-500:]

    # ------------------------------------------------------------------
    # HA service registration (exposed to Hermes)
    # ------------------------------------------------------------------

    async def async_register_services(self) -> None:
        """Register HA services that Hermes can call.

        Exposes ``hermes_command`` and ``voice_settings`` services
        so Hermes tools can control HA via its native WebSocket path
        instead of going through REST API.
        """
        from .services import async_register_services as _svc
        await _svc(self.hass)

    # ------------------------------------------------------------------
    # WebSocket lifecycle
    # ------------------------------------------------------------------

    async def async_connect(self) -> None:
        """Connect to Hermes Agent WebSocket."""
        import ssl as _ssl

        ssl_context: _ssl.SSLContext | None = None
        if not self.verify_ssl:
            ssl_context = _ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = _ssl.CERT_NONE
            if self.hermes_token:
                _LOGGER.warning(
                    "Hermes token configured with verify_ssl=False — "
                    "token will be sent over plaintext"
                )

        # Cancel any previous reader task before creating a new connection
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass

        try:
            self._session = aiohttp.ClientSession()
            headers = {}
            if self.hermes_token:
                headers["Authorization"] = f"Bearer {self.hermes_token}"
            # Token in query param removed: use Authorization header instead
            url = f"{self.hermes_url}/api/hermes/ws"
            self._ws = await self._session.ws_connect(
                url,
                headers=headers,
                ssl=ssl_context,
                heartbeat=30,
            )
            # Start background reader; set _connected only after reader launches
            self._reader_task = asyncio.create_task(self._ws_reader())
            self._connected = True
            _LOGGER.info("Connected to Hermes WebSocket at %s", self.hermes_url)
            # Flush any pending messages queued while disconnected
            await _flush_pending(self._ws, self._pending)
        except Exception as exc:
            _LOGGER.warning("Failed to connect to Hermes WebSocket: %s", exc)
            self._connected = False


    async def _ws_reader(self) -> None:
        """Background task: continuously drain messages from Hermes WebSocket.

        Keeps the aiohttp heartbeat handling alive and routes
        conversation responses back to pending query futures.
        """
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        _LOGGER.debug("Hermes WS: unparseable message")
                        continue
                    msg_type = data.get("type", "")
                    if msg_type == WS_TYPE_ASSIST_RESPONSE:
                        conv_id = data.get("conversation_id", "")
                        _LOGGER.debug(
                            "Hermes WS: received assist_response conv_id=%s", conv_id
                        )
                        future = self._pending_queries.pop(conv_id, None)
                        if future and not future.done():
                            future.set_result(data)
                    elif msg_type in (WS_TYPE_HERMES_EVENT, WS_TYPE_STATE_ACK):
                        pass  # informational; no routing needed
                    else:
                        _LOGGER.debug("Hermes WS: unhandled type=%s", msg_type)
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    _LOGGER.info("Hermes WebSocket closed by server")
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    _LOGGER.warning("Hermes WebSocket error")
                    break
        except asyncio.CancelledError:
            _LOGGER.debug("Hermes WS reader cancelled")
        except Exception as exc:
            _LOGGER.warning("Hermes WS reader exception: %s", exc)
        finally:
            self._connected = False
            # Resolve any pending futures as failed
            for future in self._pending_queries.values():
                if not future.done():
                    future.set_exception(ConnectionError("Hermes WebSocket disconnected"))
            self._pending_queries.clear()

    async def async_send_conversation_query(
        self,
        text: str,
        conversation_id: str | None = None,
        language: str = "en",
    ) -> dict[str, Any]:
        """Send a conversation query to Hermes and wait for the response.

        Returns the response dict from Hermes (contains 'text' and
        optionally 'speech' keys).
        """
        import uuid

        if conversation_id is None:
            conversation_id = str(uuid.uuid4())

        payload = {
            "type": "assist_query",
            "text": text,
            "conversation_id": conversation_id,
            "language": language,
        }

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending_queries[conversation_id] = future

        if self._connected and self._ws:
            try:
                await self._ws.send_json(payload)
            except Exception as exc:
                self._pending_queries.pop(conversation_id, None)
                _LOGGER.warning("Failed to send conversation query: %s", exc)
                raise ConnectionError(f"Failed to send to Hermes: {exc}") from exc
        else:
            self._pending_queries.pop(conversation_id, None)
            raise ConnectionError("Hermes WebSocket not connected")

        try:
            result = await asyncio.wait_for(future, timeout=30.0)
            return result
        except asyncio.TimeoutError:
            self._pending_queries.pop(conversation_id, None)
            raise TimeoutError("Hermes did not respond within 30 seconds")

    async def async_shutdown(self) -> None:
        """Clean up connections."""
        self._connected = False
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
            self._reader_task = None
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._session:
            await self._session.close()
            self._session = None

    async def async_relay_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """Relay a Hermes voice/control command over the Hermes WebSocket."""
        _LOGGER.debug("Hermes command received: %s", command)
        action = str(command.get("action", "")).lower()
        payload = {
            "type": "voice_action",
            "action": action,
            "media_player_entity": command.get("media_player_entity", self.media_player_entity),
            "args": {
                "tts_engine": self.tts_engine,
                "tts_voice": self.tts_voice,
                "stt_engine": self.stt_engine,
                "stt_model": self.stt_model,
                "wake_word_engine": self.wake_word_engine,
                "wake_word": self.wake_word,
                "media_player_entity": command.get("media_player_entity", self.media_player_entity),
                **dict(command.get("args") or {}),
            },
        }

        if action == "enable":
            self._voice_ready = True
        elif action == "disable":
            self._voice_ready = False

        if self._connected and self._ws:
            try:
                await self._ws.send_json(payload)
                return {"ok": True, "sent": True, "voice_ready": self._voice_ready}
            except Exception as exc:
                _LOGGER.warning("Failed to relay Hermes voice action: %s", exc)

        self._pending.append(payload)
        if len(self._pending) > 1000:
            self._pending = self._pending[-500:]
        return {"ok": False, "queued": True, "voice_ready": self._voice_ready}

    def status_snapshot(self) -> list[dict[str, Any]]:
        """Return HA-local Hermes status sensor data.

        The custom component must be self-contained for HACS/manual installs,
        so it cannot import the Hermes plugin package at runtime.
        """
        uptime_hours = (time.monotonic() - self._start_time) / 3600.0
        return [
            {"entity_id": "sensor.hermes_gateway_status", "state": "on" if self._connected else "off", "attributes": {"friendly_name": "Hermes Gateway Status", "icon": "mdi:router-wireless"}},
            {"entity_id": "sensor.hermes_uptime_hours", "state": round(uptime_hours, 2), "attributes": {"friendly_name": "Hermes Uptime", "icon": "mdi:timer-outline"}},
            {"entity_id": "sensor.hermes_total_interactions", "state": self._total_interactions, "attributes": {"friendly_name": "Hermes Voice Interactions", "icon": "mdi:microphone"}},
            {"entity_id": "sensor.hermes_total_errors", "state": self._total_errors, "attributes": {"friendly_name": "Hermes Voice Errors", "icon": "mdi:alert-circle"}},
            {"entity_id": "sensor.ha_ws_connection", "state": "on" if self._connected else "off", "attributes": {"friendly_name": "HA WebSocket Connection", "icon": "mdi:connection"}},
            {"entity_id": "sensor.hermes_voice_ready", "state": "on" if self._voice_ready else "off", "attributes": {"friendly_name": "Hermes Voice Ready", "icon": "mdi:account-voice"}},
            {"entity_id": "sensor.hermes_tts_voice", "state": self.tts_voice or "none", "attributes": {"friendly_name": "Hermes TTS Voice", "icon": "mdi:account-voice"}},
            {"entity_id": "sensor.hermes_stt_engine", "state": self.stt_engine or "none", "attributes": {"friendly_name": "Hermes STT Engine", "icon": "mdi:microphone"}},
            {"entity_id": "sensor.hermes_wake_word", "state": ", ".join(self.wake_word) if isinstance(self.wake_word, list) else str(self.wake_word), "attributes": {"friendly_name": "Hermes Wake Word", "icon": "mdi:emoticon-excited"}},
            {"entity_id": "sensor.hermes_media_player", "state": self.media_player_entity or "none", "attributes": {"friendly_name": "Hermes Media Player", "icon": "mdi:speaker"}},
        ]


async def _flush_pending(ws, pending: list) -> None:
    """Send queued messages once reconnected."""
    while pending:
        payload = pending.pop(0)
        try:
            await ws.send_json(payload)
        except Exception:
            pending.insert(0, payload)
            break
