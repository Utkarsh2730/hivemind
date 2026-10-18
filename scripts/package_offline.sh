#!/usr/bin/env bash
# Build a single archive that installs Hivemind on a machine with NO internet access.
# Run this on a machine that has Docker and internet; copy the resulting file to the offline machine.
#   ./scripts/package_offline.sh            -> offline/hivemind-offline.tar.gz
set -euo pipefail
cd "$(dirname "$0")/.."

OUT=offline
mkdir -p "$OUT/bundle"

echo "1/4  Building the Hivemind image..."
docker compose build hivemind

echo "2/4  Pulling FalkorDB..."
docker compose pull falkordb

echo "3/4  Saving both images..."
docker save hivemind:latest falkordb/falkordb:latest | gzip > "$OUT/bundle/images.tar.gz"

echo "4/4  Adding compose file and installer..."
cp docker-compose.yml "$OUT/bundle/"
cp scripts/install_offline.sh "$OUT/bundle/install.sh"
cat > "$OUT/bundle/README.txt" <<'TXT'
Hivemind — offline install
1. Install Docker (Docker Desktop, or Docker Engine + compose plugin).
2. Run:  ./install.sh
3. Open: http://localhost:8000
Data is kept in the Docker volume "falkordb-data". Stop with: docker compose down
TXT
tar -czf "$OUT/hivemind-offline.tar.gz" -C "$OUT" bundle
rm -rf "$OUT/bundle"
echo "Done: $OUT/hivemind-offline.tar.gz ($(du -h "$OUT/hivemind-offline.tar.gz" | cut -f1))"
