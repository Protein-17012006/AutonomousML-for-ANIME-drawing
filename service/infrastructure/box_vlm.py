"""Infrastructure adapter for the box-served VLM (Qwen3-VL behind an OpenAI-compatible :8001).

Transport ONLY: encode frames -> POST -> extract the JSON blob. Pulled out of
box_engines (P3, architecture review 2026-07-08) so the engine factory is pure
assembly and this second, hand-rolled VLM path is one visible module instead of
a closure. (vision_common/client.py stays the CLOUD/tier client; the box path
deliberately posts raw to the served endpoint — no SDK, no tier routing.)

FAIL-SAFE contract (unchanged): if the served VLM is unreachable or errors
(e.g. Errno 111 when serve.sh isn't running), post() returns {} so QA degrades
to the softness/gate signals — perceive() and the CSQ channels treat {} as a
benign no-error verdict. The `status` dict flips {"degraded": True} so the
worker can surface ResultEvent.qa_degraded (audit 2026-07-02 finding #6).
"""
from __future__ import annotations

import sys


def make_post_vlm(url: str, model: str, *, timeout: float = 180):
    """Return `(post, status)`: post(prompt, frames) -> dict (parsed JSON or {}),
    status = mutable {"degraded": bool} read by the worker after the run.
    cv2 is imported lazily at call time so importing this module stays box-free."""
    warned = []          # one-shot "VLM unavailable" notice (degraded-QA mode)
    status = {"degraded": False}

    def post(prompt, frames):
        import base64
        import json
        import re
        import urllib.request

        import cv2

        content = [{"type": "text", "text": prompt}]
        for fr in frames:
            _, buf = cv2.imencode(".png", cv2.cvtColor(fr, cv2.COLOR_RGB2BGR))
            content.append({"type": "image_url", "image_url":
                            {"url": "data:image/png;base64," + base64.b64encode(buf).decode()}})
        body = json.dumps({
            "model": model, "max_tokens": 300, "temperature": 0,
            "messages": [{"role": "user", "content": content}]
        }).encode()
        req = urllib.request.Request(url, data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            txt = json.loads(urllib.request.urlopen(req, timeout=timeout).read()
                             )["choices"][0]["message"]["content"]
            m = re.search(r"\{.*\}", txt, re.S)
            return json.loads(m.group(0)) if m else {}
        except Exception as e:
            status["degraded"] = True
            if not warned:
                print(f"[box_vlm] VLM at {url} unavailable ({e!r}); QA degrades "
                      f"to softness/gate. Start it on the box with: serve.sh 320 "
                      f"~/anime-ft-data/motion/runs/motion_lora16_on2s_v2",
                      file=sys.stderr, flush=True)
                warned.append(True)
            return {}

    return post, status
