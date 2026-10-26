#!/bin/bash
# Detached continuous commentary queue.
#
# Start:
#   nohup caffeinate -dimsu bash skills/podcast-youtuber-agent/scripts/continuous_worker.sh \
#     >> build/autopilot/continuous-runner.log 2>&1 &
#
# Stop:
#   touch build/autopilot/STOP
#
# Each episode is uploaded privately; enforce_private.py keeps it private if
# YouTube's processing briefly flips the visibility.  The worker stops after
# five episodes or when the daily YouTube quota is exhausted.
set -u
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT" || exit 1
LOG="$ROOT/build/autopilot/continuous-$(date +%Y%m%d-%H%M).log"
exec >>"$LOG" 2>&1
echo "=== continuous worker $(date) ==="
for i in 1 2 3 4 5; do
  if [ -f "$ROOT/build/autopilot/STOP" ]; then
    echo "STOP file detected; exiting"
    break
  fi
  echo "=== episode $i $(date) ==="
  .venv/bin/python skills/podcast-youtuber-agent/scripts/autopilot.py \
    --episodes 1 --source investment --language zh-Hans
  code=$?
  echo "autopilot exit=$code $(date)"
  .venv/bin/python skills/podcast-youtuber-agent/scripts/enforce_private.py \
    --latest --settle 120 --attempts 3 || true
  if [ "$code" -ne 0 ]; then
    if tail -80 "$LOG" | grep -q 'quotaExceeded\|quota exceeded'; then
      echo "quota exceeded; stopping worker"
      break
    fi
    sleep 600
  else
    sleep 300
  fi
done
echo "=== continuous worker done $(date) ==="
