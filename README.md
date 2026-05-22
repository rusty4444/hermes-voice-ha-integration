# Hermes × Home Assistant — Voice Stack Integration

**"Your entire smart home, controlled by your own on-device AI. No cloud. No latency. No subscription."**

A three-component integration that wires Hermes Agent to Home Assistant and adds a full
local voice stack — wake word → STT → LLM → TTS → `media_player`.

---

## Components

| # | Component | Location in repo |
|---|-----------|-----------------|
| A | **Home Assistant custom integration** | `custom_components/hermes/` |
| B | **Hermes Home Assistant plugin** | `plugins/home_assistant/` |
| C | **Hermes Voice Stack plugin** | `plugins/voice-stack/` |

---

### Component A — HA Custom Integration (`custom_components/hermes/`)

Manages the WebSocket connection between HA and Hermes, exposes HA services via a
config-entry-driven bridge, and provides dashboard UI helpers.

```
custom_components/hermes/
├── __init__.py       — WebSocket client + HermesBridge class
├── config_flow.py    — HA config-entry wizard
├── services.py       — async_register_admin_service callbacks
├── manifest.json     — HA integration manifest
├── strings.json      — UI strings for config flow
└── web/              — (P1) Action-bar dashboard card
```

**Key mechanisms:**
- Bidirectional entity sync via `entity_component.register()` for Hermes-created virtual entities
- Incoming service routing: HA config entries → Hermes `ha_call_service()` callback
- Event emission: HA calls Hermes via `conversation.process` → HA gateway

### Component B — Hermes HA Plugin (`plugins/home_assistant/`)

Wraps Component A and provides Hermes with structured thinking context about the home
state. Registers core tools at agent start.

```
plugins/home_assistant/
├── __init__.py       — plugin entry: connect, register 4 P0 tools
├── ha_assistant.py   — HAWebSocketBridge (entity cache, call_service, search)
├── plugin.yaml       — config: ha_url, ha_token, auto_discover_services
├── compound.py       — P0 compound tools (control_light_and_set_scene, turn_off_all_except)
├── security.py       — P0 allow-lister, Admin protection, audit log
└── README.md         — user-facing docs
```

### Component C — Voice Stack Plugin (`plugins/voice-stack/`)

Audio pipeline loop: Wake Word → STT → Hermes → TTS → `media_player`.

```
plugins/voice-stack/
├── __init__.py       — VoiceOrchestrator, engine wiring
├── wake_word.py      — Porcupine / OpenWakeWord / Sherpa-Onix
├── stt.py            — Whisper.cpp GGUF (base.en) / Vosk / Coqui
├── tts.py            — PiperTTS / Edge-TTS / ElevenLabs
├── audio.py          — mic capture, playback via HA media_player
├── plugin.yaml       — config: engines, confidence thresholds, device IDs
└── README.md         — voice stack docs
```

---

## Installation

### 1. Hermes Agent (already installed)

```bash
# Clone Hermes
git clone https://github.com/NousResearch/hermes-agent.git
cd hermes-agent && source .venv/bin/activate
```

### 2. Enable the HA plugin

1. Copy `plugins/home_assistant/plugin.yaml` to `~/.hermes/plugins/home_assistant/`
2. Edit config with your HA URL and Long-Lived Access Token:

```yaml
# ~/.hermes/config.yaml
plugins:
  enabled:
    - home_assistant

home_assistant:
  ha_url: "http://homeassistant.local:8123"
  ha_token: "<your-llat>"
  auto_discover_services: true
```

### 3. In Home Assistant

- Create a Long-Lived Access Token (LLAT) in your HA profile → Security.
- (P1) Install the `hermes-voice-ha-integration` custom component via HACS.

---

## P0 Exit Condition

Ask Hermes:

```
Is the living room light on?
```

→ It returns the correct state within 10s via `ha_get_state` or `ha_search_entities`.
If HA is unreachable, it responds gracefully:

```
Home Assistant is currently unavailable.
```

---

## Roadmap

| Phase | Name | Target |
|-------|------|--------|
| **P0** | Foundation | Plugin sent-up, 4-core tools, compound actions, security layer |
| **P1** | Voice Layer | Wake-word → STT → LLM → TTS → media_player |
| **P2** | HA Completeness | Bulk control, service auto-discovery, state pushed to context |
| **P3** | Advanced Features | Observability bridge, shadow-assist, user profiles |
| **P4** | Packaging | HACS release, HA Add-on Docker image |

---

## License

MIT — see [`LICENSE`](LICENSE).
