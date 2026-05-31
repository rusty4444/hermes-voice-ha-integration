"""Scene/Script Auto-Discovery — build compound tools from HA scenes + scripts.

P3: At session start, queries HA for all defined scenes and scripts, then
generates dedicated tool schemas so the LLM can activate any scene or script
by name without manually resolving entity_ids.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


def discover_scenes_scripts() -> Dict[str, Any]:
    """Fetch all defined scenes and scripts from HA.

    Returns: {"scenes": [...], "scripts": [...], "total_scenes": N, "total_scripts": N}
    """
    try:
        from .ha_assistant import search_entities

        scenes = search_entities(domain="scene")
        scripts = search_entities(domain="script")

        result = {
            "scenes": scenes.get("entities", []),
            "scripts": scripts.get("entities", []),
            "total_scenes": scenes.get("count", 0),
            "total_scripts": scripts.get("count", 0),
        }
        logger.info(
            "Scene/script discovery: %d scenes, %d scripts",
            result["total_scenes"],
            result["total_scripts"],
        )
        return result
    except Exception as exc:
        logger.error("Scene/script discovery failed: %s", exc)
        return {"scenes": [], "scripts": [], "total_scenes": 0, "total_scripts": 0}


def build_scene_tool_schemas(scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate tool schemas for each detected HA scene.

    Returns a list of Hermes tool schema dicts ready for registration.
    """
    schemas = []
    for scene in scenes:
        entity_id = scene.get("entity_id", "")
        friendly_name = scene.get("friendly_name", entity_id)
        short_name = entity_id.replace("scene.", "") if entity_id.startswith("scene.") else entity_id

        schema = {
            "name": f"ha_scene_{short_name}",
            "description": (
                f"Activate the Home Assistant scene '{friendly_name}' "
                f"(entity_id: {entity_id}). This is a Hermes compound tool "
                f"auto-discovered from your HA configuration."
            ),
            "parameters": {"type": "object", "properties": {}},
            "_scene_entity_id": entity_id,  # metadata for the handler
        }
        schemas.append(schema)
    return schemas


def build_script_tool_schemas(scripts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Generate tool schemas for each detected HA script."""
    schemas = []
    for script in scripts:
        entity_id = script.get("entity_id", "")
        friendly_name = script.get("friendly_name", entity_id)
        short_name = entity_id.replace("script.", "") if entity_id.startswith("script.") else entity_id

        schema = {
            "name": f"ha_script_{short_name}",
            "description": (
                f"Run the Home Assistant script '{friendly_name}' "
                f"(entity_id: {entity_id}). This is a Hermes compound tool "
                f"auto-discovered from your HA configuration."
            ),
            "parameters": {"type": "object", "properties": {}},
            "_script_entity_id": entity_id,
        }
        schemas.append(schema)
    return schemas


def make_scene_handler(entity_id: str) -> Callable[..., str]:
    """Return a handler function that activates the given scene."""

    def _handler(args: dict, **kw) -> str:
        from .ha_assistant import call_service
        result = call_service("scene", "turn_on", entity_id=entity_id)
        if "error" in result:
            return json.dumps({"error": result["error"]})
        return json.dumps({"ok": True, "scene": entity_id, "result": result})

    return _handler


def make_script_handler(entity_id: str) -> Callable[..., str]:
    """Return a handler function that runs the given script."""

    def _handler(args: dict, **kw) -> str:
        from .ha_assistant import call_service
        result = call_service("script", "turn_on", entity_id=entity_id)
        if "error" in result:
            return json.dumps({"error": result["error"]})
        return json.dumps({"ok": True, "script": entity_id, "result": result})

    return _handler


# ---------------------------------------------------------------------------
# Observability metrics
# ---------------------------------------------------------------------------

import time as _time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class VoiceLatencyMetric:
    """A single voice pipeline latency measurement."""
    stt_latency_ms: float = 0.0
    llm_latency_ms: float = 0.0
    tts_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class Observability:
    """Track voice pipeline latency and error rate metrics."""

    def __init__(self, max_samples: int = 100) -> None:
        self._samples: deque[VoiceLatencyMetric] = deque(maxlen=max_samples)
        self._lock = __import__("threading").Lock()

    def record(self, metric: VoiceLatencyMetric) -> None:
        with self._lock:
            self._samples.append(metric)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            if not self._samples:
                return {"samples": 0, "avg_total_ms": 0}
            samples_list = list(self._samples)
            total_ms = [s.total_latency_ms for s in samples_list]
            stt_ms = [s.stt_latency_ms for s in samples_list if s.stt_latency_ms > 0]
            llm_ms = [s.llm_latency_ms for s in samples_list if s.llm_latency_ms > 0]
            tts_ms = [s.tts_latency_ms for s in samples_list if s.tts_latency_ms > 0]

            def _avg(vals):
                return round(sum(vals) / len(vals), 1) if vals else 0

            return {
                "samples": len(samples_list),
                "avg_total_ms": _avg(total_ms),
                "avg_stt_ms": _avg(stt_ms),
                "avg_llm_ms": _avg(llm_ms),
                "avg_tts_ms": _avg(tts_ms),
                "p50_total_ms": _percentile(total_ms, 50),
                "p95_total_ms": _percentile(total_ms, 95),
            }


def _percentile(data: List[float], p: float) -> float:
    """Return the p-th percentile of a sorted list."""
    import math

    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (p / 100.0) * (len(sorted_data) - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_data[int(k)]
    d0 = sorted_data[int(f)] * (c - k)
    d1 = sorted_data[int(c)] * (k - f)
    return round(d0 + d1, 1)


# Singleton
_observability: Optional[Observability] = None


def get_observability() -> Observability:
    global _observability
    if _observability is None:
        _observability = Observability()
    return _observability
