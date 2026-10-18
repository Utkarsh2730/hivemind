#!/usr/bin/env bash
# Install and start Hivemind from the offline bundle (no internet needed).
set -euo pipefail
cd "$(dirname "$0")"

command -v docker >/dev/null || { echo "Docker is required. Install Docker Desktop or Docker Engine first."; exit 1; }

echo "Loading images (this can take a minute)..."
gunzip -c images.tar.gz | docker load

# The app image is prebuilt, so start without building.
docker compose up -d --no-build

echo "Waiting for Hivemind to start..."
for i in $(seq 1 60); do
  if curl -fs "http://localhost:${HIVEMIND_PORT:-8000}/healthz" >/dev/null 2>&1; then
    echo "Hivemind is running: http://localhost:${HIVEMIND_PORT:-8000}"
    exit 0
  fi
  sleep 2
done
echo "Hivemind did not answer yet. Check logs with: docker compose logs hivemind"
exit 1
