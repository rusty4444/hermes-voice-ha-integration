// Hermes Action Bar — Lovelace Custom Card for hermes-voice-ha-integration
// Served as /hacsfiles/hermes_action_bar.js

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
        ha-card { flex: 1; }
        .title { font-weight: 600; font-size: 1rem; margin: 0 4px; }
        .status { display:flex; align-items:center; gap:4px; font-size: .82rem; color: var(--secondary-text-color); }
        .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
        .dot.on  { background: #4caf50; }
        .dot.off { background: #f44336; }
      </style>
      <ha-card>
        <div id="bar">
          <ha-icon icon="mdi:account-voice"></ha-icon>
          <span class="title">${title}</span>
          ${show_status ? this._statusHtml() : ''}
          <action-bar-button id="voice-enable" style="color:#4caf50;">Enable</action-bar-button>
          <action-bar-button id="voice-disable" style="color:#f44336;">Disable</action-bar-button>
          <action-bar-button id="voice-status">Status</action-bar-button>
        </div>
      </ha-card>
    `;
    this.shadowRoot.getElementById("voice-enable") &&
      (this.shadowRoot.getElementById("voice-enable").onclick = () =>
        this._fire("hermes_voice_enable"));
    this.shadowRoot.getElementById("voice-disable") &&
      (this.shadowRoot.getElementById("voice-disable").onclick = () =>
        this._fire("hermes_voice_disable"));
    this.shadowRoot.getElementById("voice-status") &&
      (this.shadowRoot.getElementById("voice-status").onclick = () =>
        this._fire("hermes_voice_status"));
  }

  _statusHtml() {
    const h = window?.hass;
    if (!h) return '';
    const ready = Object.values(h.states || {}).some(
      e => (e.entity_id || '').startsWith('sensor.hermes_') && e.state === 'on',
    );
    return `<span class="dot ${ready ? 'on' : 'off'}"></span>
            <span class="status">${ready ? 'Ready' : 'Offline'}</span>`;
  }

  _fire(method) {
    const h = window?.hass;
    if (!h) return;
    h.callService('homeassistant', 'toggle', {
      entity_id: 'sensor.hermes_voice_ready',
    });
    console.info('[HermesActionBar]', method);
  }

  getCardSize() { return 2; }
}

customElements.define("hermes-action-bar", HermesActionBar);
console.info("HermesActionBar card loaded");
