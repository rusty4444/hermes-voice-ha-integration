"""Opt-in voice-panel control through inline ``[HW:...]`` markers (#58).

On turns that come from the configured panel device, Hermes may start its
reply with markers such as::

    [HW:/display/info:{"text":"14:30"}]
    [HW:/light:{"brightness_pct":40}]
    [HW:/volume:{"value":30}]

The markers are removed before text-to-speech and turned into Home Assistant
service calls on the configured entities. Rules:

* Nothing happens unless a panel device and at least one route entity are
  configured, and the Assist request carries that device's ``device_id``.
* Clean first, execute only what parses: every marker-shaped span is removed
  from the speech, even broken ones, but only well-formed markers for an
  enabled route run.
* Limits are enforced here, below the model. Brightness and volume are clamped
  to the configured range whatever the reply asks for.
* At most one call per route per reply, dispatched without blocking the reply.

This module only depends on the standard library and ``const`` so the parsing
and planning logic can be tested without Home Assistant.
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping

from .const import (
    CONF_PANEL_BRIGHTNESS_MAX,
    CONF_PANEL_BRIGHTNESS_MIN,
    CONF_PANEL_DEVICE,
    CONF_PANEL_HUD_ENTITY,
    CONF_PANEL_HUD_MAX_LENGTH,
    CONF_PANEL_LIGHT_ENTITY,
    CONF_PANEL_VOLUME_ENTITY,
    CONF_PANEL_VOLUME_MAX,
    CONF_PANEL_VOLUME_MIN,
    DEFAULT_PANEL_BRIGHTNESS_MAX,
    DEFAULT_PANEL_BRIGHTNESS_MIN,
    DEFAULT_PANEL_HUD_MAX_LENGTH,
    DEFAULT_PANEL_VOLUME_MAX,
    DEFAULT_PANEL_VOLUME_MIN,
    PANEL_HUD_DOMAINS,
    PANEL_HUD_MAX_LENGTH_LIMIT,
    PANEL_LIGHT_DOMAINS,
    PANEL_VOLUME_DOMAINS,
)

_LOGGER = logging.getLogger(__name__)

ROUTE_HUD = "/display/info"
ROUTE_LIGHT = "/light"
ROUTE_VOLUME = "/volume"
ROUTES = (ROUTE_HUD, ROUTE_LIGHT, ROUTE_VOLUME)

_ENTITY_ID = re.compile(r"^([a-z0-9_]+)\.[a-z0-9_]+$")
_MARKER_START = re.compile(r"\[HW:", re.IGNORECASE)
_ROUTE = re.compile(r"/[A-Za-z0-9_\-/]*")
# Markdown-link variant some models produce: [label](HW:/light:{...}).
# Keep the label, drop the link target, never execute it.
_LINK_MARKER = re.compile(r"\[([^\]\n]*)\]\(\s*HW:[^)\n]*\)", re.IGNORECASE)
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")
_DECODER = json.JSONDecoder()

# Spoken when a reply consisted only of markers that were dispatched, so the
# panel does not go silent. Keyed by the primary language subtag.
_FALLBACK_SPEECH = {
    "de": "Erledigt.",
    "en": "Done.",
    "es": "Hecho.",
    "fr": "C'est fait.",
    "it": "Fatto.",
    "nl": "Klaar.",
    "pt": "Feito.",
}


@dataclass(frozen=True)
class Marker:
    """One well-formed marker taken from a reply."""

    route: str
    params: dict[str, Any]


@dataclass(frozen=True)
class ServiceCall:
    """A Home Assistant service call planned from a marker."""

    domain: str
    service: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PanelConfig:
    """Validated panel options. Built only when at least one route is enabled."""

    device_id: str
    hud_entity: str = ""
    light_entity: str = ""
    volume_entity: str = ""
    hud_max_length: int = DEFAULT_PANEL_HUD_MAX_LENGTH
    brightness_min: int = DEFAULT_PANEL_BRIGHTNESS_MIN
    brightness_max: int = DEFAULT_PANEL_BRIGHTNESS_MAX
    volume_min: int = DEFAULT_PANEL_VOLUME_MIN
    volume_max: int = DEFAULT_PANEL_VOLUME_MAX

    def entity_for(self, route: str) -> str:
        return {
            ROUTE_HUD: self.hud_entity,
            ROUTE_LIGHT: self.light_entity,
            ROUTE_VOLUME: self.volume_entity,
        }.get(route, "")

    @property
    def enabled_routes(self) -> tuple[str, ...]:
        return tuple(route for route in ROUTES if self.entity_for(route))

    def as_payload(self) -> dict[str, Any]:
        """Describe enabled routes and limits for the Hermes-side prompt.

        Hermes renders the marker convention from these numbers, so the model
        is told exactly the limits this module enforces.
        """
        routes: dict[str, dict[str, int]] = {}
        if self.hud_entity:
            routes[ROUTE_HUD] = {"max_length": self.hud_max_length}
        if self.light_entity:
            routes[ROUTE_LIGHT] = {"min": self.brightness_min, "max": self.brightness_max}
        if self.volume_entity:
            routes[ROUTE_VOLUME] = {"min": self.volume_min, "max": self.volume_max}
        return {"routes": routes}


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
def entity_or_empty(value: Any, domains: Iterable[str]) -> str:
    """Return ``value`` when it is an entity ID in one of ``domains``, else ''."""
    entity_id = str(value or "").strip().lower()
    match = _ENTITY_ID.match(entity_id)
    if match is None or match.group(1) not in tuple(domains):
        return ""
    return entity_id


def bounded_int(value: Any, default: int, low: int, high: int) -> int:
    """Coerce ``value`` to an int within ``[low, high]``; fall back to default."""
    number = _finite_number(value)
    if number is None:
        return default
    return max(low, min(high, int(round(number))))


def panel_config_from_options(options: Mapping[str, Any] | None) -> PanelConfig | None:
    """Build the panel configuration, or None while the feature is disabled."""
    options = options or {}
    device_id = str(options.get(CONF_PANEL_DEVICE) or "").strip()
    if not device_id:
        return None

    brightness_max = bounded_int(
        options.get(CONF_PANEL_BRIGHTNESS_MAX), DEFAULT_PANEL_BRIGHTNESS_MAX, 0, 100
    )
    volume_max = bounded_int(
        options.get(CONF_PANEL_VOLUME_MAX), DEFAULT_PANEL_VOLUME_MAX, 0, 100
    )
    config = PanelConfig(
        device_id=device_id,
        hud_entity=entity_or_empty(options.get(CONF_PANEL_HUD_ENTITY), PANEL_HUD_DOMAINS),
        light_entity=entity_or_empty(
            options.get(CONF_PANEL_LIGHT_ENTITY), PANEL_LIGHT_DOMAINS
        ),
        volume_entity=entity_or_empty(
            options.get(CONF_PANEL_VOLUME_ENTITY), PANEL_VOLUME_DOMAINS
        ),
        hud_max_length=bounded_int(
            options.get(CONF_PANEL_HUD_MAX_LENGTH),
            DEFAULT_PANEL_HUD_MAX_LENGTH,
            1,
            PANEL_HUD_MAX_LENGTH_LIMIT,
        ),
        # A floor above the ceiling is clamped down to it, never up past it.
        brightness_min=min(
            brightness_max,
            bounded_int(
                options.get(CONF_PANEL_BRIGHTNESS_MIN), DEFAULT_PANEL_BRIGHTNESS_MIN, 0, 100
            ),
        ),
        brightness_max=brightness_max,
        volume_min=min(
            volume_max,
            bounded_int(options.get(CONF_PANEL_VOLUME_MIN), DEFAULT_PANEL_VOLUME_MIN, 0, 100),
        ),
        volume_max=volume_max,
    )
    return config if config.enabled_routes else None


def panel_for_turn(
    options: Mapping[str, Any] | None, device_id: str | None
) -> PanelConfig | None:
    """Return the panel configuration only for turns from the panel device."""
    config = panel_config_from_options(options)
    if config is None or not device_id or str(device_id) != config.device_id:
        return None
    return config


# ---------------------------------------------------------------------------
# Marker extraction
# ---------------------------------------------------------------------------
def _parse_marker(text: str, start: int) -> tuple[int, Marker | None]:
    """Parse the marker at ``text[start:]``.

    Returns the index just past the span to remove and the marker, or None
    when the marker is malformed. Malformed spans are still removed.
    """
    length = len(text)
    pos = start + len("[HW:")
    route_match = _ROUTE.match(text, pos)
    route = ""
    if route_match:
        route = route_match.group(0).rstrip("/").lower()
        pos = route_match.end()
    params: dict[str, Any] = {}
    valid = bool(route)
    json_end: int | None = None

    if pos < length and text[pos] == ":":
        pos += 1
        while pos < length and text[pos] in " \t":
            pos += 1
        if pos < length and text[pos] == "{":
            try:
                parsed, json_end = _DECODER.raw_decode(text, pos)
            except ValueError:
                valid = False
            else:
                pos = json_end
                if isinstance(parsed, dict):
                    params = parsed
                else:
                    valid = False
        else:
            valid = False

    while pos < length and text[pos] in " \t":
        pos += 1
    if valid and pos < length and text[pos] == "]":
        return pos + 1, Marker(route=route, params=params)

    # Malformed: remove it anyway so it is never spoken. Prefer the closing
    # bracket after a parsed JSON body, then the next bracket on this line,
    # and otherwise the rest of the line.
    search_from = json_end if json_end is not None else start
    line_end = text.find("\n", search_from)
    if line_end < 0:
        line_end = length
    close = text.find("]", search_from, line_end)
    if close >= 0:
        return close + 1, None
    if json_end is not None:
        return json_end, None
    return line_end, None


def extract_markers(text: str) -> tuple[str, list[Marker]]:
    """Remove every marker-shaped span from ``text``.

    Returns the cleaned speech and the well-formed markers in reply order.
    Text without markers is returned unchanged.
    """
    if not text or "hw:" not in text.lower():
        return text, []

    pieces: list[str] = []
    markers: list[Marker] = []
    pos = 0
    removed = False
    while True:
        match = _MARKER_START.search(text, pos)
        if match is None:
            pieces.append(text[pos:])
            break
        pieces.append(text[pos : match.start()])
        end, marker = _parse_marker(text, match.start())
        removed = True
        if marker is None:
            _LOGGER.warning(
                "Hermes panel: removed a malformed marker without running it: %r",
                text[match.start() : end][:120],
            )
        else:
            markers.append(marker)
        pos = end

    cleaned = "".join(pieces)
    linked = _LINK_MARKER.sub(lambda m: m.group(1), cleaned)
    if linked != cleaned:
        removed = True
        _LOGGER.warning("Hermes panel: removed a link-style marker without running it")
        cleaned = linked
    if not removed:
        return text, []

    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip(), markers


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
def _finite_number(value: Any) -> float | None:
    """Return ``value`` as a finite float; booleans and text are rejected."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _hud_text(params: Mapping[str, Any]) -> str | None:
    text = params.get("text")
    if isinstance(text, bool) or not isinstance(text, (str, int, float)):
        return None
    value = str(text)
    subtitle = params.get("subtitle")
    if isinstance(subtitle, str) and subtitle.strip():
        value = f"{value} — {subtitle}" if value.strip() else subtitle
    value = _CONTROL_CHARS.sub(" ", value)
    return re.sub(r"\s{2,}", " ", value).strip()


