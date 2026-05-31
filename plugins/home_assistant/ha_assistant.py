"""HA Bridge — WebSocket-backed entity cache, service routing, and search.

Design decisions:
- REST-first: uses the same LLAT + HASS_URL env vars as core homeassistant_tool.py
- WebSocket is deferred to Component A (custom_components/hermes/) for bidirectional
  event push; this module uses polling for state refresh when needed.
- Entity cache is a simple dict with TTL — avoids re-fetching the entire
  state tree on every ha_search_entities call.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Lazy imports for security module (avoid circular deps at plugin load time)
_security_log_call = None
_security_is_entity_blocked = None
_security_is_service_allowed = None

def _ensure_security_imported():
    global _security_log_call, _security_is_entity_blocked, _security_is_service_allowed
    if _security_log_call is None:
        try:
            from .security import (
                is_entity_blocked as _is_blocked,
                is_service_allowed as _is_allowed,
                log_call as _log,
            )
            _security_is_entity_blocked = _is_blocked
            _security_is_service_allowed = _is_allowed
            _security_log_call = _log
        except ImportError:
            # Running standalone without full plugin context — skip security
            _security_is_entity_blocked = lambda *a, **kw: False
            _security_is_service_allowed = lambda *a, **kw: True
            _security_log_call = lambda *a, **kw: None

# ---------------------------------------------------------------------------
# Config (reads same env vars as core homeassistant_tool.py)                  
# ---------------------------------------------------------------------------

_DEFAULT_URL = "http://homeassistant.local:8123"
_ENTITY_CACHE_TTL_SECONDS = 30.0      # refresh every 30s max
_SERVICE_CACHE_TTL_SECONDS = 300.0    # services change rarely
_LIST_ENTITIES_TIMEOUT = 10.0
_GET_STATE_TIMEOUT = 8.0
_CALL_SERVICE_TIMEOUT = 12.0

# Blocked domains (mirrors core homeassistant_tool.py)
_BLOCKED_DOMAINS = frozenset({
    "shell_command",
    "command_line",
    "python_script",
    "pyscript",
    "hassio",
    "rest_command",
})


def _get_config() -> Tuple[str, str]:
    """Return (hass_url, hass_token) from environment."""
    url = os.getenv("HASS_URL", _DEFAULT_URL).rstrip("/")
    token = os.getenv("HASS_TOKEN", "")
    return url, token


# ---------------------------------------------------------------------------
# Entity cache                                                              
# ---------------------------------------------------------------------------

class EntityCache:
    """Simple in-memory cache for HA entity state with TTL."""

    def __init__(self, ttl: float = _ENTITY_CACHE_TTL_SECONDS) -> None:
        self._data: Optional[List[Dict[str, Any]]] = None
        self._fetched_at: float = 0.0
        self._ttl = ttl

    @property
    def fresh(self) -> bool:
        return self._data is not None and (time.monotonic() - self._fetched_at) < self._ttl

    def invalidate(self) -> None:
        self._data = None
        self._fetched_at = 0.0

    def set(self, entities: List[Dict[str, Any]]) -> None:
        self._data = list(entities)
        self._fetched_at = time.monotonic()

    def all(self) -> List[Dict[str, Any]]:
        if self._data is None:
            return []
        return list(self._data)

    def get(self, entity_id: str) -> Optional[Dict[str, Any]]:
        if self._data is None:
            return None
        for e in self._data:
            if e.get("entity_id") == entity_id:
                return dict(e)
        return None


_entity_cache = EntityCache()
_service_cache: Optional[List[Dict[str, Any]]] = None
_service_cache_ts: float = 0.0


# ---------------------------------------------------------------------------
# Async REST helpers                                                         
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Async bridging (mirrors tools/homeassistant_tool.py pattern)
# ---------------------------------------------------------------------------

import concurrent.futures

_THREAD_POOL = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="ha-bridge-")


def _run_async(coro):
    """Run an async coroutine from a sync handler.

    Uses a persistent thread pool to avoid creating/destroying threads on
    every call.  Mirrors the pattern in tools/homeassistant_tool.py.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        future = _THREAD_POOL.submit(asyncio.run, coro)
        return future.result(timeout=30)
    else:
        return asyncio.run(coro)


