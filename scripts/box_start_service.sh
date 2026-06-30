#!/usr/bin/env bash
# Runs ON the 5090 box. Restart the co-pilot service as a real detached daemon.
#
# Two hard-won rules baked in (see vault sub-project-1 plan, 2026-06-25 deploy log):
#  1. Kill the old server by PORT, never by `pkill -f "uvicorn service.app:app"` —
#     that pattern matches THIS shell's own command line and kills the launcher
#     before the new server persists (empty log, port stays down).
#  2. Use the venv uvicorn (`~/cogvideo-venv/bin/uvicorn`) — bare `uvicorn` is not
#     on the non-interactive SSH PATH.
# nohup+setsid+</dev/null detaches it so it survives the SSH channel closing.
set -uo pipefail
PORT="${1:-8000}"
DIR="$HOME/copilot_svc"
UVICORN="$(ls "$HOME"/cogvideo-venv/bin/uvicorn 2>/dev/null || command -v uvicorn)"
[ -z "$UVICORN" ] && { echo "FATAL: uvicorn not found (venv missing?)"; exit 1; }

PID="$(ss -ltnp 2>/dev/null | grep ":$PORT" | grep -oP 'pid=\K[0-9]+' | head -1)"
if [ -n "$PID" ]; then echo "killing old server pid $PID on :$PORT"; kill "$PID"; sleep 2; fi

cd "$DIR" || { echo "FATAL: no $DIR"; exit 1; }
# COPILOT_WEB_DIR=dist serves the built React SPA (~/copilot_svc/dist); falls back to
# web/ inside app.py if dist is absent.
COPILOT_ENGINES=box COPILOT_WEB_DIR="${COPILOT_WEB_DIR:-dist}" nohup setsid "$UVICORN" service.app:app \
  --host 0.0.0.0 --port "$PORT" >"$DIR/uvicorn.log" 2>&1 </dev/null &
disown 2>/dev/null || true
sleep 4
echo "--- uvicorn.log ---"; tail -n 6 "$DIR/uvicorn.log"
if ss -ltn 2>/dev/null | grep -q ":$PORT"; then echo "OK: listening on :$PORT"; else echo "FAILED to bind :$PORT"; fi
