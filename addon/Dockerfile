# Hermes Voice Assistant — HA Add-on Dockerfile
#
# Multi-stage build: install Hermes Agent + voice engines + HA plugin
# on the HA base image for both amd64 and aarch64.

ARG BUILD_FROM
FROM ${BUILD_FROM}

# ---------------------------------------------------------------------------
# System dependencies
# ---------------------------------------------------------------------------
RUN apk add --no-cache \
    python3 \
    py3-pip \
    py3-virtualenv \
    ffmpeg \
    alsa-lib-dev \
    portaudio-dev \
    git \
    curl \
    jq

# ---------------------------------------------------------------------------
# Clone Hermes Agent (or use local dev path)
# ---------------------------------------------------------------------------
WORKDIR /opt
ARG HERMES_REPO=https://github.com/NousResearch/hermes-agent.git
ARG HERMES_REF=main
RUN git clone --depth 1 --branch ${HERMES_REF} ${HERMES_REPO} hermes-agent

# ---------------------------------------------------------------------------
# Python virtual environment with voice stack deps
# ---------------------------------------------------------------------------
WORKDIR /opt/hermes-agent
RUN python3 -m venv .venv && \
    .venv/bin/pip install --upgrade pip setuptools wheel && \
    .venv/bin/pip install \
    aiohttp>=3.9 \
    pydantic>=2.0 \
    edge-tts>=6.1 \
    sounddevice>=0.4 \
    numpy>=1.26 \
    faster-whisper>=1.0

# Optional: Piper TTS (offline)
# RUN .venv/bin/pip install piper-tts && \
#     mkdir -p /opt/voices && \
#     curl -L "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx" -o /opt/voices/en_US-lessac-medium.onnx

# Optional: Porcupine wake word
# RUN .venv/bin/pip install pvporcupine pyaudio

# ---------------------------------------------------------------------------
# Install Hermes HA integration plugin
# ---------------------------------------------------------------------------
COPY plugins/ /opt/hermes-agent/plugins/
COPY custom_components/ /opt/hermes-agent/custom_components/

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
COPY addon/run.sh /opt/run.sh
RUN chmod +x /opt/run.sh

# Hermes config directory
RUN mkdir -p /data/hermes /data/hermes/logs /data/hermes/voice_cache
ENV HERMES_HOME=/data/hermes
ENV HERMES_VOICE_CACHE=/data/hermes/voice_cache

EXPOSE 7860
ENTRYPOINT ["/opt/run.sh"]
