"""Ask a RUNNING co-pilot service what verdict each pair of a real cut received.

Spec 6, unit A. Two tools — explain_pair and show_annotated — need a pair whose
qa.status is flag or abstain, and no live run has ever produced one. Before
changing anything, find out which of the three routes to a non-pass verdict is
reachable on real data:

  * the recall guard   src_motion > tau_motion  -> abstain   (perception.py:96)
  * the stillness guard concentration > 0.6     -> flag      (perception.py:87)
  * the calibrator itself                       -> flag/abstain

This talks HTTP to the deployed service on purpose: it therefore measures the
tau the process ACTUALLY booted with, which is the exact thing a file on disk
failed to tell us on 2026-08-02.

Usage — run as a MODULE from the repo root, not as a path. `python scripts/x.py`
puts `scripts/` on sys.path instead of the repo root and cannot import
`inbetween_copilot`:

    python -m scripts.probe_qa_verdicts --url http://127.0.0.1:8000 --clip f000
    python -m scripts.probe_qa_verdicts --keys path/to/cut/*.png
"""
from __future__ import annotations

import argparse
import glob
import json
import os

from inbetween_copilot.thresholds import TAU_SRC_MOTION

SUITE = os.path.join("benchmark", "suites", "suite_rife", "clips")


def classify_rows(pairs: list[dict], tau_motion: float) -> tuple[list[dict], str]:
    """Turn raw pair events into printable rows plus a one-line conclusion.

    `guard_should_fire` is "unknown" rather than False when the server did not
    report a gap: absence of a key is not evidence that the value is small.
    """
    rows: list[dict] = []
    silent_failures: list[int] = []
    reached: set[str] = set()
    for p in pairs:
        gap = p.get("gap")
        qa = p.get("qa")
        filled = p.get("action") != "needs_key"
        if not filled:
            should = False
        elif gap is None:
            should = "unknown"
        else:
            should = float(gap) > tau_motion
        if qa in ("flag", "abstain"):
            reached.add(qa)
        if should is True and qa == "pass":
            silent_failures.append(p["index"])
        rows.append({
            "index": p["index"],
            "action": p.get("action"),
            "gap": "not reported" if gap is None else round(float(gap), 5),
            "qa": qa if qa is not None else "n/a",
            "p_error": p.get("verdict_prob"),
            "u": p.get("uncertainty"),
            "guard_should_fire": should,
        })
    if silent_failures:
        conclusion = (
            f"RECALL GUARD did not fire on pairs {silent_failures}: filled, "
            f"gap > tau_motion={tau_motion}, and still 'pass'. Guard is armed in "
            f"code (perception.py:96) -> investigate qa_window, the engine bundle, "
            f"or whether window_source_motion sees these frames (run --internals)."
        )
    elif reached:
        conclusion = (
            f"REACHABLE: {sorted(reached)} present on real data — explain_pair and "
            f"show_annotated have a pair to work on. Film this cut."
        )
    else:
        conclusion = (
            "No pair is above tau_motion and none flagged: every filled pair is "
            "genuinely near-still, so 'pass' is CORRECT. Try another cut "
            "(design section 2, branch B-ii) — do not move a threshold."
        )
    return rows, conclusion


def clip_keys(clip_id: str) -> list[str]:
    frames = sorted(glob.glob(os.path.join(SUITE, clip_id, "*.png")))
    if len(frames) < 3:
        raise SystemExit(f"no frames for clip {clip_id!r} under {SUITE}")
    return frames[0::2]                     # even indices = source keys


def internals(keys: list[str]) -> None:
    """Print what the two deterministic guards actually measure, per pair.

    Nothing here is derived from `gap`: window_source_motion is recomputed on the
    same frames the QA saw, because the equality "src_motion == the gate's gap"
    only holds for a 2-source window and run_copilot may be windowing wider
    (copilot.py:91).
    """
    import numpy as np
    from PIL import Image

    from inbetween_copilot.infrastructure.artifact_json import load_artifact
    from inbetween_copilot.qa.csq.stillness import (
        TAU_MOTION, TAU_STILL, motion_concentration, window_source_motion,
    )
    from service.core.config import BoxSettings, ConfigurationError, GateSettings

    # BoxSettings.from_env() is the class that owns csq_artifact_path
    # (service/core/config.py:494). It requires VISION_MODEL_CHECK and pins
    # VISION_MAX_PIXELS_CHECK to 320, so it RAISES off the box — say which,
    # rather than falling back to a path that may not be the deployed one.
    try:
        art_path = BoxSettings.from_env().csq_artifact_path
    except ConfigurationError as exc:
        print(f"[internals] cannot resolve the box config here: {exc}")
        print("[internals] run this ON the box; the artifact path below is unknown")
        art_path = None
    else:
        print(f"[internals] COPILOT_TAU_GATE in THIS process = "
              f"{GateSettings.from_env().tau_gate}")
        print(f"[internals] csq artifact = {art_path} exists={os.path.exists(art_path)}")
        if os.path.exists(art_path):
            art = load_artifact(str(art_path))
            print(f"[internals] artifact.meta = {art.meta}")
            print(f"[internals] resolved tau_motion = "
                  f"{art.meta.get('tau_motion', TAU_SRC_MOTION)}"
                  f"  tau_still = {art.meta.get('tau_still', TAU_STILL)}")
        else:
            print("[internals] NO ARTIFACT -> the fallback perceive() has NO abstain "
                  "at all (perception.py:69). That alone explains zero abstains.")

    frames = [np.array(Image.open(p).convert("RGB")) for p in keys]
    for i in range(len(frames) - 1):
        window = [frames[i], frames[i + 1]]
        print(f"[internals] pair {i}: "
              f"window_source_motion={window_source_motion(window):.5f} "
              f"(fires above {TAU_SRC_MOTION}) "
              f"motion_concentration={motion_concentration(window):.3f} "
              f"(fires above {TAU_STILL}, zeroed below total motion {TAU_MOTION})")


