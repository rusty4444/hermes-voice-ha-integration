# Hermes Voice Stack Plugin

Local voice pipeline for Hermes Agent.

**Wake Word → STT → LLM → TTS → HA media_player**

> ⚠️ P1 scaffold — engines are stubs. Real hardware wiring ships in the next phase.

## Architecture

```
┌─────────┐    ┌─────┐    ┌───────────┐    ┌─────┐    ┌──────────────┐
│Wake Word│ →  │ STT │ →  │Hermes Agent│ → │ TTS │ →  │HA media_player│
│ Porcupine│    │whisp│    │   LLM      │    │Piper│    │  (speaker)   │
└─────────┘    └─────┘    └───────────┘    └─────┘    └──────────────┘
```

## Engines (P1)

| Stage | Default | Alternatives |
|-------|---------|-------------|
| Wake Word | Porcupine | OpenWakeWord, Sherpa-Onix |
| STT | Whisper.cpp GGUF (base.en) | Vosk, Coqui-STT |
| TTS | PiperTTS | Edge-TTS, ElevenLabs |
| Audio sink | HA `media_player.*` | ALSA, PulseAudio |

## Latency Budget (target on RPi 5)

| Stage | Target |
|-------|--------|
| Wake Word | 250ms |
| STT | 500ms |
| Hermes LLM | 1800ms |
| TTS | 300ms |
| media_player | 80ms |
| **Total** | **~2,930ms** |

## Voice System Prompt (P1)

The voice stack injects a compact system prompt:

```
You are Hermes, a voice-controlled home assistant.
Current time: <iso_timestamp>
Home areas: <areas JSON>
Key entities: <entities JSON>

RULES:
1. Respond concisely — this is voice. One sentence when possible.
2. Use ha_call_service to control devices.
3. If ambiguous, ask a brief clarifying question.
4. Never return internal state JSON — summarise in plain English.
5. After calling a service, confirm success in ≤5 words.
```

## P1 Exit Criteria

- "Hey Hermes, turn off the living room light" → light off, TTS says "Done" within 3s
- "What's the outside temperature?" → reads correct sensor value
- Wake word false-positive rate ≤1/hour in a quiet room
- All three KWS/STT/TTS engines swappable via config only
