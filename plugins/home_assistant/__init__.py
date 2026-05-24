"""Hermes Home Assistant Plugin — P0 Foundation.

Configures the Hermes ↔ Home Assistant bridge, registers all P0 tools,
and injects entity context into sessions.

Architecture:
    Context Engine  ←  entity snapshot on session start
    Tool Registry   ←  6 tools registered at load
    Security Layer  ←  allow-list / block-list / audit log
    Compound Tools  ←  scene + light, turn-off-all-except
"""

from __future__ import annotations

import json
import logging
import os
import re
import time as _time
from typing import Any, Dict, Optional, Tuple

from plugins.home_assistant.ha_assistant import (
    call_service,
    get_entity_state,
    invalidate_cache,
    is_available,
    list_services,
    refresh_entity_cache,
    search_entities,
)
from plugins.home_assistant.compound import (
    BULK_CONTROL_SCHEMA,
    CONTROL_LIGHT_AND_SET_SCENE_SCHEMA,
    TURN_OFF_ALL_EXCEPT_SCHEMA,
    _handle_bulk_control,
    _handle_control_light_and_set_scene,
    _handle_turn_off_all_except,
)
from plugins.home_assistant.security import (
    is_entity_blocked,
    is_service_allowed,
    log_call,
)

logger = logging.getLogger(__name__)

# Entity ID regex (mirrors core homeassistant_tool.py)
_ENTITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")
_SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------------------
# Tool Availability
# ---------------------------------------------------------------------------

def _check_ha_available() -> bool:
    return is_available()


# ---------------------------------------------------------------------------
# Tool Handlers
# ---------------------------------------------------------------------------

def _handle_search_entities(args: dict, **kw) -> str:
    """ha_search_entities — find entities by name, domain, or area."""
    query = args.get("query")
    domain = args.get("domain")
    area = args.get("area")
    try:
        result = search_entities(query=query, domain=domain, area=area)
        entities = result.get("entities", [])
        # --- Disambiguation: when 3+ entities match, surface the ambiguity ---
        if len(entities) >= 3 and query:
            resolved = {e["entity_id"]: e["friendly_name"] for e in entities}
            result["disambiguation"] = {
                "needed": True,
                "entities": resolved,
                "instruction": (
                    f"Multiple entities matched '{query}'. "
                    f"Ask the user which room they mean before proceeding."
                ),
            }
        return json.dumps({"result": result})
    except Exception as exc:
        logger.error("ha_search_entities error: %s", exc)
        return json.dumps({"error": f"Failed to search entities: {exc}"})


def _handle_get_state(args: dict, **kw) -> str:
    """ha_get_state — get detailed state of a single entity."""
    entity_id = args.get("entity_id", "")
    if not entity_id:
        return json.dumps({"error": "Missing required parameter: entity_id"})
    if not _ENTITY_ID_RE.match(entity_id):
        return json.dumps({"error": f"Invalid entity_id format: {entity_id!r}"})
    try:
        state = get_entity_state(entity_id)
        if state is None:
            return json.dumps({"error": f"Entity not found: {entity_id}"})
        return json.dumps({"result": state})
    except Exception as exc:
        logger.error("ha_get_state error: %s", exc)
        return json.dumps({"error": f"Failed to get state for {entity_id}: {exc}"})


def _handle_call_service(args: dict, **kw) -> str:
    """ha_call_service — call a Home Assistant service with security gating."""
    domain = args.get("domain", "")
    service = args.get("service", "")
    if not domain or not service:
        return json.dumps({"error": "Missing required parameters: domain and service"})

    # Validate format
    if not _SERVICE_NAME_RE.match(domain):
        return json.dumps({"error": f"Invalid domain format: {domain!r}"})
    if not _SERVICE_NAME_RE.match(service):
        return json.dumps({"error": f"Invalid service format: {service!r}"})

    entity_id = args.get("entity_id")
    if entity_id and not _ENTITY_ID_RE.match(entity_id):
        return json.dumps({"error": f"Invalid entity_id format: {entity_id!r}"})

    data = args.get("data")
    if isinstance(data, str):
        try:
            data = json.loads(data) if data.strip() else None
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid JSON in 'data' parameter: {exc}"})

    # --- Security gating ---
    if entity_id and is_entity_blocked(entity_id, domain, service):
        log_call(entity_id, domain, service, data, allowed=False, reason="blocked entity")
        return json.dumps({
            "error": f"Entity '{entity_id}' is blocked by the Hermes HA security policy."
        })

    if entity_id and not is_service_allowed(entity_id, domain, service):
        log_call(entity_id, domain, service, data, allowed=False, reason="denied by allow-list")
        return json.dumps({
            "error": f"Service '{domain}.{service}' on '{entity_id}' is not in the Hermes HA allow-list."
        })

    # --- Execute ---
    try:
        result = call_service(domain, service, entity_id, data)
        log_call(entity_id, domain, service, data, allowed=True)
        return json.dumps({"result": result})
    except Exception as exc:
        logger.error("ha_call_service error: %s", exc)
        log_call(entity_id, domain, service, data, allowed=False, reason=f"error: {exc}")
        return json.dumps({"error": f"Failed to call {domain}.{service}: {exc}"})


