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
BOX_HOST="${BOX_HOST:?set BOX_HOST to the inference box tailnet IP or DNS name}"
BOX_DIR="${BOX_DIR:-~/copilot_svc}"
PORT="${PORT:-8000}"
DEST="${BOX_USER}@${BOX_HOST}"

# what to ship: the service, the core lib, its RUNTIME
# imports (inbetween_copilot/signals/* imports benchmark.{lib,smallgap} at import time,
# and wiring's qa_fn needs vision_common — omitting them left stale copies on the box:
# the audit's #3 finding, 2026-07-02), and the daemon launcher.
# The SERVED frontend is the TEAM's canonical Next.js static export (in the export repo),
# deployed separately to ~/copilot_svc/dist and served via COPILOT_WEB_DIR=dist. This
# script deliberately ships NO frontend build, so it can never clobber that Next export
# (the old frontend/dist -> dist sync did exactly that). Frontend deploy is out of scope here.
PATHS=(service inbetween_copilot benchmark vision_common scripts
       requirements-gimm-box.txt)
# box-only comparison script: git-ignored scratch — ship only when present so a
# fresh clone's deploy doesn't abort under `set -euo pipefail`.
[ -e .scratch/fullloop/compare_video.py ] && PATHS+=(.scratch/fullloop/compare_video.py)

echo ">> deploying to ${DEST}:${BOX_DIR}"
if command -v rsync >/dev/null 2>&1; then
  # suites/ + results/ = local benchmark DATA (5,984 PNGs ≈ 1.3 GB) — the box only
  # needs the benchmark CODE (lib/, smallgap/, triage/) the pipeline imports.
  rsync -av --exclude='__pycache__' --exclude='*.pyc' \
        --exclude='suites/' --exclude='results/' \
        "${PATHS[@]}" "${DEST}:${BOX_DIR}/"
else
  # `scp -r` cannot exclude anything, so it shipped benchmark/suites + results —
  # the 1.3 GB of PNGs the rsync branch above deliberately skips. On 2026-08-03
  # that reset the connection mid-transfer and the deploy died before --restart,
  # leaving the box serving code from before the copy. tar-over-ssh takes the
  # same exclusions as rsync, so both paths ship the same tree.
  echo "   (rsync not found, falling back to tar over ssh)"
  tar czf - --exclude='__pycache__' --exclude='*.pyc' \
      --exclude='benchmark/suites' --exclude='benchmark/results' \
      "${PATHS[@]}" | ssh "${DEST}" "mkdir -p ${BOX_DIR} && tar xzf - -C ${BOX_DIR}"
fi

if [[ "${1:-}" == "--restart" ]]; then
  echo ">> starting image-edit worker and restarting service on the box"
  # box_start_service.sh kills the old server BY PORT (a `pkill -f uvicorn...`
  # pattern would match this launcher's own cmdline and kill itself) and relaunches
  # the venv uvicorn detached (nohup+setsid). See that script's header for the why.
  ssh "${DEST}" \
    "bash ${BOX_DIR}/scripts/box_start_image_edit_worker.sh 8002 && \
     bash ${BOX_DIR}/scripts/box_start_service.sh ${PORT}"
  echo ">> verify from your machine (expect 200 + the demo UI):"
  echo "   curl -s -o /dev/null -w 'HTTP %{http_code}\\n' http://${BOX_HOST}:${PORT}/"
else
  echo ">> files synced. Re-run with --restart to bounce the service, or restart manually:"
  echo "   ssh ${DEST} \"bash ${BOX_DIR}/scripts/box_start_image_edit_worker.sh 8002 && bash ${BOX_DIR}/scripts/box_start_service.sh ${PORT}\""
fi

echo ">> to build the side-by-side comparison video on the box:"
echo "   ssh ${DEST} \"cd ${BOX_DIR} && python .scratch/fullloop/compare_video.py --data ~/fullloop --out ~/fullloop/compare.mp4 --fps 24\""
