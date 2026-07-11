"""U1 -- the lens bank. Six independent, role-diverse questions put to the served
detector, one VLM call per (clip, lens). No cross-lens discussion: independence
catches errors that consensus would smooth over. styl_guard is the hard-negative
guard (an apparent error that is intentional stylization)."""
from __future__ import annotations

import json
import re

_PREAMBLE = ("These are consecutive frames of one short animation clip, in order. "
             "Judge ONLY the specific question below.\n\n")
_RETURN = '\n\nReturn JSON: {"verdict": "flag" | "clean" | "unsure", "note": "<one sentence>"}'

_DEFS = [
    ("gap", "positive", "not_interpolable",
     "Are the first and last frames close enough in content to interpolate between, "
     "or is this a snap / scene-cut (too far apart to interpolate)? flag = snap/too-far."),
    ("timing", "positive", "timing_intent",
     "Is the motion timing coherent, or does a smooth tween replace an intended snap or "
     "hold (the motion eases through where it should pop/hold)? flag = timing/intent error."),
    ("identity", "positive", "identity_drift",
     "Do the character's identity, face, and colors stay stable across the frames, or do "
     "they drift / change? flag = identity or colour drift."),
    ("lineart", "positive", "flicker_pop",
     "Are the line art and edges stable, or is there line-boiling / flicker / popping "
     "(edges jitter or toggle frame-to-frame)? flag = flicker/line-boiling."),
    ("morph", "positive", "impossible_morph",
     "Is the shape change physically plausible, or is there an impossible morph, a limb "
     "that warps, or a melt? flag = morph/warp/melt."),
    ("styl_guard", "negative", None,
     "Is any apparent 'error' here actually INTENTIONAL anime stylization (a smear, an "
     "impact frame, chibi proportions, or motion blur)? flag = intentional stylization, NOT an error."),
]

LENSES = [{"key": k, "polarity": p, "hint": h, "question": _PREAMBLE + q + _RETURN}
          for (k, p, h, q) in _DEFS]


def parse_verdict(raw_text: str) -> dict:
    try:
        m = re.search(r"\{.*\}", raw_text or "", re.S)
        obj = json.loads(m.group(0)) if m else {}
        v = obj.get("verdict")
        v = v if v in ("flag", "clean", "unsure") else "unsure"
        return {"verdict": v, "note": str(obj.get("note", ""))}
    except Exception:
        return {"verdict": "unsure", "note": ""}


def build_lens_request(lens: dict, b64_images, *, model: str) -> dict:
    content = [{"type": "text", "text": lens["question"]}]
    for b in b64_images:
        content.append({"type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + b}})
    return {"model": model, "max_tokens": 400, "temperature": 0.0,
            "messages": [{"role": "user", "content": content}]}
