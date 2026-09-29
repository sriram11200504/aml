#!/usr/bin/env bash
# run_all.sh – Start all AML demo services without Docker (SQLite mode)
# Usage: ./run_all.sh
# Stop with: ./stop_all.sh

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "╔══════════════════════════════════════════════════════╗"
echo "║           AML Demo – Starting All Services           ║"
echo "╚══════════════════════════════════════════════════════╝"

wait_for_health() {
  local url="$1"
  local name="$2"
  local max=30
  local i=0
  echo -n "  Waiting for $name..."
  while ! curl -sf "$url/health" >/dev/null 2>&1; do
    sleep 1
    i=$((i+1))
    if [ $i -ge $max ]; then
      echo " TIMEOUT"
      return 1
    fi
    echo -n "."
  done
  echo " OK ✓"
}

mkdir -p "$ROOT/logs" "$ROOT/pids"

# ── Mock Model Service ─────────────────────────────────────────────────────────
echo ""
echo "▶ Starting Mock Model Service (port 8200)..."
cd "$ROOT/aml-platform/mock-model-service"
[ ! -d venv ] && python3 -m venv venv
./venv/bin/pip install -q -r requirements.txt
nohup ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8200 > "$ROOT/logs/mock-model.log" 2>&1 &
echo $! > "$ROOT/pids/mock-model.pid"

# ── AML Platform API ───────────────────────────────────────────────────────────
echo "▶ Starting AML Platform API (port 8100)..."
cd "$ROOT/aml-platform"
[ ! -d venv ] && python3 -m venv venv
./venv/bin/pip install -q -r requirements.txt
mkdir -p data
nohup ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8100 > "$ROOT/logs/aml-api.log" 2>&1 &
echo $! > "$ROOT/pids/aml-api.pid"

# ── Fake Bank API ──────────────────────────────────────────────────────────────
echo "▶ Starting Fake Bank API (port 8000)..."
cd "$ROOT/fake-bank"
[ ! -d venv ] && python3 -m venv venv
./venv/bin/pip install -q -r requirements.txt
mkdir -p data
nohup ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$ROOT/logs/bank-api.log" 2>&1 &
echo $! > "$ROOT/pids/bank-api.pid"

# ── Health checks ──────────────────────────────────────────────────────────────
echo ""
echo "Waiting for services to be ready..."
wait_for_health http://localhost:8200 "Mock Model Service"
wait_for_health http://localhost:8100 "AML Platform API"
wait_for_health http://localhost:8000 "Fake Bank API"

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║                  All Services Ready                  ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Fake Bank App        http://localhost:8000          ║"
echo "║  Fake Bank API        http://localhost:8000/docs     ║"
echo "║  AML Dashboard        http://localhost:8100/dashboard║"
echo "║  AML Platform API     http://localhost:8100/docs     ║"
echo "║  Mock Model Service   http://localhost:8200/docs     ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Logs: ./logs/                                       ║"
echo "║  To stop: ./stop_all.sh                              ║"
echo "╚══════════════════════════════════════════════════════╝"
