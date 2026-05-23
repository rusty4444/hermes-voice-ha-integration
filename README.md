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
| C | **Hermes Voice Stack plugin** | `plugins/voice_stack/` |

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
├── __init__.py       — plugin entry: connect, register 7 tools
├── ha_assistant.py   — HAWebSocketBridge (entity cache, call_service, search, list_services)
├── plugin.yaml       — config: ha_url, ha_token, auto_discover_services
├── compound.py       — P0 compound tools (control_light_and_set_scene, turn_off_all_except)
├── security.py       — P0 allow-list, block-list, audit log, 3-layer security
└── README.md         — user-facing docs
```

### Component C — Voice Stack Plugin (`plugins/voice_stack/`)

Audio pipeline loop: Wake Word → STT → Hermes → TTS → `media_player`.

```
plugins/voice_stack/
├── __init__.py       — VoicePlugIn, 6 tools registered, engine wiring
├── pipeline.py       — VoicePipeline orchestrator, audio record/play, voice system prompt
├── engines/
│   ├── __init__.py   — engine sub-package
│   ├── tts.py        — EdgeTTS / PiperTTS / Command TTS
│   ├── stt.py        — faster-whisper / whisper-cpp / Command STT
│   └── wake_word.py  — Porcupine / OpenWakeWord / Command WW
├── audio.py          — thin shim → pipeline.py (deprecated)
├── plugin.yaml       — config: engines, confidence thresholds, media_player entity
└── README.md         — voice stack docs
```

**Registered tools (P1):**

| Tool | Description |
|------|-------------|
| `voice_status` | Show engine availability + pipeline state |
| `voice_enable` | Enable continuous voice mode (wake word + STT + TTS) |
| `voice_disable` | Disable continuous voice mode |
| `voice_speak` | TTS-only: speak text through configured engine + media_player |
| `voice_listen` | One-shot: record audio and return transcription |
| `voice_prompt` | Return the voice-optimised system prompt with HA context |

---

## Installation

### 1. Hermes Agent (already installed)

```bash
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

## P1 Voice Layer Exit Criteria

| Signal | Target | How to verify |
|--------|--------|---------------|
| "Hey Hermes, turn off the living room light" | light off, TTS says "Done" | voice_listen → ha_call_service → voice_speak |
| "What's the outside temperature?" | reads correct sensor value | voice_listen → ha_search_entities → ha_get_state → voice_speak |
| Wake word false-positive rate | ≤1/hour in quiet room | voice_status → observe wake_word.listen() |
| Engine swap | all config, no code changes | set HERMES_TTS_ENGINE=piper, restart, test again |

---

## Roadmap

| Phase | Name | Status |
|-------|------|--------|
| **P0** | Foundation | ✅ 23/23 tests, code reviewed by aeon-ultimate-xs, 5 criticals fixed |
| **P1** | Voice Layer | ✅ Engines built (TTS/STT/Wake Word), pipeline orchestrator, 47/47 tests |
| **P2** | HA Completeness | Bulk control, service auto-discovery, disambiguation, state events |
| **P3** | Advanced Features | Observability, shadow-assist, user profiles |
| **P4** | Packaging | HACS release, HA Add-on Docker image |

---

## Running Tests

```bash
cd ~/dev/hermes/hermes-voice-ha-integration
PYTHONPATH=. python -m pytest tests/ -v
```

All tests are fully mocked — no live HA instance required.

---

## License

MIT — see [`LICENSE`](LICENSE).