def _authenticate(client, url: str, id_token: str) -> None:
    """Trade a Cognito ID token for the session cookie the app routes require.

    `authenticate_request` reads the COOKIE (or the ALB header), never a bare
    bearer, so POST /auth/session is a required hop rather than a convenience.
    The cookie is `Secure` in production, which is why this only works against
    an https:// origin. `Origin` is mandatory once a cookie is present
    (auth.py:331) and must equal scheme://host exactly.
    """
    origin = url.rstrip("/")
    r = client.post(f"{url}/auth/session",
                    headers={"Authorization": f"Bearer {id_token}", "Origin": origin})
    if r.status_code != 204:
        raise SystemExit(f"POST /auth/session -> {r.status_code}: {r.text[:300]}")
    me = client.get(f"{url}/auth/me", headers={"Origin": origin})
    if me.status_code != 200:
        raise SystemExit(f"GET /auth/me -> {me.status_code}: {me.text[:300]}")
    print(f"[probe] authenticated as sub={me.json().get('user_sub')}")


def run(url: str, keys: list[str], tau_motion: float, id_token: str | None = None) -> None:
    import httpx

    origin = url.rstrip("/")
    print(f"[probe] posting {len(keys)} keys -> {url}/session (engines=box)")
    files = [("keys", (os.path.basename(p), open(p, "rb"), "image/png")) for p in keys]
    pairs: list[dict] = []
    result = None
    with httpx.Client(timeout=900.0, follow_redirects=False) as client:
        if id_token:
            _authenticate(client, url, id_token)
        with client.stream("POST", f"{url}/session", data={"engines": "box"},
                           headers={"Origin": origin}, files=files) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                if "artifacts" in payload:
                    result = payload
                elif "index" in payload:
                    pairs.append(payload)
    if result is None:
        raise SystemExit("no result event received")

    print(f"[probe] qa_degraded={result.get('qa_degraded')} "
          f"csq_calibrator={'present' if result.get('csq') else 'ABSENT'}")
    print(f"[probe] flagged={result['flagged']} abstained={result['abstained']} "
          f"needs_key={result['needs_key']}")
    print(f"[probe] explanations for pairs: {sorted(result.get('explanations') or {})}")
    print(f"[probe] key-travel overlays for pairs: "
          f"{sorted(result.get('pair_keys') or {})}")

    rows, conclusion = classify_rows(pairs, tau_motion)
    print(f"\n{'idx':>4} {'action':>10} {'gap':>12} {'qa':>8} {'p_err':>7} "
          f"{'u':>6}  guard_should_fire")
    for row in rows:
        print(f"{row['index']:>4} {str(row['action']):>10} {str(row['gap']):>12} "
              f"{str(row['qa']):>8} {str(row['p_error']):>7} {str(row['u']):>6}"
              f"  {row['guard_should_fire']}")
    print(f"\n[probe] tau_motion used = {tau_motion} (code default; the box may run a "
          f"different COPILOT_TAU_GATE, which does NOT move this guard)")
    print(f"[probe] CONCLUSION: {conclusion}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--url",
        default=os.environ.get("COPILOT_SERVICE_URL", "http://127.0.0.1:8000"),
    )
    ap.add_argument("--clip", default=None,
                    help="clip id under benchmark/suites/suite_rife/clips")
    ap.add_argument("--keys", nargs="*", default=None, help="explicit key PNG paths")
    ap.add_argument("--tau-motion", type=float, default=TAU_SRC_MOTION)
    ap.add_argument("--internals", action="store_true",
                    help="also read the guards' own inputs, in-process")
    ap.add_argument("--id-token-file", default=None,
                    help="file holding a Cognito ID token; required against a "
                         "deployment with COPILOT_AUTH_REQUIRED=1. Never pass the "
                         "token on the command line — it is a credential.")
    a = ap.parse_args()
    if not a.clip and not a.keys:
        raise SystemExit("give --clip or --keys")
    key_paths = a.keys if a.keys else clip_keys(a.clip)
    if a.internals:
        internals(key_paths)
    token = None
    if a.id_token_file:
        with open(a.id_token_file, encoding="utf-8") as fh:
            token = fh.read().strip()
    run(a.url, key_paths, a.tau_motion, token)
