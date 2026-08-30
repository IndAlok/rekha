#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/apps/api${PYTHONPATH:+:$PYTHONPATH}"
PY="${PY:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

if [[ ! -d "$ROOT/apps/web/node_modules" ]]; then
  echo "apps/web/node_modules is missing. Run: cd apps/web && npm install"
  exit 1
fi

if [[ ! -f "$ROOT/artifacts/eval/latest.json" ]]; then
  echo "No eval report yet. Building it..."
  "$PY" -m rekha.cli eval
fi

"$PY" -m uvicorn rekha.api:app --host 0.0.0.0 --port 8080 &
API_PID=$!
cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

ok=0
for _ in $(seq 1 90); do
  if "$PY" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=1)" 2>/dev/null; then
    ok=1
    break
  fi
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "API exited before it became healthy"
    exit 1
  fi
  sleep 1
done
if [[ "$ok" != 1 ]]; then
  echo "API did not become healthy on :8080"
  exit 1
fi

cd "$ROOT/apps/web"
npm run dev -- --port 3000 --hostname 0.0.0.0
