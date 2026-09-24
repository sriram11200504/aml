#!/usr/bin/env bash
# stop_all.sh – Stop all AML demo background services

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "Stopping AML demo services..."

for pid_file in "$ROOT"/pids/*.pid; do
  if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file")
    name=$(basename "$pid_file" .pid)
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null && echo "  Stopped $name (PID $pid)"
    fi
    rm "$pid_file"
  fi
done

echo "All services stopped."
