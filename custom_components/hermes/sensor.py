"""Hermes status sensors for Home Assistant."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
_UPDATE_INTERVAL = timedelta(seconds=30)


def _snapshot_key(entity_id: str) -> str:
    """Return the stable key suffix for an HA entity_id."""
    return entity_id.split(".", 1)[1] if "." in entity_id else entity_id


class HermesStatusUpdateCoordinator(DataUpdateCoordinator):
    """Poll HermesStatusSensors and make the snapshot available to entities."""

    def __init__(self, hass, status_sensors_getter) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_status",
            update_interval=_UPDATE_INTERVAL,
        )
        self._get_sensors = status_sensors_getter

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            sensors = self._get_sensors()
            snap = sensors.snapshot() if hasattr(sensors, "snapshot") else sensors
            return {_snapshot_key(s["entity_id"]): s for s in snap}
        except Exception as exc:
            raise UpdateFailed(f"Hermes status fetch failed: {exc}") from exc


_DESCRIPTIONS = [
    SensorEntityDescription(
        key="hermes_gateway_status",
        name="Hermes Gateway Status",
        icon="mdi:router-wireless",
    ),
    SensorEntityDescription(
        key="hermes_uptime_hours",
        name="Hermes Uptime",
        icon="mdi:timer-outline",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="h",
    ),
    SensorEntityDescription(
        key="hermes_total_interactions",
        name="Hermes Voice Interactions",
        icon="mdi:microphone",
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="hermes_total_errors",
        name="Hermes Voice Errors",
        icon="mdi:alert-circle",
        state_class=SensorStateClass.TOTAL,
    ),
    SensorEntityDescription(
        key="ha_ws_connection",
        name="HA WebSocket Connection",
        icon="mdi:connection",
    ),
    SensorEntityDescription(
        key="hermes_voice_ready",
        name="Hermes Voice Ready",
        icon="mdi:account-voice",
    ),
]


class HermesStatusSensor(SensorEntity):
    """A single status sensor driven by the HermesStatusSensors singleton."""

    def __init__(
        self,
        coordinator: HermesStatusUpdateCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        self._coordinator = coordinator
        self.entity_description = description
        self._attr_unique_id = f"{DOMAIN}_{description.key}"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> Any:
        data = self._coordinator.data or {}
        entry = data.get(self.entity_description.key, {})
        return entry.get("state", "unavailable")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self._coordinator.data or {}
        entry = data.get(self.entity_description.key, {})
        attrs: dict[str, Any] = dict(entry.get("attributes", {}))
        attrs["last_updated"] = datetime.now(timezone.utc).isoformat()
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self._coordinator.async_add_listener(self._handle_coordinator_update)
        )
        self._handle_coordinator_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._attr_native_value = self.native_value
        self.async_write_ha_state()


async def async_setup_entry(hass, entry, async_add_entities) -> bool:
    """Set up Hermes status sensors from a config entry."""
    bridge = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if bridge is None:
        return False

    coordinator = HermesStatusUpdateCoordinator(
        hass=hass,
        status_sensors_getter=bridge.status_snapshot,
    )
    await coordinator.async_config_entry_first_refresh()

    entities = [HermesStatusSensor(coordinator, desc) for desc in _DESCRIPTIONS]
    hass.data.setdefault(f"{DOMAIN}_entities", {})[entry.entry_id] = entities
    async_add_entities(entities)
    return True
