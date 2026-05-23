"""Compound tools for the Hermes Home Assistant plugin.

Compound tools reduce LLM round-trips by batching common HA operations into
single tool calls. This is critical for small local models that struggle with
multi-step tool-chaining.

P0 compound tools:
- control_light_and_set_scene  — set a scene AND adjust specific lights in one go
- turn_off_all_except          — turn off everything in a domain except named entities
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from plugins.home_assistant.ha_assistant import call_service, search_entities

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# control_light_and_set_scene
# ---------------------------------------------------------------------------

CONTROL_LIGHT_AND_SET_SCENE_SCHEMA = {
    "name": "control_light_and_set_scene",
    "description": (
        "Compound action: activate a Home Assistant scene and simultaneously "
        "adjust specific light entities (brightness, color, etc.). Saves a "
        "round-trip vs calling scene.turn_on + light.turn_on separately."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scene": {
                "type": "string",
                "description": (
                    "Scene entity_id (e.g. 'scene.movie_night') or scene name "
                    "(e.g. 'movie night'). If a name is provided, ha_search_entities "
                    "is used to resolve it to an entity_id."
                ),
            },
            "light_adjustments": {
                "type": "array",
                "description": (
                    "Optional list of per-light adjustments applied AFTER the scene is set. "
                    "Each entry: {'entity_id': 'light.kitchen', 'brightness': 128, 'color_name': 'red'}"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "entity_id": {"type": "string"},
                        "brightness": {"type": "integer", "minimum": 0, "maximum": 255},
                        "color_name": {"type": "string"},
                        "rgb_color": {
                            "type": "array", "items": {"type": "integer"}, "minItems": 3, "maxItems": 3,
                        },
                    },
                    "required": ["entity_id"],
                },
                "minItems": 0,
            },
        },
        "required": ["scene"],
    },
}


def _resolve_scene_entity_id(name_or_id: str) -> Optional[str]:
    """Resolve a scene name to its entity_id. Returns None if not found."""
    if name_or_id.startswith("scene."):
        return name_or_id
    result = search_entities(query=name_or_id, domain="scene")
    entities = result.get("entities", [])
    if len(entities) == 1:
        return entities[0]["entity_id"]
    # Multiple matches or none — return None to surface ambiguity
    if entities:
        logger.info("Ambiguous scene: %s → %d matches", name_or_id, len(entities))
    return None


def _handle_control_light_and_set_scene(args: dict, **kw) -> str:
    """Handler for control_light_and_set_scene."""
    scene_name = args.get("scene", "")
    light_adjustments: List[dict] = args.get("light_adjustments", []) or []

    # 1. Resolve scene
    scene_id = _resolve_scene_entity_id(scene_name)
    if scene_id is None:
        return json.dumps({
            "error": f"Scene '{scene_name}' not found or ambiguous. Try using the full entity_id (e.g. 'scene.movie_night')."
        })

    # 2. Activate scene
    results = []
    try:
        scene_result = call_service("scene", "turn_on", entity_id=scene_id)
        results.append({"action": "scene.turn_on", "entity_id": scene_id, "result": scene_result})
    except Exception as exc:
        return json.dumps({"error": f"Failed to activate scene '{scene_id}': {exc}"})

    # 3. Apply per-light adjustments
    for adj in light_adjustments:
        entity_id = adj.get("entity_id", "")
        data: Dict[str, Any] = {}
        if "brightness" in adj:
            data["brightness"] = adj["brightness"]
        if "color_name" in adj:
            data["color_name"] = adj["color_name"]
        if "rgb_color" in adj:
            data["rgb_color"] = adj["rgb_color"]

        if not data:
            results.append({"action": "light.adjust", "entity_id": entity_id, "skipped": True, "reason": "no data fields"})
            continue

        try:
            adj_result = call_service("light", "turn_on", entity_id=entity_id, data=data)
            results.append({"action": "light.adjust", "entity_id": entity_id, "data": data, "result": adj_result})
        except Exception as exc:
            results.append({"action": "light.adjust", "entity_id": entity_id, "error": str(exc)})

    return json.dumps({"results": results})


# ---------------------------------------------------------------------------
# turn_off_all_except
# ---------------------------------------------------------------------------

TURN_OFF_ALL_EXCEPT_SCHEMA = {
    "name": "turn_off_all_except",
    "description": (
        "Turn off all entities in a domain EXCEPT the specified entity_ids. "
        "Use this for 'goodnight' or 'leaving home' scenarios where you want "
        "to keep a few lights on while turning everything else off."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Entity domain to target (e.g. 'light', 'switch').",
            },
            "preserve": {
                "type": "array",
                "description": "Entity_ids to keep ON (e.g. ['light.nightstand', 'light.hallway']).",
                "items": {"type": "string"},
                "minItems": 0,
            },
            "area": {
                "type": "string",
                "description": (
                    "Optional area name to scope the operation. "
                    "When set, only entities in this area are turned off."
                ),
            },
        },
        "required": ["domain"],
    },
}


def _handle_turn_off_all_except(args: dict, **kw) -> str:
    """Handler for turn_off_all_except."""
    domain = args.get("domain", "")
    preserve: List[str] = args.get("preserve", []) or []
    area = args.get("area")

    # Fetch candidates
    entities = search_entities(domain=domain, area=area).get("entities", [])

    preserve_set = set(preserve)
    to_turn_off = [e["entity_id"] for e in entities if e["entity_id"] not in preserve_set]

    if not to_turn_off:
        return json.dumps({
            "results": [],
            "message": (
                f"No {domain} entities to turn off"
                + (f" in area '{area}'" if area else "")
                + (" (all in preserve list)" if preserve_set else "")
            ),
        })

    results = []
    for entity_id in to_turn_off:
        try:
            r = call_service(domain, "turn_off", entity_id=entity_id)
            results.append({"entity_id": entity_id, "ok": True})
        except Exception as exc:
            results.append({"entity_id": entity_id, "ok": False, "error": str(exc)})

    ok_count = sum(1 for r in results if r.get("ok"))
    return json.dumps({
        "results": results,
        "summary": {
            "turned_off": ok_count,
            "failed": len(results) - ok_count,
            "preserved": list(preserve_set),
        },
    })


# ---------------------------------------------------------------------------
# ha_bulk_control — parallel multi-entity control
# ---------------------------------------------------------------------------

BULK_CONTROL_SCHEMA = {
    "name": "ha_bulk_control",
    "description": (
        "Execute multiple Home Assistant service calls in parallel. "
        "Use this to turn on/off multiple lights, set all thermostats to "
        "the same temperature, or any batch operation across different entities. "
        "Each operation runs concurrently on a thread pool.\n\n"
        "Example: [{'domain': 'light', 'service': 'turn_off', 'entity_id': 'light.kitchen'}, "
        "{'domain': 'light', 'service': 'turn_off', 'entity_id': 'light.bedroom'}]"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "operations": {
                "type": "array",
                "description": "List of service calls to execute in parallel.",
                "items": {
                    "type": "object",
                    "properties": {
                        "domain": {"type": "string", "description": "Service domain (e.g. 'light')."},
                        "service": {"type": "string", "description": "Service name (e.g. 'turn_off')."},
                        "entity_id": {"type": "string", "description": "Target entity ID."},
                        "data": {
                            "type": "object",
                            "description": "Additional service data (e.g. {'brightness': 128}).",
                        },
                    },
                    "required": ["domain", "service"],
                },
                "minItems": 1,
                "maxItems": 50,
            },
        },
        "required": ["operations"],
    },
}


def _handle_bulk_control(args: dict, **kw) -> str:
    """Execute multiple HA service calls in parallel."""
    import concurrent.futures

    operations: list = args.get("operations", [])
    if not operations:
        return json.dumps({"error": "No operations provided"})

    # Group by domain+service for efficiency, but call each individually
    # for independent error reporting
    results: list = []
    futures: dict = {}

    # We reuse the existing thread pool from ha_assistant.py
    from plugins.home_assistant.ha_assistant import call_service

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(operations), 10)) as executor:
        for i, op in enumerate(operations):
            domain = op.get("domain", "")
            service = op.get("service", "")
            entity_id = op.get("entity_id")
            data = op.get("data")
            future = executor.submit(call_service, domain, service, entity_id, data)
            futures[future] = i

        for future in concurrent.futures.as_completed(futures, timeout=30):
            i = futures[future]
            try:
                result = future.result()
                results.append({
                    "op_index": i,
                    "domain": operations[i]["domain"],
                    "service": operations[i]["service"],
                    "entity_id": operations[i].get("entity_id"),
                    "ok": "error" not in result,
                    "result": result,
                })
            except Exception as exc:
                results.append({
                    "op_index": i,
                    "domain": operations[i]["domain"],
                    "service": operations[i]["service"],
                    "entity_id": operations[i].get("entity_id"),
                    "ok": False,
                    "error": str(exc),
                })

    ok_count = sum(1 for r in results if r.get("ok"))
    return json.dumps({
        "results": sorted(results, key=lambda r: r["op_index"]),
        "summary": {
            "total": len(operations),
            "succeeded": ok_count,
            "failed": len(operations) - ok_count,
        },
    })

