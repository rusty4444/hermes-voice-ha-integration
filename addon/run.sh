#!/usr/bin/env bash
# Hermes Voice Assistant — HA Add-on entrypoint
set -euo pipefail

# Read options passed by HA Supervisor via /data/options.json
HA_URL="$(jq -r '.ha_url // "http://homeassistant.local:8123"' /data/options.json)"
HERMES_API_TOKEN="$(jq -r '.hermes_api_token // ""' /data/options.json)"
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
export HOME="/data/hermes"
export HERMES_HOME="/data/hermes"
export HERMES_VOICE_CACHE="/data/hermes/voice_cache"
export HASS_URL="${HA_URL}"
export HASS_TOKEN="${SUPERVISOR_TOKEN}"
export HERMES_HA_WS_HOST="0.0.0.0"
export HERMES_HA_WS_PORT="7860"
export HERMES_HA_WS_PATH="/api/hermes/ws"
export HERMES_HA_WS_TOKEN="${HERMES_API_TOKEN}"
export API_SERVER_KEY="${HERMES_API_TOKEN}"
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
echo "║  WS API:     :7860/api/hermes/ws"
echo "║  Provider:   ${HERMES_PROVIDER}"
echo "║  Model:      ${HERMES_MODEL}"
echo "║  STT:        ${STT_ENGINE} (${STT_MODEL})"
echo "║  TTS:        ${TTS_ENGINE} (${TTS_VOICE})"
echo "║  Wake Word:  ${WAKE_WORD}"
echo "╚══════════════════════════════════════════╝"

# Start Hermes gateway in foreground. Runtime configuration is read from
# HERMES_HOME=/data/hermes, /data/options.json-derived environment variables,
# and any config.yaml the user mounts/creates in /data/hermes.
exec hermes gateway run
