"""Hermes Status Sensors — expose Hermes pipeline health as real HA entities.

P3: Defines AsyncSensorEntity subclasses that the Home Assistant entity registry
tracks.  They are updated in-place by the HermesBridge at ~30 s intervals via
``async_update_ha_state()`` so HA dashboards can display them as first-class citizens.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import (
    callback,
)
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

_PUSH_INTERVAL = 30.0   # seconds between Hermes→HA status pushes

# ---------------------------------------------------------------------------
# Coordinator — keeps the single source of truth for all Hermes status metrics
# ---------------------------------------------------------------------------

class HermesStatusUpdateCoordinator(DataUpdateCoordinator):
    """Poll HermesStatusSensors and make the snapshot available to entities."""

    def __init__(self, hass, status_sensors_getter) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_status",
            update_interval=_PUSH_INTERVAL,
        )
        self._get_sensors = status_sensors_getter  # callable → HermesStatusSensors

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            snap = self._get_sensors()
            return {s["entity_id"]: s for s in snap}
        except Exception as exc:
            raise UpdateFailed(f"Hermes status fetch failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Entity descriptions
# ---------------------------------------------------------------------------

_GATEWAY_DESC = EntityDescription(
    key="hermes_gateway_status",
    name="Hermes Gateway Status",
    device_class=SensorDeviceClass.ENUM,
    icon="mdi:router-wireless",
)
_UPTIME_DESC = EntityDescription(
    key="hermes_uptime_hours",
    name="Hermes Uptime",
    device_class=SensorDeviceClass.DURATION,
    icon="mdi:timer-outline",
    state_class=SensorStateClass.MEASUREMENT,
)
_INTERACTIONS_DESC = EntityDescription(
    key="hermes_total_interactions",
    name="Hermes Voice Interactions",
    icon="mdi:microphone",
    state_class=SensorStateClass.TOTAL,
)
_ERRORS_DESC = EntityDescription(
    key="hermes_total_errors",
    name="Hermes Voice Errors",
    icon="mdi:alert-circle",
    state_class=SensorStateClass.TOTAL,
)
_WS_DESC = EntityDescription(
    key="ha_ws_connection",
    name="HA WebSocket Connection",
    device_class=SensorDeviceClass.CONNECTIVITY,
    icon="mdi:connection",
)
_VOICE_READY_DESC = EntityDescription(
    key="hermes_voice_ready",
    name="Hermes Voice Ready",
    icon="mdi:account-voice",
)

_DESCRIPTIONS = [
    _GATEWAY_DESC,
    _UPTIME_DESC,
    _INTERACTIONS_DESC,
    _ERRORS_DESC,
    _WS_DESC,
    _VOICE_READY_DESC,
]


# ---------------------------------------------------------------------------
# Sensor entity
# ---------------------------------------------------------------------------

class HermesStatusSensor(SensorEntity):
    """A single status sensor driven by the HermesStatusSensors singleton."""

    def __init__(
        self,
        coordinator: HermesStatusUpdateCoordinator,
        description: EntityDescription,
    ) -> None:
        self._coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"

    @property
    def native_value(self) -> Any:
        data = self._coordinator.data or {}
        entry = data.get(self.entity_description.key, {})
        return entry.get("state", "unavailable")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._coordinator.data or {}
        entry = data.get(self.entity_description.key, {})
        attrs: dict[str, Any] = entry.get("attributes", {})
        attrs["last_updated"] = datetime.now(timezone.utc).isoformat()
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._handle_coordinator_update()  # initial push

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = self.native_value
        self.async_write_ha_state()


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(hass, entry):
    """Set up Hermes status sensors from a config entry.

    Called by ``hass.config_entries.async_forward_entry_setup`` when the
    ``sensor`` platform (i.e. this file) is listed in ``PLATFORMS``.
    """
    from plugins.home_assistant.status_sensors import get_status_sensors
    from . import HermesBridge

    bridge: HermesBridge | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if bridge is None:
        return False

    snapshot_fn = get_status_sensors
    coordinator = HermesStatusUpdateCoordinator(
        hass=hass,
                status_sensors_getter=snapshot_fn,
    )

    entities = [HermesStatusSensor(coordinator, desc) for desc in _DESCRIPTIONS]

    hass.data.setdefault(f"{DOMAIN}_entities", {})[entry.entry_id] = entities

    await hass.config_entries.async_forward_entry_setup(entry, "sensor")
    return True
