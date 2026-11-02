#!/usr/bin/env bash
# Start or stop the test upstream servers in the background.
# Usage: scripts/upstreams.sh start|stop|status
set -u
cd "$(dirname "$0")/.."

SERVERS=(math_server notes_server rest_api)
PY=.venv/bin/python
mkdir -p .run

case "${1:-}" in
  start)
    for s in "${SERVERS[@]}"; do
      if [[ -f .run/$s.pid ]] && kill -0 "$(cat .run/$s.pid)" 2>/dev/null; then
        echo "$s already running (pid $(cat .run/$s.pid))"
        continue
      fi
      nohup "$PY" "upstreams/$s.py" > ".run/$s.log" 2>&1 &
      echo $! > ".run/$s.pid"
      echo "$s started (pid $!, log .run/$s.log)"
    done
    echo "math :9001/mcp · notes :9002/mcp · rest :9003 (docs /docs)"
    ;;
  stop)
    for s in "${SERVERS[@]}"; do
      if [[ -f .run/$s.pid ]]; then
        kill "$(cat .run/$s.pid)" 2>/dev/null && echo "$s stopped"
        rm -f ".run/$s.pid"
      fi
    done
    ;;
  status)
    for s in "${SERVERS[@]}"; do
      if [[ -f .run/$s.pid ]] && kill -0 "$(cat .run/$s.pid)" 2>/dev/null; then
        echo "$s running (pid $(cat .run/$s.pid))"
      else
        echo "$s stopped"
      fi
    done
    ;;
  *)
    echo "usage: $0 start|stop|status" >&2
    exit 1
    ;;
esac