def _plan_hud(config: PanelConfig, params: Mapping[str, Any], state: Any) -> ServiceCall | None:
    value = _hud_text(params)
    if value is None:
        _LOGGER.warning("Hermes panel: HUD marker needs a 'text' string; skipped")
        return None
    limit = config.hud_max_length
    entity_max = _finite_number(getattr(state, "attributes", {}).get("max"))
    if entity_max is not None and entity_max >= 0:
        limit = min(limit, int(entity_max))
    domain = config.hud_entity.split(".", 1)[0]
    return ServiceCall(
        domain, "set_value", {"entity_id": config.hud_entity, "value": value[:limit].rstrip()}
    )


def _plan_light(config: PanelConfig, params: Mapping[str, Any], state: Any) -> ServiceCall | None:
    requested = _finite_number(params.get("brightness_pct"))
    if requested is None:
        _LOGGER.warning("Hermes panel: light marker needs a numeric 'brightness_pct'; skipped")
        return None
    value = max(config.brightness_min, min(config.brightness_max, int(round(requested))))
    if value != requested:
        _LOGGER.info("Hermes panel: brightness %s clamped to %s", requested, value)
    return ServiceCall(
        "light", "turn_on", {"entity_id": config.light_entity, "brightness_pct": value}
    )


def _plan_volume(config: PanelConfig, params: Mapping[str, Any], state: Any) -> ServiceCall | None:
    requested = _finite_number(params.get("value"))
    if requested is None:
        _LOGGER.warning("Hermes panel: volume marker needs a numeric 'value'; skipped")
        return None
    percent = max(config.volume_min, min(config.volume_max, requested))
    if percent != requested:
        _LOGGER.info("Hermes panel: volume %s%% clamped to %s%%", requested, percent)

    attributes = getattr(state, "attributes", {}) or {}
    low = _finite_number(attributes.get("min"))
    high = _finite_number(attributes.get("max"))
    if low is None or high is None or high < low:
        _LOGGER.warning(
            "Hermes panel: %s has no usable min/max range; volume skipped",
            config.volume_entity,
        )
        return None
    value = low + (high - low) * percent / 100.0
    step = _finite_number(attributes.get("step"))
    if step is not None and step > 0:
        value = low + round((value - low) / step) * step
    value = round(max(low, min(high, value)), 6)
    if value.is_integer():
        value = int(value)
    domain = config.volume_entity.split(".", 1)[0]
    return ServiceCall(domain, "set_value", {"entity_id": config.volume_entity, "value": value})


