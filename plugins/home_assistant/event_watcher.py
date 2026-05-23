"""HA Event Watcher — propagates state_changed events to Hermes tool context.

P2: Uses the running aiohttp event listener from the HA WebSocket bridge.
If the WebSocket connection is not yet wired (P0 stub mode), this module
falls back to a short-polling loop on the entity cache.

Both paths use the same EventSource interface, so callers don't care which
back-end is active.

Design
------
EventSource observers are called with a StateChangedEvent on every HA state
change.  The main Hermes agent augments its context window with the recent
event stream, giving the LLM visibility into device state changes without
polling.

Propagation latency target: <200ms from HA event → Hermes context (WebSocket
path); up to 30s on the fallback poll path.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data class for state change events
# ---------------------------------------------------------------------------

@dataclass
class StateChangedEvent:
    """A single Home Assistant state_changed event."""
    entity_id: str
    old_state: Optional[str]
    new_state: Optional[str]
    attributes_diff: Dict[str, Any] = field(default_factory=dict)
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "old_state": self.old_state,
            "new_state": self.new_state,
            "attributes_diff": self.attributes_diff,
            "ts": self.ts,
        }


# ---------------------------------------------------------------------------
# Event Source
# ---------------------------------------------------------------------------

class EventSource:
    """Observable event source for HA state_changed events.

    Usage:
        source = EventSource()
        source.subscribe(callback)           # register observer
        source.emit(event)                   # fire event to all subscribers
        source.get_events(max_age_seconds=60) # snapshot recent events
    """

    def __init__(self, max_events: int = 500) -> None:
        self._subscribers: Dict[int, Callable[[StateChangedEvent], None]] = {}
        self._events: List[StateChangedEvent] = []
        self._max_events = max_events
        self._lock = threading.Lock()
        self._next_id = 0

    def subscribe(self, callback: Callable[[StateChangedEvent], None]) -> int:
        """Register an observer. Returns a subscriber ID for unsubscribe."""
        with self._lock:
            sid = self._next_id
            self._next_id += 1
            self._subscribers[sid] = callback
            return sid

    def unsubscribe(self, sid: int) -> None:
        """Remove a previously registered observer."""
        with self._lock:
            self._subscribers.pop(sid, None)

    def emit(self, event: StateChangedEvent) -> None:
        """Fire event to all subscribers + append to history."""
        with self._lock:
            self._events.append(event)
            if len(self._events) > self._max_events:
                self._events = self._events[-self._max_events:]
            subscribers = list(self._subscribers.values())
        for cb in subscribers:
            try:
                cb(event)
            except Exception:
                logger.warning("EventSource subscriber raised an error", exc_info=True)

    def get_events(
        self,
        entity_id: Optional[str] = None,
        max_age_seconds: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Return recent events as dicts, optionally filtered."""
        with self._lock:
            now = time.time()
            events = list(self._events)
        result = []
        for ev in events:
            if entity_id and ev.entity_id != entity_id:
                continue
            if max_age_seconds is not None:
                ev_ts = datetime.fromisoformat(ev.ts.replace("Z", "+00:00")).timestamp()
                if now - ev_ts > max_age_seconds:
                    continue
            result.append(ev.to_dict())
        return result

    def clear(self) -> None:
        """Drop all stored events."""
        with self._lock:
            self._events.clear()


# ---------------------------------------------------------------------------
# Shared event source singleton
# ---------------------------------------------------------------------------

# Module-level singleton; Grabs onto start of Hermes session.
_event_source: Optional[EventSource] = None


def get_event_source() -> EventSource:
    """Return (or create) the module-level EventSource singleton."""
    global _event_source
    if _event_source is None:
        _event_source = EventSource()
    return _event_source


# ---------------------------------------------------------------------------
# WebSocket Event Listener (connects to HA WebSocket)
# ---------------------------------------------------------------------------

def start_ws_listener(ws_url: str, ha_token: str) -> Optional[threading.Thread]:
    """Start a background thread that listens for HA WebSocket events.

    Returns the thread. Call thread.join() to stop it (or set stop_event).
    Requires aiohttp installed.

    This connects to the same HA WebSocket the bridge uses, making subscription
    to specific service calls cheaper than full polling.
    """
    try:
        import aiohttp
    except ImportError:
        logger.warning("aiohttp not installed — HA WS event listener unavailable")
        return None

    source = get_event_source()
    stop_evt = threading.Event()

    def _run() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_ws_loop(ws_url, ha_token, source, stop_evt))
        except Exception:
            logger.warning("HA WS listener thread exited", exc_info=True)
        finally:
            loop.close()

    thread = threading.Thread(target=_run, daemon=True, name="ha-ws-listener")
    thread.start()
    return thread


async def _ws_loop(
    ws_url: str,
    ha_token: str,
    source: EventSource,
    stop_evt: threading.Event,
) -> None:
    """Async WebSocket listener — runs in background thread."""
    import aiohttp  # lazy import

    headers = {
        "Authorization": f"Bearer {ha_token}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url, headers=headers) as ws:
            logger.info("HA WS event listener connected")

            # Subscribe to state_changed events
            sub_id = await ws.send_json({
                "id": 1,
                "type": "subscribe",
                "event_type": "state_changed",
            })

            while not stop_evt.is_set():
                try:
                    msg = await asyncio.wait_for(ws.receive_json(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                except Exception as exc:
                    logger.warning("HA WS listener error: %s", exc)
                    break

                if msg.get("event_type") == "state_changed":
                    data = msg.get("data", {})
                    entity_id = data.get("entity_id", "")
                    new_state = data.get("new_state") or {}
                    old_state = data.get("old_state") or {}
                    source.emit(StateChangedEvent(
                        entity_id=entity_id,
                        old_state=old_state.get("state"),
                        new_state=new_state.get("state"),
                        attributes_diff=_diff_attrs(
                            old_state.get("attributes", {}),
                            new_state.get("attributes", {}),
                        ),
                    ))

        logger.info("HA WS event listener disconnected")


def _diff_attrs(old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
    """Return only the changed/added attributes between old and new."""
    diff: Dict[str, Any] = {}
    all_keys = set(old) | set(new)
    for k in all_keys:
        if old.get(k) != new.get(k):
            diff[k] = {"old": old.get(k), "new": new.get(k)}
    return diff


# ---------------------------------------------------------------------------
# Context Injection
# ---------------------------------------------------------------------------

def build_event_context(max_events: int = 10, max_age_seconds: float = 60.0) -> Dict[str, Any]:
    """Build a compact event summary for injection into Hermes context.

    Call this from the Hermes agent loop on each turn to surface recent
    HA events to the LLM.
    """
    source = get_event_source()
    events = source.get_events(max_age_seconds=max_age_seconds)
    events = events[-max_events:]  # last N

    if not events:
        return {"events": [], "summary": "no_recent_events"}

    # Summarise: group by entity_id, dedupe repeated states
    recent_changes: Dict[str, Dict[str, Any]] = {}
    for ev in events:
        key = ev["entity_id"]
        if key not in recent_changes:
            recent_changes[key] = ev
        else:
            # Keep the latest event for this entity
            recent_changes[key] = ev

    grouped: Dict[str, List[str]] = {"last_5min": []}
    for key, ev in sorted(recent_changes.items()):
        grouped["last_5min"].append(
            f"{ev['entity_id']}: {ev['old_state']} → {ev['new_state']}"
        )

    return {
        "events": events,
        "summary": "recent_state_changes",
        "grouped": grouped,
    }


import asyncio  # noqa: E402 (needed for _ws_loop)