async def _async_fetch_all_entities() -> List[Dict[str, Any]]:
    """Fetch all entity states from HA REST API."""
    import aiohttp
    url, token = _get_config()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{url}/api/states", headers=headers,
            timeout=aiohttp.ClientTimeout(total=_LIST_ENTITIES_TIMEOUT),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _async_get_entity_state(entity_id: str) -> Dict[str, Any]:
    """Fetch single entity state from HA REST API."""
    import aiohttp
    url, token = _get_config()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{url}/api/states/{entity_id}", headers=headers,
            timeout=aiohttp.ClientTimeout(total=_GET_STATE_TIMEOUT),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _async_call_service(
    domain: str, service: str,
    entity_id: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Call a Home Assistant service via REST API."""
    import aiohttp
    url, token = _get_config()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload: Dict[str, Any] = {}
    if entity_id:
        payload["entity_id"] = entity_id
    if data:
        payload.update(data)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{url}/api/services/{domain}/{service}",
            headers=headers, json=payload,
            timeout=aiohttp.ClientTimeout(total=_CALL_SERVICE_TIMEOUT),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _async_list_services() -> List[Dict[str, Any]]:
    """Fetch available HA services."""
    import aiohttp
    url, token = _get_config()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{url}/api/services", headers=headers,
            timeout=aiohttp.ClientTimeout(total=15.0),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


# ---------------------------------------------------------------------------
# Public API (called by tool handlers)                                        
# ---------------------------------------------------------------------------

def refresh_entity_cache(force: bool = False) -> List[Dict[str, Any]]:
    """Ensure the entity cache is fresh; return all cached entities."""
    if force or not _entity_cache.fresh:
        try:
            entities = _run_async(_async_fetch_all_entities())
            _entity_cache.set(entities)
            logger.debug("Entity cache refreshed: %d entities", len(entities))
        except Exception as exc:
            logger.warning("Failed to refresh entity cache: %s", exc)
            if _entity_cache._data is None:
                raise  # first fetch must succeed
    return _entity_cache.all()


def get_entity_state(entity_id: str) -> Optional[Dict[str, Any]]:
    """Get a single entity's state (cache-first)."""
    cached = _entity_cache.get(entity_id)
    if cached is not None:
        return cached
    try:
        state = _run_async(_async_get_entity_state(entity_id))
        return {
            "entity_id": state["entity_id"],
            "state": state["state"],
            "attributes": state.get("attributes", {}),
            "last_changed": state.get("last_changed", ""),
            "last_updated": state.get("last_updated", ""),
        }
    except Exception as exc:
        logger.error("Failed to get state for %s: %s", entity_id, exc)
        return None


def search_entities(
    query: Optional[str] = None,
    domain: Optional[str] = None,
    area: Optional[str] = None,
) -> Dict[str, Any]:
    """Search entities by name, domain, or area.

    Returns a compact dict: {"count": N, "entities": [...]}
    Each entity entry: entity_id, state, friendly_name
    """
    entities = refresh_entity_cache()
    if domain:
        entities = [e for e in entities if e.get("entity_id", "").startswith(f"{domain}.")]
    if area:
        area_lower = area.lower()
        entities = [
            e for e in entities
            if area_lower in (e.get("attributes", {}).get("friendly_name", "") or "").lower()
            or area_lower in (e.get("attributes", {}).get("area", "") or "").lower()
        ]
    if query:
        query_lower = query.lower()
        entities = [
            e for e in entities
            if query_lower in e.get("entity_id", "").lower()
            or query_lower in (e.get("attributes", {}).get("friendly_name", "") or "").lower()
        ]

    result = []
    for e in entities:
        result.append({
            "entity_id": e["entity_id"],
            "state": e["state"],
            "friendly_name": e.get("attributes", {}).get("friendly_name", ""),
        })
    return {"count": len(result), "entities": result}


def call_service(
    domain: str,
    service: str,
    entity_id: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
    *,
    _skip_security: bool = False,
) -> Dict[str, Any]:
    """Call a Home Assistant service. Returns HA's response dict.

    Security gating is ALWAYS enforced here (allow-list, block-list, audit
    log) so that compound tools and any future code paths cannot bypass it.
    The ``_skip_security`` parameter exists only for tests; it MUST NOT be
    set to True in production code.
    """
    import threading as _threading

    # --- Blocked domains (system-wide) ---
    if domain in _BLOCKED_DOMAINS:
        return {"error": f"Service domain '{domain}' is blocked for security."}

    # --- Security gating (allow-list + block-list + audit) ---
    if not _skip_security:
        _ensure_security_imported()
        assert _security_log_call is not None
        if entity_id and _security_is_entity_blocked(entity_id, domain, service):
            _security_log_call(entity_id, domain, service, data, allowed=False, reason="blocked entity")
            return {
                "error": f"Entity '{entity_id}' is blocked by the Hermes HA security policy."
            }
        if entity_id and not _security_is_service_allowed(entity_id, domain, service):
            _security_log_call(entity_id, domain, service, data, allowed=False, reason="denied by allow-list")
            return {
                "error": f"Service '{domain}.{service}' on '{entity_id}' is not in the Hermes HA allow-list."
            }

    # --- Execute ---
    try:
        result = _run_async(_async_call_service(domain, service, entity_id, data))
        if not _skip_security:
            try:
                _security_log_call(entity_id, domain, service, data, allowed=True)
            except Exception:
                pass
    except Exception as exc:
        logger.error("ha_call_service error: %s", exc)
        if not _skip_security:
            try:
                _security_log_call(entity_id, domain, service, data, allowed=False, reason=f"error: {exc}")
            except Exception:
                pass
        return {"error": f"Failed to call {domain}.{service}: {exc}"}

    # Invalidate entity cache so subsequent reads are fresh
    if entity_id:
        _entity_cache.invalidate()

    return result


def list_services(domain: Optional[str] = None) -> Dict[str, Any]:
    """List available HA services, optionally filtered by domain."""
    global _service_cache, _service_cache_ts
    now = time.monotonic()
    if _service_cache is not None and (now - _service_cache_ts) < _SERVICE_CACHE_TTL_SECONDS:
        services = list(_service_cache)
    else:
        services = _run_async(_async_list_services())
        _service_cache = services
        _service_cache_ts = now

    if domain:
        services = [s for s in services if s.get("domain") == domain]

    result = []
    for svc_domain in services:
        d = svc_domain.get("domain", "")
        domain_services = {}
        for svc_name, svc_info in svc_domain.get("services", {}).items():
            svc_entry: Dict[str, Any] = {"description": svc_info.get("description", "")}
            fields = svc_info.get("fields", {})
            if fields:
                svc_entry["fields"] = {
                    k: v.get("description", "")
                    for k, v in fields.items()
                    if isinstance(v, dict)
                }
            domain_services[svc_name] = svc_entry
        result.append({"domain": d, "services": domain_services})

    return {"count": len(result), "domains": result}


def is_available() -> bool:
    """Check if HA is reachable with a short HTTP ping; falls back to env check."""
    import urllib.request
    url, token = _get_config()
    if not token:
        return False  # no token, no point pinging
    try:
        req = urllib.request.Request(
            f"{url}/api/",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return resp.status < 400
    except Exception:
        return False


def invalidate_cache() -> None:
    """Force next call to re-fetch."""
    _entity_cache.invalidate()
    global _service_cache_ts
    _service_cache_ts = 0.0
