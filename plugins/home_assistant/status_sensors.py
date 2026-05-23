"""HA Status Sensors — expose Hermes pipeline health to Home Assistant.

P3: Creates synthetic entity state dictionaries that the HA custom integration
publishes as real entities in the entity registry.

Entities created:
- binary_sensor.hermes_gateway_status   (connected / disconnected)
- sensor.hermes_uptime_hours           (float, agent runtime)
- sensor.hermes_total_interactions     (int, lifetime completed voice interactions)
- sensor.hermes_total_errors           (int, lifetime pipeline errors)
- binary_sensor.ha_ws_connection       (WebSocket status)

Callers: custom_components/hermes/__init__.py reads these dicts and pushes
them to HA via the state pile / WebSocket bridge at ~30s intervals.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sensor definitions
# ---------------------------------------------------------------------------

@dataclass
class StatusSensor:
    """A single Hermes → HA status sensor."""
    entity_id: str
    friendly_name: str
    device_class: Optional[str]
    icon: str
    state: Any = "unknown"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "state": self.state,
            "attributes": {
                "friendly_name": self.friendly_name,
                "device_class": self.device_class,
                "icon": self.icon,
            },
        }


class HermesStatusSensors:
    """Collects all Hermes-to-HA status sensor state.

    Usage:
        sensors = HermesStatusSensors()
        sensors.start_time = time.monotonic()
        sensors.gateway_connected = True
        ...
        payload = sensors.snapshot()   # dict ready for HA state push
    """

    def __init__(self) -> None:
        self._start_time: float = 0.0
        self._gateway_connected: bool = False
        self._ws_connected: bool = False
        self._total_interactions: int = 0
        self._total_errors: int = 0
        self._voice_ready: bool = False

    # --- setters ---

    @property
    def start_time(self) -> Optional[float]:
        return self._start_time if self._start_time > 0 else None

    @start_time.setter
    def start_time(self, value: float) -> None:
        self._start_time = value

    @property
    def gateway_connected(self) -> bool:
        return self._gateway_connected

    @gateway_connected.setter
    def gateway_connected(self, value: bool) -> None:
        self._gateway_connected = value

    @property
    def ws_connected(self) -> bool:
        return self._ws_connected

    @ws_connected.setter
    def ws_connected(self, value: bool) -> None:
        self._ws_connected = value

    @property
    def total_interactions(self) -> int:
        return self._total_interactions

    @total_interactions.setter
    def total_interactions(self, value: int) -> None:
        self._total_interactions = value

    @property
    def total_errors(self) -> int:
        return self._total_errors

    @total_errors.setter
    def total_errors(self, value: int) -> None:
        self._total_errors = value

    @property
    def voice_ready(self) -> bool:
        return self._voice_ready

    @voice_ready.setter
    def voice_ready(self, value: bool) -> None:
        self._voice_ready = value

    # --- snapshot ---

    def snapshot(self) -> list[Dict[str, Any]]:
        """Return list of sensor dicts ready for HA state push."""
        uptime_hours = 0.0
        if self._start_time > 0:
            uptime_hours = (time.monotonic() - self._start_time) / 3600.0

        sensors = [
            StatusSensor(
                entity_id="binary_sensor.hermes_gateway_status",
                friendly_name="Hermes Gateway Status",
                device_class="connectivity",
                icon="mdi:router-wireless",
                state="on" if self._gateway_connected else "off",
            ),
            StatusSensor(
                entity_id="sensor.hermes_uptime_hours",
                friendly_name="Hermes Uptime",
                device_class="duration",
                icon="mdi:timer-outline",
                state=round(uptime_hours, 2),
            ),
            StatusSensor(
                entity_id="sensor.hermes_total_interactions",
                friendly_name="Hermes Voice Interactions",
                device_class=None,
                icon="mdi:microphone",
                state=self._total_interactions,
            ),
            StatusSensor(
                entity_id="sensor.hermes_total_errors",
                friendly_name="Hermes Voice Errors",
                device_class=None,
                icon="mdi:alert-circle",
                state=self._total_errors,
            ),
            StatusSensor(
                entity_id="binary_sensor.ha_ws_connection",
                friendly_name="HA WebSocket Connection",
                device_class="connectivity",
                icon="mdi:connection",
                state="on" if self._ws_connected else "off",
            ),
            StatusSensor(
                entity_id="binary_sensor.hermes_voice_ready",
                friendly_name="Hermes Voice Ready",
                device_class=None,
                icon="mdi:account-voice",
                state="on" if self._voice_ready else "off",
            ),
        ]
        return [s.to_dict() for s in sensors]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_status_sensors: Optional[HermesStatusSensors] = None


def get_status_sensors() -> HermesStatusSensors:
    """Return (or create) the module-level status sensor singleton."""
    global _status_sensors
    if _status_sensors is None:
        _status_sensors = HermesStatusSensors()
    return _status_sensors
