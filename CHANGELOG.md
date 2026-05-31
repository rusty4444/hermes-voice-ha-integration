# Changelog

All notable changes to `hermes-voice-ha-integration`.

## [Unreleased]

## [0.0.7] — 2026-05-31

### Added
- Added structured service responses and runtime schemas for `hermes.hermes_command` and `hermes.voice_settings`.
- Added tests for Home Assistant service response handling, voice settings queries, option wiring, and entry-scoped sensor IDs.
- Added request ID correlation, status/health telemetry, connection/message counters, and protocol documentation for the HA→Hermes WebSocket receiver.
- Added voice lifecycle tests covering richer HA action context, pipeline locking, cache directory creation, and categorized one-shot listen failures.

### Fixed
- Fixed Hermes user-plugin imports by replacing bundled `plugins.*` absolute imports with package-relative imports so `home_assistant` and `voice_stack` load correctly from Hermes plugin namespaces.
- Clarified README plugin installation paths for issue #23.
- Passed configured TTS/STT/wake-word/media-player options into the Home Assistant `HermesBridge` instead of always using bridge defaults.
- Preserved page-1 options-flow values when saving page-2 voice settings.
- Normalized wake-word options to a list consistently before storing or forwarding them.
- Scoped status sensor unique IDs by config entry to avoid collisions with multiple Hermes integrations.
- Created voice-cache directories before temporary recordings and returned stable `voice_listen` error categories for invalid durations, unavailable engines, recording failures, no speech, and transcription failures.
- Reused the voice pipeline lock across enable/disable paths so concurrent lifecycle calls cannot create multiple active pipeline instances.

## [0.0.5] — 2026-05-25

### Fixed
- Added `custom_components/hermes/translations/en.json` so Home Assistant has runtime translations for the config-flow page instead of showing raw `url` and `token` field names.
- Expanded the setup-page title, description, labels, and field help to state that the URL is the Hermes host/container endpoint and the token is the Hermes API/WebSocket token, not a Home Assistant URL or long-lived access token.

## [0.0.4] — 2026-05-25

### Fixed
- Added Home Assistant local brand assets under `custom_components/hermes/brand/` (`icon.png`, `logo.png`, `icon@2x.png`, `logo@2x.png`) generated from the README logo so the integration can serve `/api/brands/integration/hermes/icon.png` instead of showing "Icon Not Available".
- Kept the root and legacy integration icon/logo PNGs in sync with the README logo for HACS/repository contexts.

## [0.0.3] — 2026-05-25

### Added
- Added packaged logo/icon assets for HACS and Home Assistant (`icon.png`, `custom_components/hermes/icon.png`, and `custom_components/hermes/logo.png`) using the existing Hermes logo artwork.

### Changed
- Reworked the initial setup form copy so it clearly asks for the Hermes Agent machine/container URL, not the Home Assistant URL.
- Clarified that the token field expects the Hermes API/WebSocket bearer token (`HERMES_HA_WS_TOKEN`, or the API server token fallback), not a Home Assistant long-lived access token.
- Switched the setup URL field to a URL selector, the token field to a password selector, and changed the default URL example to `http://hermes.local:7860`.
- Added visual setup instructions to the README, including a field guide image and an explicit Home Assistant → Hermes connection path.

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
