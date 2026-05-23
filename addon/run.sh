#!/usr/bin/env bash
# Hermes Voice Assistant — HA Add-on entrypoint
set -euo pipefail

# Read options passed by HA Supervisor via /data/options.json
HA_URL="$(jq -r '.ha_url // "http://homeassistant.local:8123"' /data/options.json)"
HERMES_MODEL="$(jq -r '.hermes_model // "qwen2.5:3b"' /data/options.json)"
HERMES_PROVIDER="$(jq -r '.hermes_llm_provider // "ollama"' /data/options.json)"
LLM_URL="$(jq -r '.hermes_llm_url // "http://ollama:11434/v1"' /data/options.json)"
STT_ENGINE="$(jq -r '.stt_engine // "faster-whisper"' /data/options.json)"
STT_MODEL="$(jq -r '.stt_model // "tiny"' /data/options.json)"
TTS_ENGINE="$(jq -r '.tts_engine // "edge"' /data/options.json)"
TTS_VOICE="$(jq -r '.tts_voice // "en-US-AriaNeural"' /data/options.json)"
WAKE_WORD="$(jq -r '.wake_word // "computer"' /data/options.json)"
MEDIA_PLAYER="$(jq -r '.media_player_entity // ""' /data/options.json)"
LOG_LEVEL="$(jq -r '.log_level // "info"' /data/options.json)"

# Export for Hermes + plugins
export HASS_URL="${HA_URL}"
export HASS_TOKEN="${SUPERVISOR_TOKEN}"
export HERMES_MODEL="${HERMES_MODEL}"
export HERMES_PROVIDER="${HERMES_PROVIDER}"
export HERMES_LLM_URL="${LLM_URL}"
export HERMES_STT_ENGINE="${STT_ENGINE}"
export HERMES_STT_MODEL="${STT_MODEL}"
export HERMES_TTS_ENGINE="${TTS_ENGINE}"
export HERMES_TTS_VOICE="${TTS_VOICE}"
export HERMES_WAKE_WORD="${WAKE_WORD}"
export HERMES_MEDIA_PLAYER="${MEDIA_PLAYER}"
export HERMES_LOG_LEVEL="${LOG_LEVEL}"

# Activate virtual environment
source /opt/hermes-agent/.venv/bin/activate

echo "╔══════════════════════════════════════════╗"
echo "║  Hermes Voice Assistant — HA Add-on    ║"
echo "╠══════════════════════════════════════════╣"
echo "║  HA URL:     ${HA_URL}"
echo "║  Provider:   ${HERMES_PROVIDER}"
echo "║  Model:      ${HERMES_MODEL}"
echo "║  STT:        ${STT_ENGINE} (${STT_MODEL})"
echo "║  TTS:        ${TTS_ENGINE} (${TTS_VOICE})"
echo "║  Wake Word:  ${WAKE_WORD}"
echo "╚══════════════════════════════════════════╝"

# Start Hermes Agent in gateway mode
exec python -m hermes_gateway \
    --provider "${HERMES_PROVIDER}" \
    --model "${HERMES_MODEL}" \
    --plugins home_assistant,voice_stack \
    --host 0.0.0.0 \
    --port 7860 \
    --log-level "${LOG_LEVEL}"
