#!/usr/bin/env bash
# init-ollama.sh — Pull the configured cloud model on first startup.
#
# Usage:
#   docker compose up -d
#   ./scripts/init-ollama.sh
#
# This script waits for the Ollama container to be healthy, then pulls
# the model specified by OLLAMA_MODEL from the Cloud Registry.
# The :cloud tag ensures remote inference weights are fetched.
#
# Idempotent: safe to re-run. Ollama skips if model already exists.

set -euo pipefail

CONTAINER_NAME="${1:-ollama}"
MODEL="${OLLAMA_MODEL:-llama3}"
TAG="${MODEL_TAG:-cloud}"
FULL_MODEL="${MODEL}:${TAG}"
MAX_RETRIES=30
RETRY_INTERVAL=5

echo "[init-ollama] Waiting for container '${CONTAINER_NAME}' to be healthy..."

for i in $(seq 1 "$MAX_RETRIES"); do
    STATUS=$(docker inspect --format='{{.State.Health.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "not_found")
    if [ "$STATUS" = "healthy" ]; then
        echo "[init-ollama] Container is healthy."
        break
    fi
    if [ "$i" -eq "$MAX_RETRIES" ]; then
        echo "[init-ollama] ERROR: Container did not become healthy after $((MAX_RETRIES * RETRY_INTERVAL))s."
        exit 1
    fi
    echo "[init-ollama] Status: ${STATUS}. Retrying in ${RETRY_INTERVAL}s... (${i}/${MAX_RETRIES})"
    sleep "$RETRY_INTERVAL"
done

echo "[init-ollama] Checking if model '${FULL_MODEL}' is already available..."
EXISTING=$(docker exec "$CONTAINER_NAME" ollama list 2>/dev/null | grep -c "${MODEL}" || true)

if [ "$EXISTING" -gt 0 ]; then
    echo "[init-ollama] Model '${MODEL}' already cached. Skipping pull."
else
    echo "[init-ollama] Pulling model '${FULL_MODEL}' from Cloud Registry..."
    docker exec "$CONTAINER_NAME" ollama pull "$FULL_MODEL"
    echo "[init-ollama] Pull complete."
fi

echo "[init-ollama] Warming up model (loading into memory)..."
docker exec "$CONTAINER_NAME" ollama run "$FULL_MODEL" "ping" --nowordwrap 2>/dev/null || true

echo "[init-ollama] Verifying model is loaded..."
docker exec "$CONTAINER_NAME" curl -sf http://localhost:11434/api/tags | grep -q "${MODEL}" && \
    echo "[init-ollama] ✅ Model '${FULL_MODEL}' is ready." || \
    echo "[init-ollama] ⚠️  Model may not be fully loaded. Check 'docker exec ${CONTAINER_NAME} ollama list'."

echo "[init-ollama] Done."
