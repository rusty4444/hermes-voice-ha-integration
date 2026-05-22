# Hermes Home Assistant Plugin

Plug your Hermes Agent into Home Assistant for full smart-home control.  
**No cloud. No latency. No subscription.**

## Quick Start

1. **Get a Long-Lived Access Token** from your HA profile → Security tab.

2. **Add to your Hermes config** (`~/.hermes/config.yaml`):

```yaml
plugins:
  enabled:
    - home_assistant
```

3. **Set environment variables:**

```bash
export HASS_URL="http://homeassistant.local:8123"
export HASS_TOKEN="eyJhbGciOi..."   # your LLAT
```

4. **Restart Hermes** and ask:

```
> ha_get_overview
> ha_search_entities domain=light
> Is the living room light on?
```

## P0 Tools

| Tool | Description |
|------|-------------|
| `ha_search_entities` | Find entities by name, domain, or area |
| `ha_get_state` | Get detailed state + attributes of a single entity |
| `ha_call_service` | Call any HA service (turn_on, set_temperature, etc.) |
| `ha_get_overview` | Top-level entity summary grouped by domain |
| `ha_list_services` | List available services per domain |
| `control_light_and_set_scene` | Activate a scene AND adjust lights in one call |
| `turn_off_all_except` | Turn off everything except named entities |

## Compound Tools (P0)

### control_light_and_set_scene

Set a scene **and** fine-tune lights in one LLM round-trip:

```
> control_light_and_set_scene scene="movie night" light_adjustments=[{"entity_id": "light.kitchen", "brightness": 30}]
```

### turn_off_all_except

"Turn everything off, but keep the nightstand on":

```
> turn_off_all_except domain=light preserve=["light.nightstand", "light.hallway"]
```

## Security

Three-layer security model (all configurable via JSON files in `~/.hermes/`):

| Layer | File | Default |
|-------|------|---------|
| **Allow-list** | `ha_allow_list.json` | Disabled (allow all) |
| **Block-list** | `ha_block_list.json` | Empty (nothing blocked) |
| **Audit log** | `ha_audit.log` | All calls logged |

### Enabling the allow-list

```json
// ~/.hermes/ha_allow_list.json
{
  "enabled": true,
  "rules": [
    {"entity_id": "light.*", "services": ["turn_on", "turn_off"]},
    {"entity_id": "climate.living_room", "services": ["set_temperature", "set_hvac_mode"]}
  ]
}
```

### Blocking sensitive entities

```json
// ~/.hermes/ha_block_list.json
{
  "entities": ["switch.server_power", "lock.front_door", "cover.garage"]
}
```

## Entity Disambiguation

When multiple entities match a query, the tool returns all candidates so the LLM can ask a clarifying question:

```
> ha_search_entities query=light
→ 3 matches: light.kitchen, light.living_room, light.bedroom
→ LLM: "Which room?"
```

## Exit Condition (P0 complete)

```
> Is the bathroom light on?
→ bathroom light is off
```

Graceful fallback when HA is unreachable:

```
> is the light on?
→ Home Assistant connection is unavailable. Check HASS_URL and HASS_TOKEN.
```
