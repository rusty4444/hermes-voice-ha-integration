"""Marker convention for Assist turns from a configured voice panel (#58).

The Home Assistant integration adds a ``panel`` object to ``assist_query`` only
for turns from the panel device the user configured. It lists the enabled
routes and the limits Home Assistant enforces, for example::

    {"routes": {"/display/info": {"max_length": 60},
                "/light": {"min": 10, "max": 100},
                "/volume": {"min": 20, "max": 80}}}

This module turns that object into system-prompt instructions. It accepts only
the known routes and bounded integers, so the payload cannot inject free text
into the prompt. Without a valid ``panel`` object the result is empty and the
prompt stays exactly as before.
"""

from __future__ import annotations

import math
from typing import Any

ROUTE_HUD = "/display/info"
ROUTE_LIGHT = "/light"
ROUTE_VOLUME = "/volume"


def _int_in(value: Any, low: int, high: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or float(value) != int(value):
        return None
    number = int(value)
    return number if low <= number <= high else None


def _range(spec: Any) -> tuple[int, int] | None:
    if not isinstance(spec, dict):
        return None
    low = _int_in(spec.get("min"), 0, 100)
    high = _int_in(spec.get("max"), 0, 100)
    if low is None or high is None or low > high:
        return None
    return low, high


def panel_instructions(panel: Any) -> str:
    """Return the marker convention for a valid ``panel`` object, else ''."""
    if not isinstance(panel, dict) or not isinstance(panel.get("routes"), dict):
        return ""
    routes = panel["routes"]
    lines: list[str] = []

    hud = routes.get(ROUTE_HUD)
    max_length = _int_in(hud.get("max_length"), 1, 255) if isinstance(hud, dict) else None
    if max_length is not None:
        lines.append(
            '- [HW:/display/info:{"text":"..."}] shows one short line on the panel '
            f"screen, at most {max_length} characters. Don't repeat what you say aloud."
        )

    light = _range(routes.get(ROUTE_LIGHT))
    if light is not None:
        lines.append(
            '- [HW:/light:{"brightness_pct":N}] sets the screen brightness in percent, '
            f"N from {light[0]} to {light[1]}."
        )

    volume = _range(routes.get(ROUTE_VOLUME))
    if volume is not None:
        lines.append(
            '- [HW:/volume:{"value":N}] sets the speaker volume in percent, '
            f"N from {volume[0]} to {volume[1]}."
        )

    if not lines:
        return ""
    return (
        "This request comes from a voice panel with a screen. You can control the "
        "panel by putting markers at the start of your reply. Markers are removed "
        "before the reply is spoken. Use one only when it helps, write it exactly "
        "as shown with a JSON object, and always add a normal spoken reply after it.\n"
        + "\n".join(lines)
        + "\nValues outside these ranges are corrected by Home Assistant."
    )
