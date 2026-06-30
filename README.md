# AutonomousML for Anime Drawing — In-Between Co-pilot

An artist-assist tool for anime in-betweening ("DLSS for anime"). Given a small number of
content-close key drawings, the co-pilot interpolates the missing in-between frames to add
smoothness and frame-rate, and then runs quality assurance on its own output. The human animator
keeps the key animation (genga); the co-pilot handles the in-between / clean-up tier (douga) plus
animation-quality checking (sakuga-QA).

The defensible part of this project is the QA / verification layer, not the interpolator. Any
modern tool can interpolate frames; the hard problem is knowing when an interpolated frame is wrong.
The target bar is "fan-undetectable": a frame ships only when the system is confident it is clean,
and otherwise it abstains and asks the artist for another key.


## The problem

Anime is not animated on every frame. Drawings are commonly held for two or three frames ("on-2s"
and "on-3s"), and motion arrives as holds, snaps, and smears rather than smooth displacement. A
naive frame interpolator assumes "near in time" means "near in content", so it ghosts and warps on
exactly these holds and snaps. The scope here is deliberately narrow: interpolate between near,
content-close keyframes and QA the middle frames. Large-gap in-betweening (synthesizing brand-new
breakdown drawings across distant keys) is out of scope and is treated as a different product.


## How it works

https://github.com/user-attachments/assets/e8606dd8-0ee8-479a-a2a4-11fda6193c67

*Art Example*
The model detect the lagre gap in drawing animation

The pipeline runs in five stages.

- Stage A — Interpolable Gate. A deterministic gate (no vision model) inspects each key pair and
  routes it: interpolable, needs-key, or hard-cut. It also estimates how many keys a gap needs.
  Content-far pairs are gated out and never interpolated. This gate is the single largest measured
  quality lever in the product.

- Stage B — Hold / Snap interpolation. For small gaps, a router chooses between RIFE-4.25
  (an anime-tuned frame interpolator), a hold-copy, or a snap-preserve, based on a softness signal.
  A large fraction of on-2s in-betweens are near-perfect hold-copies.

- Stage C — Generative interpolation. For larger sub-gaps and drawn breakdowns, an endpoint-
  conditioned generative model (AniSora V3.1) produces candidate frames, guarded by a vision-model
  reject-gate that rejects ghosted output.

- Stage D — Calibrated Self-QA (CSQ). Every in-between is scored with a three-state verdict:
  pass, abstain, or flag. CSQ fuses a fine-tuned vision detector with reference-free signals
  (softness, sharpness, structure), runs a perturbation-stability harness, and applies an
  uncertainty-conditioned conformal decision rule. It is explicitly built to resist gaming
  (a fix that clears a flag while drifting off ground truth is caught and turned into an abstain).

- Stage E — Correction loop. For flagged frames, the system loops: perceive, localize, decide,
  fix, re-QA, with a hard iteration cap. The escalation ladder is region-refill, then engine-
  escalate, then ask-key. Terminal states are resolved, needs-key, or unresolved.


## The agentic loop

The heart of the system is two cooperating models with deterministic tools around them.

- Perception is a vision-language model (Qwen3-VL-32B with an on-2s QLoRA adapter, served on a GPU
  box). It looks at each in-between and reports what is wrong and where.
- The director is a reasoning model (DeepSeek) that decides the next action: region-refill,
  engine-escalate, or ask-key.
- The gate, RIFE, and the generative interpolator are deterministic tools the director routes to,
  not agents.

The Calibrated Self-QA layer acts as the loop's conscience: it can override a model that claims a
frame is fixed by raising uncertainty into an abstain, which converts to an "ask the artist for a
key" outcome rather than silently shipping a bad frame.


## Repository layout

This repository contains the runtime code for the live product only.

- `service/`            FastAPI service exposing the co-pilot over HTTP with a server-sent-events
                        decision log.
- `inbetween_copilot/`  The co-pilot pipeline: gate, interpolation routing, Calibrated Self-QA,
                        the correction loop, signals, and reporting. Includes the frozen CSQ
                        calibration artifact under `artifacts/`.
- `benchmark/lib/`,
  `benchmark/smallgap/` Signal, scoring, and interpolation code that the pipeline imports at
                        runtime. These are runtime dependencies, not just research scaffolding.
- `vision_common/`      Shared vision-language-model client and palette utilities.
- `frontend/`           React, Vite, TypeScript, and Tailwind single-page app (the live UI).
- `scripts/`            Deployment and box-start scripts.
- `requirements-dev.txt`  Python dependencies (runtime and development combined).


## Architecture

The service and the SPA carry no GPU work. All heavy compute (RIFE interpolation, the served
vision-language model) runs on a separate GPU box reached over a private tunnel. The service runs
the pipeline and streams a decision log to the SPA; the SPA renders the per-pair decisions as a
timing sheet. A built deployment serves the SPA as static files from the same service.


## Getting started

### Prerequisites

- Python 3.10 or newer
- Node.js 20 or newer (for the frontend)
- A GPU box serving the vision-language model and the interpolation engines is required for a full
  session. The model weights and datasets are not part of this repository.

### Backend service

    # Windows PowerShell
    $env:PYTHONIOENCODING = "utf-8"
    pip install -r requirements-dev.txt
    uvicorn service.app:app --reload

The service exposes:

- `POST /session`          start a session from uploaded key frames; returns a server-sent-event
                           stream of per-pair events followed by a result event.
- `POST /session/video`    start a session from an uploaded video; the cut is decimated into keys.
- `GET  /session/{id}/...` fetch a produced artifact (report, montage, reconstructed video).

### Frontend

    cd frontend
    npm install
    npm run dev

The dev server runs on port 5173 and proxies API calls to the service (configure the target with
`VITE_API_TARGET`). For a production build:

    npm run build      # outputs frontend/dist

To have the backend serve the built UI, start the service with `COPILOT_WEB_DIR=frontend/dist`.
(This export omits the vanilla fallback UI, so without that variable the API runs but does not serve
a static page at `/`.)

### Deploy to the GPU box

    cd frontend && npm run build
    bash scripts/deploy_box.sh --restart

This syncs the service to the box and restarts it. The vision-language detector must be served on
the box before a session that uses it, otherwise self-QA calls fail with a connection error.


## Configuration

Configuration is read from environment variables (kept in a local `.env`, which is not committed):

- `DEEPSEEK_API_KEY`, `DEEPSEEK_MODEL`   director model credentials and selection.
- `VISION_MODEL_SPEC`, `VISION_MODEL_CHECK`, `VISION_MODEL_ESCALATE` and the matching
  `VISION_BASE_URL_*`   the tiered vision seam; the served detector is the "check" tier. When a base
  URL is unset, the corresponding tier falls back to a hosted vision model.
- `COPILOT_WEB_DIR`   directory of the static UI to serve (set to `frontend/dist` after building).


## Notes and limitations

- This is a runtime-only export. Tests, design documents, the benchmark datasets and evidence
  images, training code, and the vanilla fallback UI are intentionally excluded.
- Model weights (the interpolation engine and the vision-language model) and the source footage
  live on the GPU box and are not in this repository.
- The product is research-stage and was built as a solo vertical within a larger course project.


## Tech stack

- Backend: Python, FastAPI, Uvicorn, NumPy, Pillow, OpenCV, imageio.
- Frontend: React, Vite, TypeScript, Tailwind CSS.
- Models and engines: RIFE-4.25 (interpolation), AniSora V3.1 (generative interpolation),
  Qwen3-VL-32B with a QLoRA adapter (perception and QA), DeepSeek (director).
