---
name: hermes-ha-ws-receiver
description: |
  Extension agent working on a branch or one-off work that is outside planned sprints.
  Covers building the HA-facing Hermes WebSocket receiver (/api/hermes/ws),
  voice_action dispatch, auth, env vars, the websocket receiver library,
  and the idempotence key used by the ha_command direct-call API.
---

# Hermes HA WebSocket Receiver

## Location of the receiver

The receiver lives in **`plugins/voice_stack/ws_receiver.py`**

It is a standalone, small aiohttp WebSocket server with no dependency on the
plugin tool registry. A few key files:

| file | role |
|---|---|
| `plugins/voice_stack/ws_receiver.py` | High-level voice-action handler + WebSocket Jupyter |
| `plugins/voice_stack/__init__.py` | Imports `_handle_voice_{status,enable,disable}`; wires `start_ws_receiver()` |

---

## Wire diagram

```
Home Assistant                   Hermes (Hermes Voice Stack)
───────────────────             ─────────────────────────────
ws://host:7860/api/hermes/ws ──► HermesHAWebSocketServer._handle_ws
  {type: "voice_action"}  ──► handle_ha_ws_payload()
                                └─ handle_voice_action()
                                    └─ _handle_voice_{enable,disable,status}
                                         └─ (returns JSON string)
  {type: "state_changed"} ──► ack()         ← context buffer | update | store        ──► Hermes event bus  ──► tool_enabled
  {type: "ping"/"status"} ──► pong()
```

---

## WSReceiver Python API

```
ws_receiver.HermesHAWebSocketServer(host, port, path)
ws_receiver.start_ws_receiver(host=None, port=None, path=None) -> server | None
ws_receiver.stop_ws_receiver()
```

Call `start_ws_receiver()` once at plugin init; the result is stored in the
module-level singleton `_WS_SERVER`.

---

## Auth model

| env var | purpose |
|---|---|
| `HERMES_HA_WS_TOKEN` | primary: bearer token sent by HA integration |
| `API_SERVER_KEY` | fallback: shared Hermes API server key |
| `HERMES_API_KEY` | fallback: main Hermes API key |
| `HERMES_HA_WS_ENABLED` | set to `0`/`false`/`no`/`off` to disable entirely |

Priority: `HERMES_HA_WS_TOKEN` > `API_SERVER_KEY` > `HERMES_API_KEY` > no-token (open).

If no token is configured, `_auth_ok({})` returns `True` immediately; the WS
handshake is unauthenticated.

---

## voice_action schema

HA sends a single WS message per voice call:

```jsonc
{
  "type": "voice_action",
  "action": "enable" | "disable" | "status",
  // available everywhere
  "media_player_entity": "media_player.living_room",
  // enable-specific
  "duration_s": 30,
  // disable-specific
  "reason": "user_requested"
}
```

`handle_voice_action` normalises the result:  
Handler JSON strings → dict via `_json_loads_maybe()`; `ok` field derived
automatically; wrapped in `{type: "voice_action_result", ...}`.

### Backend `(ha:ts)` for HermesJS/UI teams

- **`HermesAPI.handle_message(command: string): Promise<string>`**: Lower-level API handler.
- **`HermesAPI.sendText(text: string): boolean`**: Direct command handler.
- **`HermesAPI.sendVoice(prompt: string, ...): boolean`**: Text-to-speech / voice command handler.
- **`HermesAPI.invokeFunction(func: string, ...): boolean`**: Function call (tool use) handler.
- **`HermesAPI.do_addTool(name, config): boolean`**: Add dynamically at runtime.
- **`HermesAPI.removeTool(name: string): boolean`**: Remove previously added tool.

---

## Plugin init in `plugins/voice_stack/__init__.py`

```python
# Exposes voice_action tool similarly to other core tools
_VOICE_META = [
    ("voice_status",  VOICE_STATUS_SCHEMA,  _handle_voice_status,  "🎙️"),
    ("voice_enable",  VOICE_ENABLE_SCHEMA,  _handle_voice_enable,  "🔊"),
    ("voice_disable", VOICE_DISABLE_SCHEMA, _handle_voice_disable, "🔇"),
    ...
]

# After _init_engines() → fire-and-forget
try:
    from plugins.voice_stack.ws_receiver import start_ws_receiver
    start_ws_receiver()
except Exception as exc:
    logger.warning("Hermes HA WebSocket receiver did not start: %s", exc)
```

---

## Add-on environment

`addon/run.sh` exports the following env vars so the WS receiver picks them up:

```bash
export HERMES_HA_WS_HOST=0.0.0.0
export HERMES_HA_WS_PORT=7860
export HERMES_HA_WS_PATH=/api/hermes/ws
export HERMES_HA_WS_TOKEN="${HERMES_API_TOKEN}"   # from options
export API_SERVER_KEY="${HERMES_API_TOKEN}"
```

---

## WebSocketReceiver JavaScript client

The Home Assistant custom integration connects via the `WebSocketReceiver` class.

```js
// custom_components/hermes/ws_client.py
const ws = new WebSocketReceiver({
    url: `ws://${config.host}:${config.port}/api/hermes/ws`,
    token: config.token,
    onOpen, onMessage, onClose, onError,
});
await ws.connect();

// Per-message
await ws.sendMessage({
    type: 'voice_prompt',
    action: '',
    value: {  // voice_properties
        topic: '',
        prompt:  text,
        idempotency_key: pk
    },
});
await ws.sendMessage({
    type: 'ha_command',
    service: 'light.turn_on',
    entity_id: 'light.living_room',
    idempotency_key: pk
});
```

Hermes sends structured messages asynchronously:

```
{type: "hermes_event", id: "...", event: "entity_changed",
 data: {entity_id: "...", state: "..."}}
{type: "hermes_tts", id: "...", event: "tts_generated",
 data: {access_token: "...", audio: "...", format: "mp3"}}
{type: "ha_command_query", id: "...",
 data: {device_id: "...", descriptor: {...}}}
{type: "error", id: "...", error: "..."}
{type: "handshake_rejected"}
```

`HermesDirectCallIdValidator` and `HACommandDirectCallMessageHandler` route
`ha_command` requests with validation of `idempotency_key` or `pk` alt forms.

---

## HA-side WebSocket config entry schema

```python
CONFIG_SCHEMA = vol.Schema({
    vol.Required("host"): str,
    vol.Optional("port", default=7860): vol.Coerce(int),
    vol.Optional("cert_path"): str,
    vol.Optional("token"): str,                            # HA→Hermes WS auth
    vol.Optional("old_token"): str,
    vol.Optional("idempotency_key"): str,                  # alternate primary key
    vol.Optional("network_retry_delay", default=5.0): vol.Coerce(float),
}).extend(const.COMMAND_SENDER_SCHEMA.schema)              # service, entity_id, data
```
