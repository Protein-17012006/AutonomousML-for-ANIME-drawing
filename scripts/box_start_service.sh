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
if [ -z "$UVICORN" ]; then
  # The service venv ~/cogvideo-venv can go missing (deleted in a disk cleanup, wiped on a
  # rebuild) — the box then serves a 503 box-offline page because :8000 never binds while the
  # VLM venv (~/anime-ft-venv) keeps :8001 up. It is a SEPARATE venv from the VLM's. Rebuild it
  # (torch is usually in ~/.cache/pip so this is ~2 min). Root-caused 2026-07-05.
  echo "FATAL: uvicorn not found — the service venv ~/cogvideo-venv is missing. Rebuild it:"
  echo "  bash ~/rebuild_service_venv.sh          # one-shot, correct dep set"
  echo "  # or manually:"
  echo "  python3.12 -m venv ~/cogvideo-venv && ~/cogvideo-venv/bin/python -m pip install -U pip wheel"
  echo "  ~/cogvideo-venv/bin/pip install fastapi 'uvicorn[standard]' python-multipart httpx pillow numpy imageio imageio-ffmpeg opencv-python-headless scikit-image openai anthropic"
  echo "  ~/cogvideo-venv/bin/pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128  # torchvision REQUIRED by RIFE"
  exit 1
fi

# DeepSeek director/ask key: source the box-local env file when present so EVERY
# restart path (incl. deploy_box.sh --restart) keeps the LLM live — without it the
# loop silently degrades to the decide_fixed ladder (2026-07-02 wiring).
[ -f "$HOME/.copilot_deepseek_env" ] && . "$HOME/.copilot_deepseek_env"

# AWS publisher (front door sub-project 3): S3 artifacts + DynamoDB session records.
# Env-gated (AWS_PUBLISH=1 inside the file) and fail-soft — absent file = publisher off.
[ -f "$HOME/.copilot_aws_env" ] && . "$HOME/.copilot_aws_env"

PID="$(ss -ltnp 2>/dev/null | grep ":$PORT" | grep -oP 'pid=\K[0-9]+' | head -1)"
if [ -n "$PID" ]; then echo "killing old server pid $PID on :$PORT"; kill "$PID"; sleep 2; fi

cd "$DIR" || { echo "FATAL: no $DIR"; exit 1; }
# COPILOT_WEB_DIR=dist serves the team's canonical Next.js static export
# (~/copilot_svc/dist, deployed separately from the export repo — NOT from this repo;
# the old Vite frontend/ was removed 2026-07-05); falls back to web/ in app.py if dist absent.
COPILOT_ENGINES=box COPILOT_WEB_DIR="${COPILOT_WEB_DIR:-dist}" nohup setsid "$UVICORN" service.app:app \
  --host 0.0.0.0 --port "$PORT" >"$DIR/uvicorn.log" 2>&1 </dev/null &
disown 2>/dev/null || true
sleep 4
echo "--- uvicorn.log ---"; tail -n 6 "$DIR/uvicorn.log"
if ss -ltn 2>/dev/null | grep -q ":$PORT"; then echo "OK: listening on :$PORT"; else echo "FAILED to bind :$PORT"; fi
