#!/bin/bash
# Start the local ComfyUI server if it is not already listening.
#
# The cover pipeline assumes a server on 127.0.0.1:8188. It is not a daemon, so
# after a reboot nothing restarts it and covers silently fall back to the CPU
# ink sketch. Call this before a cover render.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PORT="${COMFYUI_PORT:-8188}"
LOG="$ROOT/build/autopilot/comfyui-$(date +%Y%m%d).log"
PIDFILE="$ROOT/build/autopilot/comfyui.pid"

if curl -sf -m 2 "http://127.0.0.1:$PORT/system_stats" >/dev/null 2>&1; then
  exit 0
fi

mkdir -p "$(dirname "$LOG")"
nohup "$ROOT/tools/ComfyUI/.venv/bin/python" "$ROOT/tools/ComfyUI/main.py" \
  --port "$PORT" >>"$LOG" 2>&1 &
echo $! >"$PIDFILE"

for _ in $(seq 1 60); do
  if curl -sf -m 2 "http://127.0.0.1:$PORT/system_stats" >/dev/null 2>&1; then
    echo "comfyui ready on $PORT (pid $(cat "$PIDFILE"))"
    exit 0
  fi
  sleep 2
done

echo "comfyui did not become ready on $PORT; see $LOG" >&2
exit 1
