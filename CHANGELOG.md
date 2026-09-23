# Changelog

All notable changes to the hermes-voice-ha-integration project.

## [Unreleased]

### Fixed
- The bundled Hermes `voice_stack` plugin no longer warns `address already in use` on port 7860 when another Hermes process for the same profile already serves it. The receiver is a process-wide singleton, but every Hermes process that loads the plugin (gateway, CLI session, dashboard) re-imports the module with fresh globals and re-attempted the bind, logging a failure for a port the first process was serving correctly. `start_ws_receiver` now probes the port first and, when the receiver's own unauthenticated `/health` payload identifies both the service and the same opaque profile identity, logs an informational duplicate instead. A foreign service, different or unidentified profile, or different path remains a visible configuration conflict. Identity is taken from the health payload rather than the HTTP status, since a protected foreign API answers 401 and an unrelated upgrade endpoint answers 426. ([#47](https://github.com/rusty4444/hermes-voice-ha-integration/pull/47), thanks Joel Silva [@byjaps](https://github.com/byjaps).)
- The in-process receiver record is now owner-scoped: it carries the module file, active Hermes profile, bind config and pid. Another profile's plugin no longer adopts a receiver it did not start (nor can `stop_ws_receiver()` stop it), and every fresh module import rebinds instead of being served by an object still bound to the previous module's globals, PluginContext and assist handler. Wildcard binds are probed on both loopback addresses so an IPv6-only receiver is recognised.
- The receiver thread now preserves the owning profile's ContextVar scope, and receiver enablement, bind settings and authentication token resolve through Hermes' profile-scoped secret environment. Assist callbacks and WebSocket authentication therefore use the owning profile instead of the process launch profile, while resolver failures remain fail-closed under multiplexing.
- Plugin unload, disable and forced reload now cancel in-flight Assist requests, close active Home Assistant WebSockets before cleaning up the listener, terminate the receiver thread, and release its captured assist handler. Connection bookkeeping is also released when a peer resets during the initial `hello` write. This prevents a client or model request remaining attached to an orphaned stale receiver after the replacement has bound.
- `HermesHAWebSocketServer.running` no longer reports `True` after a failed bind. It was judged on the startup event, which is set for both outcomes (the caller must not wait forever), so during a failed bind — while the thread was still inside its cleanup — the property reported a live receiver and `start_ws_receiver` handed back a dead server. Liveness now requires a dedicated "bound and serving" event.

## [0.0.14] — 2026-09-21

### Added
- **Local Home Assistant intent handling (opt-in)** — new **Local HA intent handling** option (`off` / `answers` / `commands`, default `off`). `answers` mode uses HA's strict intent dispatcher with a pre-execution allow-list of known read-only query intents, returning results such as room temperature, entity state, date/time, or timer status in milliseconds. `commands` mode additionally executes recognised house-command intents matched on the intact transcript. Both modes bypass sentence-trigger automations inside the integration path; requests handled locally bypass the Hermes plugin's allow-list, block-list, and audit log. ([#46](https://github.com/rusty4444/hermes-voice-ha-integration/pull/46), thanks @byjaps.)
- Behavioural coverage for local-intent safety, exact Hermes-payload preservation, non-speech-marker cleanup, multi-clause preservation, options-flow persistence, and the shared query timeout.

### Fixed
- Made frontend static-route registration idempotent so reloading the config entry on Home Assistant 2026.9+ does not abort setup with aiohttp's duplicate GET route error. ([#44](https://github.com/rusty4444/hermes-voice-ha-integration/pull/44); addresses [#43](https://github.com/rusty4444/hermes-voice-ha-integration/issues/43), reported by @EdwardMoyse.)
- Added explicit reconnect-task ownership, retry backoff, and WebSocket/session cleanup so failed reconnects and shutdowns do not leak resources. ([#42](https://github.com/rusty4444/hermes-voice-ha-integration/pull/42), thanks @byjaps.)
- Local intent processing no longer executes sentence-trigger automations, truncates requests into different commands, alters Hermes fallback payloads, or dispatches a command twice after a post-side-effect HA failure.
- `answers` mode filters by recognised read-only intent name before execution and correctly returns HA date, time, and timer handlers even when they report `ACTION_DONE`.
- Oversized transcripts are rejected before local or Hermes processing rather than silently truncated.
- The Assist query timeout is consistently 45 seconds in both runtime behaviour and its error message.

### Documentation
- Clarified that the integration-level local-intent setting does not disable HA's upstream sentence-trigger automations or **Prefer handling commands locally** pipeline option.
- Corrected the Hermes plugin check and WebSocket test commands.
- Synchronised release metadata across the Python package, HACS manifest, add-on config, and bundled Hermes plugins.

## [0.0.13] — 2026-07-11

### Documentation
- Clarified how this project coexists with Hermes Agent's bundled Home Assistant integration. ([#39](https://github.com/rusty4444/hermes-voice-ha-integration/pull/39)).

## [0.0.12] — 2026-06-26

### Fixed
- Bumped release metadata across the Python package, HACS manifest, add-on config, and bundled Hermes plugins so users can install a version newer than the stale `v0.0.11` tag.
- Documented the current install tag for the Hermes-side `assist_query` receiver added in PR #35, avoiding the Home Assistant Assist timeout path reported in issue #33.

## [0.0.10] — 2026-06-15

### Added
- Packaged `hermes-ha-install-plugins` command for installing the bundled Hermes Agent plugins from the Python wheel or a direct GitHub pip install.
- Installer tests covering replacement of existing plugin directories and dry-run behaviour.

### Changed
- Documented the pip-based plugin install and upgrade path, including why existing plugin directories are replaced to avoid stale files.
- Release metadata is now synchronised across the Python package, HACS manifest, add-on config, and plugin manifests.

## [0.0.9] — 2026-06-14

### Fixed
- **Conversation agent unselectable on HA 2026.6+** — `supported_languages` now returns the plain string `"*"` instead of the list `["*"]`, matching HA 2026.6+'s expectation for the wildcard language marker. The list form caused the agent to appear greyed out in the Assist pipeline dropdown. ([#31](https://github.com/rusty4444/hermes-voice-ha-integration/pull/31), reported by @AlexPla in [#28](https://github.com/rusty4444/hermes-voice-ha-integration/issues/28))

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