def _handle_get_overview(args: dict, **kw) -> str:
    """ha_get_overview — summarise all entities by domain/count."""
    try:
        entities = refresh_entity_cache(force=True)
    except Exception as exc:
        return json.dumps({"error": f"Failed to refresh entity cache: {exc}"})

    # Group by domain
    domain_counts: Dict[str, int] = {}
    domain_states: Dict[str, Dict[str, int]] = {}
    for e in entities:
        entity_id = e.get("entity_id", "")
        state = e.get("state", "unknown")
        domain = entity_id.split(".", 1)[0] if "." in entity_id else entity_id
        domain_counts[domain] = domain_counts.get(domain, 0) + 1
        if domain not in domain_states:
            domain_states[domain] = {}
        domain_states[domain][state] = domain_states[domain].get(state, 0) + 1

    # Top-level summary for context efficiency
    summary = {
        "total_entities": len(entities),
        "domains": {
            dom: {"count": domain_counts[dom], "top_states": _top_n(domain_states.get(dom, {}), 5)}
            for dom in sorted(domain_counts)
        },
    }
    return json.dumps({"result": summary})


def _top_n(counter: Dict[str, int], n: int) -> Dict[str, int]:
    return dict(sorted(counter.items(), key=lambda x: x[1], reverse=True)[:n])


def _handle_list_services(args: dict, **kw) -> str:
    """ha_list_services — list available Home Assistant services."""
    domain = args.get("domain")
    try:
        result = list_services(domain=domain)
        return json.dumps({"result": result})
    except Exception as exc:
        logger.error("ha_list_services error: %s", exc)
        return json.dumps({"error": f"Failed to list services: {exc}"})


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

HA_SEARCH_ENTITIES_SCHEMA = {
    "name": "ha_search_entities",
    "description": (
        "Search Home Assistant entities by name, domain, or area. "
        "Returns entity_id, state, and friendly_name for each match."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query matching against entity_id and friendly_name.",
            },
            "domain": {
                "type": "string",
                "description": "Filter by entity domain (e.g. 'light', 'switch', 'climate').",
            },
            "area": {
                "type": "string",
                "description": "Filter by area/room name (e.g. 'living room', 'kitchen').",
            },
        },
        "required": [],
    },
}

HA_GET_STATE_SCHEMA = {
    "name": "ha_get_state",
    "description": (
        "Get the complete state and attributes of a single Home Assistant entity."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "Entity ID to query (e.g. 'light.living_room').",
            },
        },
        "required": ["entity_id"],
    },
}

HA_CALL_SERVICE_SCHEMA = {
    "name": "ha_call_service",
    "description": (
        "Call a Home Assistant service (action) to control a device. "
        "Use ha_search_entities to find entity IDs and ha_list_services to discover available services."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "description": "Service domain (e.g. 'light', 'switch', 'climate', 'media_player').",
            },
            "service": {
                "type": "string",
                "description": "Service name (e.g. 'turn_on', 'turn_off', 'set_temperature').",
            },
            "entity_id": {
                "type": "string",
                "description": "Target entity ID (e.g. 'light.living_room'). Optional for some services.",
            },
            "data": {
                "type": "string",
                "description": (
                    "Additional service data as a JSON string. "
                    'Example: {"brightness": 255} for lights, '
                    '{"temperature": 22} for climate.'
                ),
            },
        },
        "required": ["domain", "service"],
    },
}

