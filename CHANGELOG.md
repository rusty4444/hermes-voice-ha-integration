# Changelog

All notable changes to the hermes-voice-ha-integration project.

## [0.0.8] — 2026-06-03

### Added
- **Assist conversation agent** — Hermes now registers as a selectable `Platform.CONVERSATION` agent in HA Assist pipelines. Users can set Hermes as their Preferred conversation agent under Settings → Voice assistants. ([#29](https://github.com/rusty4444/hermes-voice-ha-integration/pull/29))
- WebSocket background reader (`_ws_reader`) keeps the aiohttp heartbeat alive and routes `assist_response` messages to pending query futures.
- `MAX_QUERY_TEXT_LENGTH` (4096 chars) on conversation input to prevent oversized WebSocket frames.
- SSL+token plaintext warning when `verify_ssl=False` is combined with a Hermes token.
- WebSocket message type constants in `const.py` (`WS_TYPE_*`).
- Debug logging for `assist_response` routing in the reader.

### Changed
- `supported_languages` returns `["*"]` to indicate language-agnostic support (previously `["en"]`).
- `_connected` is set only after the reader task launches successfully (ordering fix).
- Deprecated `asyncio.get_event_loop().create_future()` replaced with `asyncio.get_running_loop().create_future()`.

### Fixed
- **Reconnection race** — old reader task is now cancelled before creating a new WebSocket connection, preventing stale readers from setting `_connected = False` on healthy connections.
- **Test stub** — `Platform.CONVERSATION` added to `test_ha_services.py` stub so tests pass.
- **Change-detector test** — `test_platform_listed` now checks for both `Platform.SENSOR` and `Platform.CONVERSATION` instead of an exact line match.

### Documentation
- New **"Hermes Agent WebSocket message types"** section in README documenting the `assist_query` / `assist_response` protocol contract.
- Troubleshooting entry for "Assist pipeline times out" with a Hermes Agent implementation checklist.
- Step 6 updated to reflect conversation agent registration.
- Known limitations bumped to v0.0.8 with the Hermes Agent server dependency noted.

## [0.0.7] — 2026-05-28

### Changed
- Fix user-plugin import loading (package-relative imports)
- README install paths updated for `~/.hermes/hermes-agent/plugins/`
- Home Assistant voice-bridge setup guidance

## [0.0.6] — 2026-05-24

### Initial release
- Home Assistant custom integration with config flow, services, sensors
- Hermes plugin for HA tools and context
- Voice stack plugin for wake-word / STT / TTS pipeline
- Lovelace action bar card
- HA add-on scaffold
