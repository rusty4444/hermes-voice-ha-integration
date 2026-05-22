"""Security layer — allow-listing, admin protection, and audit logging.

P0 must-have before shipping to end-users: without this, Hermes plugged into HA
has unrestricted access to every service on every entity. This module provides:
1. Per-entity/per-service allow-listing (Hermes can only call services you whitelist)
2. Admin protection (service calls on blocked entity IDs are blocked + logged)
3. Audit log (every ha_call_service call is logged with caller context)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File-based configuration (no config schema required — just JSON files)
# ---------------------------------------------------------------------------

_ALLOW_LIST_FILE = Path(os.path.expanduser("~/.hermes/ha_allow_list.json"))
_BLOCK_LIST_FILE = Path(os.path.expanduser("~/.hermes/ha_block_list.json"))
_AUDIT_LOG_FILE  = Path(os.path.expanduser("~/.hermes/ha_audit.log"))

# In-memory caches (reload on each check so users can edit files live)
_lock = threading.Lock()


def _read_json(path: Path) -> Dict[str, Any]:
    """Read a JSON file; return {} if missing or malformed."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return {}


# ---------------------------------------------------------------------------
# Allow-list — if populated, ONLY these entity_ids × services are permitted
# ---------------------------------------------------------------------------

def get_allow_list() -> Dict[str, Any]:
    """Return the current allow-list config.

    Shape:
        {
            "enabled": false,            # false → allow everything
            "rules": [
                {"entity_id": "light.living_room", "services": ["turn_on", "turn_off"]},
                {"entity_id": "climate.*", "services": ["*"]},    # wildcard
                {"entity_id": "light.*", "services": ["turn_on", "turn_off"]},
            ]
        }
    """
    return _read_json(_ALLOW_LIST_FILE)


def is_service_allowed(entity_id: str, domain: str, service: str) -> bool:
    """Return True if the service call is permitted by the allow-list.

    When the allow-list is disabled (or empty), everything is allowed.
    """
    config = get_allow_list()
    if not config.get("enabled", False):
        return True
    rules: List[dict] = config.get("rules", [])
    if not rules:
        return True  # empty rules, allow everything

    for rule in rules:
        rule_entity = rule.get("entity_id", "")
        rule_services: List[str] = rule.get("services", [])

        # Check entity match (including wildcard prefixes like "light.*")
        if not _entity_matches(entity_id, rule_entity):
            continue

        # Check service match (full name = "domain.service")
        full_service = f"{domain}.{service}"
        for allowed in rule_services:
            if allowed == "*" or allowed == full_service or allowed == service:
                return True
    return False


def _entity_matches(entity_id: str, pattern: str) -> bool:
    """Wildcard pattern match for entity_ids. 'light.*' matches 'light.anything'."""
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return entity_id.startswith(prefix + ".") or entity_id == prefix
    return entity_id == pattern


# ---------------------------------------------------------------------------
# Block list — these entity_ids can NEVER be touched by Hermes
# ---------------------------------------------------------------------------

def get_block_list() -> Dict[str, Any]:
    """Return the current block-list config.

    Shape: {"entities": ["switch.server_power", "lock.front_door"]}
    """
    return _read_json(_BLOCK_LIST_FILE)


def is_entity_blocked(entity_id: str, domain: str, service: str) -> bool:
    """Return True if the entity is explicitly blacklisted."""
    blocked = get_block_list().get("entities", [])
    if not isinstance(blocked, list):
        return False
    return any(_entity_matches(entity_id, pat) for pat in blocked)


# ---------------------------------------------------------------------------
# Audit log — append-only, human-readable + JSON-line for tooling
# ---------------------------------------------------------------------------

def log_call(
    entity_id: Optional[str],
    domain: str,
    service: str,
    data: Optional[Dict[str, Any]],
    allowed: bool,
    reason: str = "",
) -> None:
    """Append a single ha_call_service entry to the audit log."""
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "entity_id": entity_id,
        "domain": domain,
        "service": service,
        "data": data,
        "allowed": allowed,
        "reason": reason,
    }
    try:
        _AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            with open(_AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
    except Exception as exc:
        logger.warning("Failed to write audit log: %s", exc)
