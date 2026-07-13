"""Replay demo: run the PRODUCTION explain+annotate path (perceive with the served
Qwen3-VL on the box + service.media.annotate.annotate_frame) over STORED ghosted in-betweens
from the frozen suites -> circled PNG (on the softest stored RIFE in-between, odd frame)
+ the VLM's why. Plus one clean control.

Same code the service runs (explain.py: perceive -> err_type/region/explanation;
app.py: annotate_frame on the mid frame) — only the input source differs (stored
suite windows instead of a live session's re-interpolated frames). Rationale: the
live path rarely flags — the gate refuses ghost-prone pairs and small-gap RIFE is
clean (user-study round 2) — so the flag artifact is demoed on the frozen suites'
real ghosted mids.

Usage (repo root; needs the box VLM up — serve.sh 320 <adapter>):
    python scripts/demo_replay_annotated.py
"""
import base64
import glob
import json
import os
import re
import sys
import urllib.request

import numpy as np
from PIL import Image

# `python scripts/demo_replay_annotated.py` puts scripts/ (not the repo root) on
# sys.path[0] — bootstrap the root so the package imports below resolve.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from inbetween_copilot.qa.perception import PERCEPTION_PROMPT, perceive
from inbetween_copilot.signals.sharpness import frame_sharpness
from inbetween_copilot.signals.softness import interp_softness
from service.media.annotate import annotate_frame

ROOT = os.getcwd()          # run from the repo root
VLM_URL = os.environ.get("VISION_BASE_URL_CHECK",
                         "http://100.71.161.102:8001/v1").rstrip("/") + "/chat/completions"
VISION_MODEL = os.environ.get("VISION_MODEL_CHECK", "qwen3vl-anime")
OUT = os.path.join(ROOT, ".scratch", "annotated_demo")


def _post_vlm(prompt, frames):
    # mirrors service/engines.py _post_vlm (PNG base64 -> chat/completions, temp 0)
    import cv2
    content = [{"type": "text", "text": prompt}]
    for fr in frames:
        _, buf = cv2.imencode(".png", cv2.cvtColor(fr, cv2.COLOR_RGB2BGR))
        content.append({"type": "image_url", "image_url":
                        {"url": "data:image/png;base64," + base64.b64encode(buf).decode()}})
    body = json.dumps({"model": VISION_MODEL, "max_tokens": 300, "temperature": 0,
                       "messages": [{"role": "user", "content": content}]}).encode()
    req = urllib.request.Request(VLM_URL, data=body,
                                 headers={"Content-Type": "application/json"})
    txt = json.loads(urllib.request.urlopen(req, timeout=180).read()
                     )["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", txt, re.S)
    return json.loads(m.group(0)) if m else {}


def vlm_struct_fn(frames):
    raw = _post_vlm(PERCEPTION_PROMPT, frames)
    return {
        "has_motion_error": bool(raw.get("has_motion_error")),
        "error_type": str(raw.get("error_type", "none")),
        "region": str(raw.get("region", "none")),
        "explanation": str(raw.get("explanation", "")),
    }


def load_clip(suite, cid):
    fs = sorted(glob.glob(os.path.join(ROOT, "benchmark", "suites", suite, "clips", cid, "*.png")))
    return [np.asarray(Image.open(p).convert("RGB"), dtype=np.uint8) for p in fs]


def replay(suite, cid, label):
    frames = load_clip(suite, cid)
    # production softness_fn (pipeline/wiring.py): soft_mean scalar out of interp_softness
    v = perceive(frames, vlm_fn=vlm_struct_fn,
                 softness_fn=lambda fr: float(interp_softness(fr)["soft_mean"]))
    print(f"{cid} ({label}): explain_verdict={v.decision} err_type={v.err_type} "
          f"region={v.region_hint}\n    why: {v.explanation}")
    if v.decision == "flag":
        # interleaved suite layout [s0, m0, s1, m1, ...]: odd = RIFE in-between.
        # annotate the softest ghosted mid, not a clean source frame.
        odd = list(range(1, len(frames), 2))
        if odd:
            mid = frames[min(odd, key=lambda i: frame_sharpness(frames[i]))]
        else:
            mid = frames[len(frames) // 2]
        ann = annotate_frame(mid, v.region_hint, v.err_type)
        os.makedirs(OUT, exist_ok=True)
        fn = os.path.join(OUT, f"replay_{cid}_annotated.png")
        Image.fromarray(ann).save(fn)
        print(f"    annotated -> {fn}")
    else:
        print("    (pass -> no annotation, as designed)")


if __name__ == "__main__":
    replay("suite_smallgap", "w0011_rife", "ghost, stored RIFE mid")
    replay("suite_smallgap", "w0064_rife", "ghost, stored RIFE mid")
    replay("suite_smallgap", "w0011_blend", "blend crossfade (study r1 flag class)")
    replay("suite_rife", "f000", "warp_melt smoke smear")
    replay("suite_rife", "f003", "CLEAN control")