_PLANNERS: dict[str, Callable[[PanelConfig, Mapping[str, Any], Any], ServiceCall | None]] = {
    ROUTE_HUD: _plan_hud,
    ROUTE_LIGHT: _plan_light,
    ROUTE_VOLUME: _plan_volume,
}


def plan_calls(
    markers: Iterable[Marker],
    config: PanelConfig,
    get_state: Callable[[str], Any],
) -> list[ServiceCall]:
    """Translate markers into bounded service calls on configured entities.

    Unknown or disabled routes and missing entities are skipped with a log
    line; a destination is never invented. Only the first marker per route
    runs.
    """
    calls: list[ServiceCall] = []
    seen: set[str] = set()
    for marker in markers:
        planner = _PLANNERS.get(marker.route)
        entity_id = config.entity_for(marker.route)
        if planner is None or not entity_id:
            _LOGGER.warning("Hermes panel: route %s is not enabled; skipped", marker.route)
            continue
        if marker.route in seen:
            _LOGGER.info("Hermes panel: extra %s marker ignored", marker.route)
            continue
        seen.add(marker.route)
        state = get_state(entity_id)
        if state is None:
            _LOGGER.warning("Hermes panel: entity %s does not exist; skipped", entity_id)
            continue
        call = planner(config, marker.params, state)
        if call is not None:
            calls.append(call)
    return calls


def fallback_speech(language: str | None) -> str:
    """Short confirmation for replies that consisted only of markers."""
    primary = str(language or "").replace("_", "-").split("-", 1)[0].lower()
    return _FALLBACK_SPEECH.get(primary, _FALLBACK_SPEECH["en"])


async def async_dispatch(hass: Any, calls: Iterable[ServiceCall], context: Any = None) -> None:
    """Run planned calls without waiting for the devices; log failures."""
    for call in calls:
        try:
            await hass.services.async_call(
                call.domain, call.service, dict(call.data), blocking=False, context=context
            )
        except Exception as exc:  # noqa: BLE001 - a device failure must not break Assist
            _LOGGER.warning(
                "Hermes panel: %s.%s on %s failed: %s",
                call.domain,
                call.service,
                call.data.get("entity_id"),
                exc,
            )