HA_GET_OVERVIEW_SCHEMA = {
    "name": "ha_get_overview",
    "description": (
        "Get a high-level overview of all Home Assistant entities, grouped by domain "
        "with state distribution counts. Use this to understand what's in the home "
        "before issuing specific queries."
    ),
    "parameters": {"type": "object", "properties": {}},
}

HA_LIST_SERVICES_SCHEMA = {
    "name": "ha_list_services",
    "description": (
        "List available Home Assistant services (actions) for device control. "
        "Shows what actions can be performed on each device type."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "domain": {"type": "string", "description": "Filter by domain (e.g. 'light', 'climate'). Omit to list all."},
        },
        "required": [],
    },
}


# ---------------------------------------------------------------------------
# Plugin registration
# ---------------------------------------------------------------------------

_TOOLS = (
    ("ha_search_entities",       HA_SEARCH_ENTITIES_SCHEMA,         _handle_search_entities,       "🏠"),
    ("ha_get_state",             HA_GET_STATE_SCHEMA,               _handle_get_state,             "🔍"),
    ("ha_call_service",          HA_CALL_SERVICE_SCHEMA,            _handle_call_service,          "🎛️"),
    ("ha_get_overview",          HA_GET_OVERVIEW_SCHEMA,            _handle_get_overview,          "📊"),
    ("ha_list_services",         HA_LIST_SERVICES_SCHEMA,           _handle_list_services,         "📋"),
    ("control_light_and_set_scene", CONTROL_LIGHT_AND_SET_SCENE_SCHEMA, _handle_control_light_and_set_scene, "🎬"),
    ("turn_off_all_except",      TURN_OFF_ALL_EXCEPT_SCHEMA,        _handle_turn_off_all_except,   "🌙"),
    ("ha_bulk_control",          BULK_CONTROL_SCHEMA,               _handle_bulk_control,          "⚡"),
)


_WS_LISTENER_THREAD = None


def _on_session_start(**kwargs) -> None:
    """Pre-warm the entity cache on session start so the first query is fast."""
    global _WS_LISTENER_THREAD
    try:
        if is_available():
            entities = refresh_entity_cache(force=True)
            logger.info("HA entity cache pre-warmed: %d entities", len(entities))

            # Start one HA WebSocket event listener per process.
            url, token = _get_ha_creds()
            thread = _WS_LISTENER_THREAD
            if thread is None or not thread.is_alive():
                from plugins.home_assistant.event_watcher import start_ws_listener
                if url.startswith("https://"):
                    ws_url = "wss://" + url[len("https://"):]
                elif url.startswith("http://"):
                    ws_url = "ws://" + url[len("http://"):]
                else:
                    ws_url = url
                ws_url = f"{ws_url}/api/websocket"
                thread = start_ws_listener(ws_url, token)
                _WS_LISTENER_THREAD = thread
            if thread:
                logger.info("HA WS event listener active")
            else:
                logger.info("HA WS event listener skipped (no aiohttp available)")

            # --- P3: Scene/Script auto-discovery ---
            from plugins.home_assistant.discovery import discover_scenes_scripts
            discovered = discover_scenes_scripts()
            logger.info(
                "Auto-discovered %d scenes + %d scripts from HA",
                discovered.get("total_scenes", 0),
                discovered.get("total_scripts", 0),
            )

            # --- P3: Set initial status sensor values ---
            try:
                from plugins.home_assistant.status_sensors import get_status_sensors
                sensors = get_status_sensors()
                sensors.start_time = _time.monotonic()
                sensors.gateway_connected = True
                sensors.ws_connected = thread is not None
                logger.info("HA status sensors initialised")
            except Exception:
                pass
        else:
            logger.info("HA not available — skipping cache pre-warm")
    except Exception as exc:
        logger.warning("HA cache pre-warm failed (non-fatal): %s", exc)


def _get_ha_creds():
    """Return (url, token) from environment."""
    import os
    url = os.getenv("HASS_URL", "http://homeassistant.local:8123").rstrip("/")
    token = os.getenv("HASS_TOKEN", "")
    return url, token


def register(ctx) -> None:
    """Register all P0 Home Assistant tools and lifecycle hooks."""
    for name, schema, handler, emoji in _TOOLS:
        ctx.register_tool(
            name=name,
            toolset="homeassistant",
            schema=schema,
            handler=handler,
            check_fn=_check_ha_available,
            emoji=emoji,
        )
    ctx.register_hook("on_session_start", _on_session_start)
