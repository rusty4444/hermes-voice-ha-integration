"""Lovelace card resource for the Hermes Action Bar."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# The resource name used in type: custom:hermes-action-bar card config
_CARD_NAME = "hermes-action-bar"

# hacsfiles resource path  (= what appears after /hacsfiles/ in card type)
_STATIC_URL = "/hermes_static/hermes_action_bar.js"

# ---------------------------------------------------------------------------
# Lovelace card resource
# ---------------------------------------------------------------------------

def _get_card_js() -> str:
    """Return the JavaScript source for the HermesActionBar Lovelace card."""
    card_path = Path(__file__).parent / "hacsfiles" / "hermes_action_bar.js"
    return card_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# HA frontend hooks
# ---------------------------------------------------------------------------

async def async_get_lovelace_card(
    hass,  # HomeAssistant
    card_type: str,
) -> dict | None:
    """Return card definition for custom:hermes-action-bar."""
    if card_type != _CARD_NAME:
        return None
    return {
        "type": "custom:hermes-action-bar",
        "title": "Hermes Voice",
        "show_status": True,
    }


async def async_get_picture_card_content(
    hass,
    card_type: str,
) -> str | None:
    """Return the JS resource snippet for the HermesActionBar card.

    HA Lovelace reads this when it encounters type: ``custom:hermes-action-bar``
    in a dashboard card config.  The returned string is served verbatim as
    ``/hacsfiles/hermes_action_bar/hermes_action_bar.js``.
    """
    if card_type not in (f"hacsfiles/{_CARD_NAME}", _CARD_NAME):
        return None
    return _get_card_js()


async def async_register_resources(hass) -> None:
    """Serve and register the HermesActionBar card as a dashboard resource."""
    static_path = Path(__file__).parent / "hacsfiles" / "hermes_action_bar.js"
    await hass.http.async_register_static_paths([
        StaticPathConfig(_STATIC_URL, str(static_path), cache_headers=True)
    ])

    try:
        from homeassistant.components.lovelace import _CONF_RESOURCES as RES_KEY  # type: ignore
        from homeassistant.components.lovelace.resource import Resource  # type: ignore
    except ImportError:
        _LOGGER.debug("Lovelace resource API not available — static card served at %s", _STATIC_URL)
        return

    resource = Resource(_STATIC_URL, "module")
    entry_id = resource.id
    existing: dict[str, dict] = hass.data.setdefault(RES_KEY, {})
    if entry_id not in existing:
        existing[entry_id] = resource.to_dict()
        _LOGGER.info("Registered Lovelace resource: %s", _STATIC_URL)
