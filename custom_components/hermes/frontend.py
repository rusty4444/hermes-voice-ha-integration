"""Lovelace card & picture-card resource: Hermes Action Bar.

Registers a custom card resource (``hacsfiles/hermes_action_bar``) with HA's
Lovelace frontend so the card appears automatically when the integration is
installed.  The card renders a compact action bar with the most-used Hermes
voice controls (enable / disable / status).

``async_get_picture_card_content`` is read by HA's WebSocket API when the
dashboard renders the card — this is the ``hacsfiles/<name>`` path that the
plan references.
"""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# The resource name used in type: custom:hermes-action-bar card config
_CARD_NAME = "hermes-action-bar"

# hacsfiles resource path  (= what appears after /hacsfiles/ in card type)
_RESOURCE_PATH = f"hacsfiles/{_CARD_NAME}"

# ---------------------------------------------------------------------------
# Lovelace card resource
# ---------------------------------------------------------------------------

def _get_card_js() -> str:
    """Return the JavaScript source for the HermesActionBar Lovelace card."""
    return r"""
// Hermes Action Bar — HA Custom Lovelace Card
// Distributed via ha-voice-ha-integration HACS package

class HermesActionBar extends HTMLElement {
  setConfig(config) {
    this.config = config;
    this.attachShadow({ mode: "open" });
  }

  connectedCallback() {
    if (!this.shadowRoot) return;
    this._render();
  }

  _render() {
    const { title = "Hermes Voice", show_status = true } = this.config;
    const shadow = this.shadowRoot;
    shadow.innerHTML = `
      <style>
        :host {
          display: flex;
          align-items: center;
          gap: 12px;
          padding: 10px 16px;
          margin: 8px 0;
          background: rgba(38, 198, 218, 0.08);
          border: 1px solid rgba(38, 198, 218, 0.25);
          border-radius: 12px;
          font-family: var(--paper-font-body1_-_font-family, sans-serif);
          color: var(--primary-text-color);
        }
        ha-icon { color: var(--primary-color); }
        sp-action-bar {
          --sp-action-bar-spacing: 4px;
          --sp-action-bar-height: 36px;
        }
        ha-card { flex: 1; }
        .status {
          display: flex;
          align-items: center;
          gap: 4px;
          font-size: 0.82rem;
          color: var(--secondary-text-color);
        }
        .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
        .dot.on  { background: #4caf50; }
        .dot.off { background: #f44336; }
      </style>
      <ha-card>
        <div id="bar">
          <ha-icon icon="mdi:account-voice"></ha-icon>
          <span class="title">${title}</span>
          ${show_status ? this._statusHtml() : ''}
          <sp-action-bar>
            <paper-button id="voice-enable" style="color:#4caf50;cursor:pointer;">
              Enable
            </paper-button>
            <paper-button id="voice-disable" style="color:#f44336;cursor:pointer;">
              Disable
            </paper-button>
            <paper-button id="voice-status" style="cursor:pointer;">
              Status
            </paper-button>
          </sp-action-bar>
        </div>
      </ha-card>
    `;
    this.shadowRoot.getElementById("voice-enable").onclick = (e) => {
      this._fire("hermes_voice_enable");
      e.stopPropagation();
    };
    this.shadowRoot.getElementById("voice-disable").onclick = (e) => {
      this._fire("hermes_voice_disable");
      e.stopPropagation();
    };
    this.shadowRoot.getElementById("voice-status").onclick = (e) => {
      this._fire("hermes_voice_status");
      e.stopPropagation();
    };
  }

  _statusHtml() {
    const ready = this.hass?.states?.entities
      ? Object.values(this.hass.states.entities).some(
          e => e.entity_id?.startsWith("sensor.hermes_") && e.state === "on"
        )
      : false;
    return `<span class="dot ${ready ? 'on' : 'off'}"></span>
            <span class="status">${ready ? 'Ready' : 'Offline'}</span>`;
  }

  _fire(method) {
    const event = new Event("hass-more-info", {
      bubbles: true,
      composed: true,
      detail: { entityId: "sensor.hermes_voice_ready" },
    });
    this.dispatchEvent(event);
    _LOGGER.info("[HermesActionBar] %s", method);
  }

  getCardSize() { return 2; }
}

customElements.define("hermes-action-bar", HermesActionBar);
"""


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
    """Register the HermesActionBar card as a Lovelace dashboard resource.

    This is the ``hacsfiles/hermes_action_bar`` entry that the plan specifies
    in ``async_get_picture_card_content``.
    """
    try:
        from homeassistant.components.lovelace import _CONF_RESOURCES as RES_KEY  # type: ignore
        from homeassistant.components.lovelace.resource import Resource  # type: ignore
    except ImportError:
        _LOGGER.debug("Lovelace resource API not available — skipping %s", _CARD_NAME)
        return

    js_source = _get_card_js().replace('"', '\\"').replace("\n", " ").strip()
    url = f"/hacsfiles/{_CARD_NAME}.js"
    resource = Resource(url, "module")
    entry_id = resource.id

    existing: dict[str, dict] = hass.data.setdefault(RES_KEY, {})
    if entry_id not in existing:
        existing[entry_id] = resource.to_dict()
        _LOGGER.info("Registered Lovelace resource: %s", url)
