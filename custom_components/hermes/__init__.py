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
import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL, CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant, ServiceResponse
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN, CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER, CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL
from .frontend import async_register_resources as _register_frontend

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = ["sensor"]

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
    entity_filter = entry.data.get(CONF_ENTITY_FILTER, DEFAULT_ENTITY_FILTER)
    verify_ssl = entry.data.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL)

    bridge = HermesBridge(hass, url, token, entity_filter, verify_ssl)
    hass.data[DOMAIN][entry.entry_id] = bridge

    # Connect WebSocket to Hermes Agent
    await bridge.async_connect()

    # Register state-change listener
    entry.async_on_unload(
        async_track_state_change_event(
            hass,
            entity_filter,
            bridge.on_state_change,
        )
    )

    # Register HA services exposed to Hermes
    await bridge.async_register_services()

    # Register HermesActionBar Lovelace card resource
    await _register_frontend(hass)

    _LOGGER.info("Hermes integration set up — URL: %s, entities tracked: %d",
                 url, len(entity_filter))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    bridge: HermesBridge | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if bridge:
        await bridge.async_shutdown()
    return True


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
    ) -> None:
        self.hass = hass
        self.hermes_url = hermes_url.rstrip("/")
        self.hermes_token = hermes_token
        self.entity_filter = entity_filter
        self.verify_ssl = verify_ssl
        self._session: Any = None
        self._ws: Any = None
        self._connected = False
        self._pending: list[dict[str, Any]] = []

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
        import time
        now = time.monotonic()
        last = _LAST_PUSH.get(entity_id, 0)
        if now - last < _PUSH_INTERVAL.total_seconds():
            return
        _LAST_PUSH[entity_id] = now

        new_state = event.data.get("new_state")
        if new_state is None:
            return

        payload = {
            "type": "state_changed",
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
        import aiohttp
        import ssl as _ssl

        ssl_context: _ssl.SSLContext | None = None
        if not self.verify_ssl:
            ssl_context = _ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = _ssl.CERT_NONE

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
            self._connected = True
            _LOGGER.info("Connected to Hermes WebSocket at %s", self.hermes_url)
            # Flush any pending messages queued while disconnected
            await _flush_pending(self._ws, self._pending)
        except Exception as exc:
            _LOGGER.warning("Failed to connect to Hermes WebSocket: %s", exc)
            self._connected = False


async def _flush_pending(ws, pending: list) -> None:
    """Send queued messages once reconnected."""
    while pending:
        try:
            await ws.send_json(pending.pop(0))
        except Exception:
            pending.insert(0, pending.pop(0) if pending else {})
            break

    async def async_shutdown(self) -> None:
        """Clean up connections."""
        self._connected = False
        if self._ws:
            await self._ws.close()
        if self._session:
            await self._session.close()

    async def async_relay_command(self, command: dict[str, Any]) -> dict[str, Any]:
        """Relay a Hermes dispatch command to HA."""
        _LOGGER.debug("Hermes command received: %s", command)
        return {"ok": True, "message": "P0: command relay is stub"}
