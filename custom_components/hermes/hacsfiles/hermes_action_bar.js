// Hermes Action Bar — Lovelace Custom Card for hermes-voice-ha-integration
// Served as /hermes_static/hermes_action_bar.js

class HermesActionBar extends HTMLElement {
  setConfig(config) {
    this.config = config || {};
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  connectedCallback() {
    this._render();
  }

  _render() {
    if (!this.shadowRoot || !this.config) return;
    const { title = "Hermes Voice", show_status = true } = this.config;
    const safeTitle = this._escapeHtml(String(title));
    const readyState = this._getReadyState();
    this.shadowRoot.innerHTML = `
      <style>
        :host { display: block; }
        ha-card { padding: 12px 16px; }
        #bar { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
        .title { font-weight: 600; font-size: 1rem; margin-right:auto; }
        .status { display:flex; align-items:center; gap:4px; font-size: .82rem; color: var(--secondary-text-color); }
        .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
        .dot.on  { background: #4caf50; }
        .dot.off { background: #f44336; }
        button { border:0; border-radius:8px; padding:8px 10px; cursor:pointer; background:var(--secondary-background-color); color:var(--primary-text-color); }
        button.enable { color:#1b8f3a; }
        button.disable { color:#c62828; }
      </style>
      <ha-card>
        <div id="bar">
          <ha-icon icon="mdi:account-voice"></ha-icon>
          <span class="title">${safeTitle}</span>
          ${show_status ? `<span class="status"><span class="dot ${readyState.ready ? 'on' : 'off'}"></span>${readyState.label}</span>` : ''}
          <button class="enable" id="voice-enable">Enable</button>
          <button class="disable" id="voice-disable">Disable</button>
          <button id="voice-status">Status</button>
        </div>
      </ha-card>
    `;
    this.shadowRoot.getElementById("voice-enable")?.addEventListener("click", () => this._callHermes("enable"));
    this.shadowRoot.getElementById("voice-disable")?.addEventListener("click", () => this._callHermes("disable"));
    this.shadowRoot.getElementById("voice-status")?.addEventListener("click", () => this._showMoreInfo());
  }

  _getReadyState() {
    const states = this._hass?.states || {};
    const voice = states["sensor.hermes_voice_ready"] || states["binary_sensor.hermes_voice_ready"];
    const gateway = states["sensor.hermes_gateway_status"] || states["binary_sensor.hermes_gateway_status"];
    const ready = [voice?.state, gateway?.state].includes("on");
    return { ready, label: ready ? "Ready" : "Offline" };
  }

  _callHermes(action) {
    if (!this._hass) return;
    this._hass.callService("hermes", "voice_settings", { action });
  }

  _escapeHtml(value) {
    return value.replace(/[&<>"]/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
    }[char]));
  }

  _showMoreInfo() {
    const entityId = this._hass?.states?.["sensor.hermes_voice_ready"]
      ? "sensor.hermes_voice_ready"
      : "binary_sensor.hermes_voice_ready";
    this.dispatchEvent(new CustomEvent("hass-more-info", {
      bubbles: true,
      composed: true,
      detail: { entityId },
    }));
  }

  getCardSize() { return 2; }
}

if (!customElements.get("hermes-action-bar")) {
  customElements.define("hermes-action-bar", HermesActionBar);
}
console.info("HermesActionBar card loaded");
