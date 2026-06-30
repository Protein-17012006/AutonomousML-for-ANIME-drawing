#!/usr/bin/env bash
# Sync the co-pilot service + web + core lib to the 5090 box and (optionally) restart
# the service. The box is the BRAIN (RIFE/VLM); AWS/local has no GPU. Run from the
# repo root in git-bash:  bash scripts/deploy_box.sh [--restart]
#
# Why this exists: the fix for `reconstructed.mp4` (fps=24 + boundary dedup) and new
# files (inbetween_copilot/reporting/compare.py, .scratch/fullloop/compare_video.py)
# only take effect once synced to ~/copilot_svc AND the uvicorn process is restarted.
# A served-but-stale service is the #1 "I fixed it but it's still wrong" trap here.
#
# Box is SHARED ([[gpu-shared-data-rigor]]): this only touches OUR ~/copilot_svc and
# OUR uvicorn; it never kills another user's process. Free-check the GPU before a run.
set -euo pipefail

BOX_USER="${BOX_USER:-long}"
BOX_HOST="${BOX_HOST:-100.71.161.102}"      # tailscale IP (matches box_engines default)
BOX_DIR="${BOX_DIR:-~/copilot_svc}"
PORT="${PORT:-8000}"
DEST="${BOX_USER}@${BOX_HOST}"

# what to ship: the service, the vanilla web UI (fallback), the built React SPA
# (frontend/dist -> ~/copilot_svc/dist, served when COPILOT_WEB_DIR=dist), the core
# lib (compare.py is new), the box-only comparison script, and the daemon launcher.
# NB: build the SPA first (`cd frontend && npm run build`) — frontend/dist must exist.
PATHS=(service web frontend/dist inbetween_copilot .scratch/fullloop/compare_video.py scripts/box_start_service.sh)

echo ">> deploying to ${DEST}:${BOX_DIR}"
if command -v rsync >/dev/null 2>&1; then
  rsync -av --exclude='__pycache__' --exclude='*.pyc' \
        "${PATHS[@]}" "${DEST}:${BOX_DIR}/"
else
  echo "   (rsync not found, falling back to scp -r)"
  scp -r "${PATHS[@]}" "${DEST}:${BOX_DIR}/"
fi

# Prune stale hashed SPA assets on the box. Each `npm run build` emits a new
# index-<hash>.{css,js}; neither scp (no --delete) nor a no-`--delete` rsync removes
# the old ones, so ~/copilot_svc/dist/assets accumulates every prior build. Keep only
# the files the freshly-synced dist/index.html actually references. Guarded: if no refs
# parse out (unexpected index.html), it skips rather than deleting anything.
echo ">> pruning stale SPA assets on the box (keep only what index.html references)"
ssh "${DEST}" 'bash -s' "${BOX_DIR}" <<'PRUNE'
set -eu
boxdir="$1"
d="$boxdir/dist/assets"
[ -d "$d" ] || { echo "   (no dist/assets yet — skip prune)"; exit 0; }
cd "$d"
keep=$(grep -oE 'index-[A-Za-z0-9_-]+\.(css|js)' ../index.html | sort -u)
[ -n "$keep" ] || { echo "   ABORT prune: no asset refs in index.html — kept everything"; exit 0; }
n=0
for f in index-*.css index-*.js; do
  [ -e "$f" ] || continue
  echo "$keep" | grep -qx "$f" || { rm -f "$f"; n=$((n+1)); }
done
echo "   pruned $n stale asset(s); kept $(echo "$keep" | wc -l): $(echo "$keep" | tr '\n' ' ')"
PRUNE

if [[ "${1:-}" == "--restart" ]]; then
  echo ">> restarting service on the box (port ${PORT}) via box_start_service.sh"
  # box_start_service.sh kills the old server BY PORT (a `pkill -f uvicorn...`
  # pattern would match this launcher's own cmdline and kill itself) and relaunches
  # the venv uvicorn detached (nohup+setsid). See that script's header for the why.
  ssh "${DEST}" "bash ${BOX_DIR}/box_start_service.sh ${PORT}"
  echo ">> verify from your machine (expect 200 + the demo UI):"
  echo "   curl -s -o /dev/null -w 'HTTP %{http_code}\\n' http://${BOX_HOST}:${PORT}/"
else
  echo ">> files synced. Re-run with --restart to bounce the service, or restart manually:"
  echo "   ssh ${DEST} \"cd ${BOX_DIR} && COPILOT_ENGINES=box uvicorn service.app:app --host 0.0.0.0 --port ${PORT}\""
fi

echo ">> to build the side-by-side comparison video on the box:"
echo "   ssh ${DEST} \"cd ${BOX_DIR} && python .scratch/fullloop/compare_video.py --data ~/fullloop --out ~/fullloop/compare.mp4 --fps 24\""
