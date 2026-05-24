# Changelog

All notable changes to `hermes-voice-ha-integration`.

## [0.0.2] — 2026-05-24

### Added
- Full HA options UI: two-page config flow for the Hermes integration.
  - Page 1 — entity allow-list editor and SSL verification toggle.
  - Page 2 — voice pipeline: TTS engine + voice, STT engine + model size,
    wake-word engine + keyword(s), media player entity for TTS playback.
- Four new status sensors: `sensor.hermes_tts_voice`, `sensor.hermes_stt_engine`,
  `sensor.hermes_wake_word`, `sensor.hermes_media_player`.

### Fixed
- Fixed type errors in `ws_receiver.py` (replaced bare `Dict` with `dict`, `Mapping` from `typing`).
- Wired `handle_voice_action` dispatch to `_handle_voice_enable/disable/status` from `plugins.voice_stack`.
- Bumped all release metadata to `0.0.2` across `pyproject.toml`, `addon/config.yaml`, `manifest.json`, plugin YAMLs, tests, README, and egg-info.
- Added `TestVoiceWebSocketReceiver` test class covering state_changed, unknown type rejection, voice action dispatch, unsupported action rejection, and auth enforcement.

## [0.0.1] — 2026-05-24

### Added
- Initial public release of the Hermes × Home Assistant voice integration bundle.
- Home Assistant custom integration with config flow, services, status sensors, and Lovelace action bar.
- Hermes `home_assistant` plugin with entity search, state lookup, service calls, overview, service discovery, compound tools, bulk control, security gates, event watcher, and status sensors.
- Hermes `voice_stack` plugin with wake-word, STT, TTS, and voice-pipeline orchestration wrappers.
- Home Assistant add-on scaffold for running Hermes voice services alongside HA.

### Fixed before release
- Corrected HA integration unload lifecycle and sensor platform forwarding.
- Fixed status sensor coordinator data mapping and setup signature.
- Removed HA custom-component imports from Hermes plugin modules.
- Fixed HA WebSocket event subscription auth/protocol.
- Hardened TTS and wake-word engine edge cases.
- Reworked the Lovelace action bar to use HA's `hass` setter and real `hermes.voice_settings` service calls.
- Aligned release metadata to `0.0.1`.

## [0.3.0] — 2026-05-23 (pre-release development)

### Added
- **C1:** Sensor platform (`sensor.py`) — Hermes status metrics exposed as real HA entities (`sensor.hermes_gateway_status`, `sensor.ha_ws_connection`, etc.)
- **C2:** WebSocket auth header (Bearer token) replaces query-param token
- **C2:** `verify_ssl` option for self-signed certificate support
- **C2:** `HermesBridge.async_connect()` called during `async_setup_entry`
- **C3:** Compound tool security gate fixed — `call_service` enforces allow-list / block-list / audit log
- **C4:** `is_available()` now performs an HTTP GET to `/api/` instead of env-only check
- **services.py:** `hermes_command` + `voice_settings` services registered via native HA WebSocket
- **services.yaml:** HA developer-tools schema for both services
- **config_flow:** Entity allow-list UI step (`async_step_allowlist`)
- **homescript** skill (`skills/homescript/SKILL.md`) — natural-language HA automation language for Hermes
- **HermesActionBar** Lovelace card (`frontend.py` + `hacsfiles/hermes_action_bar.js`) — visual Settings UI for HA dashboards
- TTS retry logic (2 attempts with 500ms backoff)
- Logo (`logo.png`) — Hermes wing + home silhouette in HA navy / tech-blue
- Version bump: `pyproject.toml` 0.1.0 → 0.3.0 (aligned with manifest)

### Changed
- `PLATFORMS` from `[]` → `["sensor"]` so entity registry works
- `config_flow.py` now saves `entity_filter` + `verify_ssl` in entry data
- `async_register_services()` stub replaced with live service registration

## [0.2.0] — 2026-05-23

### Added
- Voice stack engines: Edge-TTS, Piper TTS, faster-whisper STT, whisper.cpp STT, Porcupine wake word, OpenWakeWord
- Voice pipeline orchestrator (`pipeline.py`) with configurable `VoicePipelineState`
- `ha_bulk_control` tool for parallel service calls
- EventSource (WebSocket `state_changed` listener via `event_watcher.py`)
- Entity disambiguation layer
- 6 Hermes status sensors (`status_sensors.py`)
- Scene/script auto-discovery (`discovery.py`)
- Voice latency observability (`Observability` class in `discovery.py`)

## [0.1.0] — 2026-05-22

### Added
- Initial P0 foundation:
  - HA WebSocket bridge (`ha_assistant.py`) with entity cache (30s TTL)
  - 7 core tools: `ha_search_entities`, `ha_get_state`, `ha_call_service`, `ha_get_overview`, `ha_list_services`, `control_light_and_set_scene`, `turn_off_all_except`
  - Security layer (`security.py`): file-based allow-list, block-list, JSON-line audit log
  - Compound tools (`compound.py`) with security gating
  - HA Custom Integration (`custom_components/hermes/`): config flow, manifest, strings
  - Entity ID regex validation
  - 23 tests passing
