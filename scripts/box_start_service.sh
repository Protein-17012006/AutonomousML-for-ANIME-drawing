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
PID="$(ss -ltnp 2>/dev/null | grep ":$PORT" | grep -oP 'pid=\K[0-9]+' | head -1)"

security_fail() {
  echo "FATAL: $1"
  if [ -n "$PID" ]; then
    echo "stopping unverifiable old service pid $PID (fail closed)"
    kill "$PID" 2>/dev/null || true
  fi
  exit 1
}

secure_env_file() {
  local path="$1" required="${2:-0}" owner mode
  if [ ! -e "$path" ]; then
    [ "$required" = "0" ] && return 1
    security_fail "missing $path"
  fi
  [ ! -L "$path" ] || security_fail "$path must not be a symlink"
  owner=$(stat -c '%u' "$path")
  mode=$(stat -c '%a' "$path")
  [ "$owner" = "$(id -u)" ] || security_fail "$path must be owned by $(id -un)"
  case "$mode" in
    400|600) ;;
    *) security_fail "$path permissions must be 400 or 600 (found $mode)" ;;
  esac
  return 0
}

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
  echo "  ~/cogvideo-venv/bin/pip install fastapi 'uvicorn[standard]' python-multipart httpx pillow numpy imageio imageio-ffmpeg opencv-python-headless scikit-image openai anthropic 'PyJWT[crypto]' boto3"
  echo "  ~/cogvideo-venv/bin/pip install torch==2.11.0 torchvision==0.26.0 --index-url https://download.pytorch.org/whl/cu128  # torchvision REQUIRED by RIFE"
  security_fail "uvicorn is unavailable; refusing to leave an unverifiable service running"
fi

# DeepSeek director/ask key: source the box-local env file when present so EVERY
# restart path (incl. deploy_box.sh --restart) keeps the LLM live — without it the
# loop silently degrades to the decide_fixed ladder (2026-07-02 wiring).
DEEPSEEK_ENV="$HOME/.copilot_deepseek_env"
if secure_env_file "$DEEPSEEK_ENV" 0; then
  . "$DEEPSEEK_ENV" || security_fail "could not load $DEEPSEEK_ENV"
fi

# AWS publisher (front door sub-project 3): S3 artifacts + DynamoDB session records.
# Env-gated (AWS_PUBLISH=1 inside the file) and fail-soft — absent file = publisher off.
AWS_ENV="$HOME/.copilot_aws_env"
if secure_env_file "$AWS_ENV" 0; then
  . "$AWS_ENV" || security_fail "could not load $AWS_ENV"
fi
[ -n "${COPILOT_MEMORY_TABLE:-}" ] || security_fail \
  "COPILOT_MEMORY_TABLE must be set in $AWS_ENV or the launcher environment"
[ -n "${COPILOT_FEEDBACK_TABLE:-}" ] || security_fail \
  "COPILOT_FEEDBACK_TABLE must be set in $AWS_ENV or the launcher environment"
export COPILOT_MEMORY_TABLE COPILOT_FEEDBACK_TABLE

# Optional GIMM-VFI paths. Defaults work for a checkout at ~/GIMM-VFI, while
# this file supports Long's existing model location without hard-coding it in
# git. The adapter validates paths only when a request selects GIMM.
GIMM_ENV="$HOME/.copilot_gimm_env"
if secure_env_file "$GIMM_ENV" 0; then
  . "$GIMM_ENV" || security_fail "could not load $GIMM_ENV"
fi
export COPILOT_GIMM_ROOT COPILOT_GIMM_CONFIG COPILOT_GIMM_CHECKPOINT
export COPILOT_GIMM_DEVICE COPILOT_GIMM_DS_FACTOR

# The public front door authenticates with ALB Cognito and forwards a signed
# x-amzn-oidc-data token. The box verifies that signature and signer before
# binding sessions/data to a Cognito subject. Fail closed: this production
# launcher must never silently fall back to ownerless sessions.
AUTH_ENV="$HOME/.copilot_auth_env"
secure_env_file "$AUTH_ENV" 1
. "$AUTH_ENV" || security_fail "could not load $AUTH_ENV"
[ -n "$COPILOT_COGNITO_REGION" ] || security_fail "COPILOT_COGNITO_REGION missing from $AUTH_ENV"
[ -n "$COPILOT_COGNITO_USER_POOL_ID" ] || security_fail "COPILOT_COGNITO_USER_POOL_ID missing from $AUTH_ENV"
[ -n "$COPILOT_COGNITO_APP_CLIENT_ID" ] || security_fail "COPILOT_COGNITO_APP_CLIENT_ID missing from $AUTH_ENV"
[ -n "$COPILOT_ALB_ARN" ] || security_fail "COPILOT_ALB_ARN missing from $AUTH_ENV"
export COPILOT_COGNITO_REGION COPILOT_COGNITO_USER_POOL_ID
export COPILOT_COGNITO_APP_CLIENT_ID COPILOT_ALB_ARN

if [ -n "$PID" ]; then echo "killing old server pid $PID on :$PORT"; kill "$PID"; sleep 2; fi

cd "$DIR" || { echo "FATAL: no $DIR"; exit 1; }
# COPILOT_WEB_DIR=dist serves the team's canonical Next.js static export
# (~/copilot_svc/dist, deployed separately from the export repo — NOT from this repo;
# the old Vite frontend/ was removed 2026-07-05); falls back to web/ in app.py if dist absent.
COPILOT_AUTH_REQUIRED=1 COPILOT_TRUST_ALB_OIDC=1 COPILOT_ENGINES=box \
  COPILOT_WEB_DIR="${COPILOT_WEB_DIR:-dist}" nohup setsid "$UVICORN" service.app:app \
  --host 0.0.0.0 --port "$PORT" >"$DIR/uvicorn.log" 2>&1 </dev/null &
disown 2>/dev/null || true
sleep 4
echo "--- uvicorn.log ---"; tail -n 6 "$DIR/uvicorn.log"
if ! ss -ltn 2>/dev/null | grep -q ":$PORT"; then
  echo "FAILED to bind :$PORT"
  exit 1
fi
AUTH_CODE=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 \
  -X POST "http://127.0.0.1:$PORT/session/0/agent" \
  -H 'Content-Type: application/json' -d '{"message":"health"}' || true)
if [ "$AUTH_CODE" != "401" ]; then
  NEW_PID="$(ss -ltnp 2>/dev/null | grep ":$PORT" | grep -oP 'pid=\K[0-9]+' | head -1)"
  [ -z "$NEW_PID" ] || kill "$NEW_PID" 2>/dev/null || true
  security_fail "auth health check expected HTTP 401, got ${AUTH_CODE:-no response}"
fi
echo "OK: listening on :$PORT with authentication enforced"
