#!/bin/bash
# Detached cooldown-aware commentary queue.
#
# Upload pending videos first, then generate one more while YouTube quota is
# cooling down. Pending manifests are capped at three so the queue cannot grow
# without bound. Stop with: touch build/autopilot/STOP
set -u
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT" || exit 1
LOG="$ROOT/build/autopilot/continuous-$(date +%Y%m%d-%H%M).log"
exec >>"$LOG" 2>&1
echo "=== cooldown worker $(date) ==="
for i in 1 2 3 4 5 6; do
  if [ -f "$ROOT/build/autopilot/STOP" ]; then
    echo "STOP file detected; exiting"
    break
  fi
  echo "=== cycle $i: upload pending $(date) ==="
  .venv/bin/python skills/podcast-youtuber-agent/scripts/upload_pending.py --limit 2
  upload_code=$?
  pending_count=$(find "$ROOT/out" -name pending-upload.json 2>/dev/null | wc -l | tr -d ' ')
  echo "upload exit=$upload_code pending=$pending_count $(date)"
  if [ "$pending_count" -lt 3 ] && [ ! -f "$ROOT/build/autopilot/STOP" ]; then
    echo "=== cycle $i: generate one without upload $(date) ==="
    .venv/bin/python skills/podcast-youtuber-agent/scripts/autopilot.py \
      --episodes 1 --source investment --language zh-Hans --generate-only
    echo "generate exit=$? $(date)"
  fi
  .venv/bin/python skills/podcast-youtuber-agent/scripts/upload_pending.py --limit 2
  echo "post-generate upload exit=$? $(date)"
  sleep 300
done
echo "=== cooldown worker done $(date) ==="
