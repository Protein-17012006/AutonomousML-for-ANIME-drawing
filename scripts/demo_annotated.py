"""E2E demo: post suite_rife source keys to the box co-pilot; fetch annotated flags.

Default clips: f000 (warp_melt "smoke smear" — must FLAG with a circle) and
f003 (clean — must PASS with no annotation). Keys = EVEN-index frames of each
16-frame clip (the odd frames are the RIFE in-betweens the suite scored).

Usage:
    python scripts/demo_annotated.py --url http://<box-host>:8000 \
        --clip f000 --out .scratch/annotated_demo
"""
from __future__ import annotations

import argparse
import glob
import json
import os

import httpx

SUITE = os.path.join("benchmark", "suites", "suite_rife", "clips")


def clip_keys(clip_id: str) -> list[str]:
    frames = sorted(glob.glob(os.path.join(SUITE, clip_id, "*.png")))
    if len(frames) < 3:
        raise SystemExit(f"no frames for clip {clip_id!r} under {SUITE}")
    return frames[0::2]                     # even indices = source keys


def run(url: str, clip_id: str, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    keys = clip_keys(clip_id)
    print(f"[demo] {clip_id}: posting {len(keys)} keys -> {url}/session")
    files = [("keys", (os.path.basename(p), open(p, "rb"), "image/png")) for p in keys]
    with httpx.Client(timeout=600.0) as client:
        with client.stream("POST", f"{url}/session", data={"engines": "box"},
                           files=files) as r:
            r.raise_for_status()
            result = None
            for line in r.iter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    if "artifacts" in payload:      # the final result event
                        result = payload
        if result is None:
            raise SystemExit("no result event received")

        print(f"[demo] flagged={result['flagged']} abstained={result['abstained']}"
              f" qa_degraded={result.get('qa_degraded')}")
        for i, e in (result.get("explanations") or {}).items():
            print(f"  pair {i}: {e.get('err_type')} @ {e.get('region')}"
                  f" — {e.get('explanation')}")
            print(f"           annotated_url={e.get('annotated_url')}")
            if e.get("annotated_url"):
                url_path = e['annotated_url']
                png = client.get(f"{url}{url_path}")
                if png.status_code == 200:
                    fn = os.path.join(out_dir, f"{clip_id}_pair{i}_annotated.png")
                    open(fn, "wb").write(png.content)
                    print(f"           saved -> {fn}")
                else:
                    print(f"[demo] WARN: GET {url}{url_path} -> {png.status_code}, skipped")
        report_path = result['artifacts']['report']
        rep = client.get(f"{url}{report_path}")
        if rep.status_code == 200:
            open(os.path.join(out_dir, f"{clip_id}_report.md"), "wb").write(rep.content)
        else:
            print(f"[demo] WARN: GET {url}{report_path} -> {rep.status_code}, skipped")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--url",
        default=os.environ.get("COPILOT_SERVICE_URL", "http://127.0.0.1:8000"),
    )
    ap.add_argument("--clip", default="f000")
    ap.add_argument("--out", default=os.path.join(".scratch", "annotated_demo"))
    a = ap.parse_args()
    run(a.url, a.clip, a.out)
