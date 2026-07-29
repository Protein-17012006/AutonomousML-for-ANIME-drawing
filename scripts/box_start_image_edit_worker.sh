#!/usr/bin/env bash
# Start the loopback-only DiffuEraser image-edit worker on Long's box.
set -euo pipefail

PORT="${1:-8002}"
ROOT="${COPILOT_ROOT:-$HOME/copilot_svc}"
PYTHON="${COPILOT_SERVICE_PYTHON:-$HOME/cogvideo-venv/bin/python}"
ENV_FILE="${COPILOT_IMAGE_EDIT_ENV:-$HOME/.copilot_image_edit_env}"
LOG_FILE="${COPILOT_IMAGE_EDIT_LOG:-$ROOT/image_edit_worker.log}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

if [[ ! -x "$PYTHON" ]]; then
  echo "service Python is not executable: $PYTHON" >&2
  exit 1
fi
if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "image-edit worker already responds on 127.0.0.1:${PORT}"
  exit 0
fi
if command -v fuser >/dev/null 2>&1 && fuser "${PORT}/tcp" >/dev/null 2>&1; then
  echo "port ${PORT} is occupied by another process; refusing to replace it" >&2
  exit 1
fi

cd "$ROOT"
nohup setsid "$PYTHON" -m uvicorn scripts.image_edit_worker:app \
  --host 127.0.0.1 --port "$PORT" >"$LOG_FILE" 2>&1 </dev/null &

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    echo "image-edit worker started on 127.0.0.1:${PORT}"
    exit 0
  fi
  sleep 0.5
done

echo "image-edit worker did not become ready; inspect $LOG_FILE" >&2
exit 1
