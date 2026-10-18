#!/usr/bin/env bash
# Check that a running Hivemind instance works end to end.
#   ./scripts/smoke_test.sh                 # http://localhost:8000
#   ./scripts/smoke_test.sh http://host:8000
set -euo pipefail
BASE="${1:-http://localhost:8000}"
fail() { echo "FAIL: $*"; exit 1; }
ok() { echo "ok   $*"; }

echo "Waiting for $BASE ..."
for i in $(seq 1 90); do
  curl -fs "$BASE/healthz" >/dev/null 2>&1 && break
  [ "$i" = 90 ] && fail "server did not become healthy"
  sleep 2
done
ok "health check"

curl -fs "$BASE/" | grep -q "Hivemind" || fail "landing page"
ok "landing page"
curl -fs "$BASE/static/vendor/vis-network.min.js" -o /dev/null || fail "bundled graph library"
curl -fs "$BASE/static/vendor/fonts.css" -o /dev/null || fail "bundled fonts"
ok "bundled assets (works offline)"

meta=$(curl -fs "$BASE/api/w/demo/meta") || fail "demo workspace"
echo "$meta" | grep -q '"Source":27' || fail "demo data not loaded: $meta"
ok "demo company loaded (27 sources)"

ans=$(curl -fs -X POST "$BASE/api/w/demo/ask" -H 'Content-Type: application/json' \
  -d '{"question":"Who should I ask about Kafka consumer lag?"}') || fail "ask"
echo "$ans" | grep -q "Tomas Silva" || fail "unexpected answer: $ans"
echo "$ans" | grep -q "DOC-3" || fail "answer missing citation"
ok "cited answer (Tomas Silva, DOC-3)"

ans=$(curl -fs -X POST "$BASE/api/w/demo/ask" -H 'Content-Type: application/json' \
  -d '{"question":"Where are our biggest knowledge risks?"}') || fail "insights"
echo "$ans" | grep -q "Key connectors" || fail "graph algorithms: $ans"
ok "knowledge risks (FalkorDB graph algorithms)"

doc=$(curl -fs -X POST "$BASE/api/w/demo/generate" -H 'Content-Type: application/json' \
  -d '{"kind":"sprint","project":"project:checkout","weeks":2}') || fail "sprint plan"
echo "$doc" | grep -q "PAY-52" || fail "sprint plan content: $doc"
ok "sprint plan (blocker PAY-52 scheduled)"

ws=$(curl -fs -X POST "$BASE/api/workspaces" -H 'Content-Type: application/json' -d '{"name":"Smoke Test Co"}') || fail "create workspace"
echo "$ws" | grep -q '"key"' || fail "workspace response: $ws"
ok "new company workspace"

echo "All smoke tests passed."
