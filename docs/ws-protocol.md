# Hermes Home Assistant WebSocket Protocol

Hermes Voice Stack exposes a small HA-facing WebSocket receiver, enabled by default at:

```text
ws://<hermes-host>:7860/api/hermes/ws
```

Set `HERMES_HA_WS_HOST`, `HERMES_HA_WS_PORT`, and `HERMES_HA_WS_PATH` to override the bind address. Set `HERMES_HA_WS_ENABLED=0` to disable it.

## Authentication

If any of these environment variables is set, HA must connect with an `Authorization` header using the `Bearer TOKEN` scheme:

1. `HERMES_HA_WS_TOKEN`
2. `API_SERVER_KEY`
3. `HERMES_API_KEY`

If none is set, the receiver accepts local unauthenticated connections. Production deployments should set `HERMES_HA_WS_TOKEN`.

## Request correlation

Every client message may include an `id` field. Hermes preserves that field in the response so HA can correlate concurrent requests.

```json
{"id":"req-1","type":"ping"}
```

```json
{"id":"req-1","type":"pong","ok":true}
```

## Message types

### `ping`

Health probe over the WebSocket channel.

Response: `pong`.

### `status`

Returns receiver health and observability data.

```json
{"id":"req-2","type":"status"}
```

```json
{
  "id": "req-2",
  "type": "status",
  "ok": true,
  "service": "hermes-ha-ws",
  "running": true,
  "uptime_seconds": 42.0,
  "auth_required": true,
  "active_connections": 1,
  "total_connections": 3,
  "message_counters": {"status": 2, "voice_action": 1},
  "host": "0.0.0.0",
  "port": 7860,
  "path": "/api/hermes/ws"
}
```

The `/health` HTTP endpoint returns the same status shape without requiring a WebSocket upgrade.

### `state_changed`

HA can push selected state changes into Hermes. Hermes acknowledges receipt; semantic ingestion can be layered on top later.

```json
{"id":"evt-1","type":"state_changed","entity_id":"light.kitchen","state":"on"}
```

Response: `ack` with the same `entity_id`.

### `voice_action`

Dispatches HA-originated voice lifecycle actions to the local voice stack.

Supported actions:

- `enable`
- `disable`
- `status`

Hermes forwards all top-level fields except `type`, `action`, and `args` into the handler args, then overlays the explicit `args` dictionary. This lets HA pass context such as `entry_id`, `media_player_entity`, `duration`, or `language` without losing future fields.

```json
{
  "id": "voice-1",
  "type": "voice_action",
  "action": "enable",
  "entry_id": "01J...",
  "media_player_entity": "media_player.living_room",
  "args": {"duration": 5}
}
```

Response type: `voice_action_result`.

## Error shape

Unsupported message types and handler failures return:

```json
{"id":"req-3","type":"error","ok":false,"error":"Unsupported message type: banana"}
```

Voice-listen errors include an `error_category` field for automation-friendly branching:

- `engine_unavailable`
- `invalid_duration`
- `cache_unavailable`
- `no_speech`
- `recording_failed`
- `transcription_failed`
