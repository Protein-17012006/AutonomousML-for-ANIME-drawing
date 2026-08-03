"""Drive one in-session frame repair end to end, on the deployed stack.

Spec 6 follow-on. The paint surface now opens, but nothing had ever pushed a
painted mask through DiffuEraser from a real session and watched what came back.

Two model floors govern whether this can run at all, and both were found on the
box only after every unit test had mocked the worker (span.py:28-46):

  * MIN_MODEL_SIDE  = 264 -- the CROP sent to the model, not the frame
  * MIN_MODEL_FRAMES = 23 -- DiffuEraser: "the number of frames of video, mask,
    and priori is at least greater than 22"

The session path refuses a short cut rather than padding it with a repeated
frame, so this driver builds a cut long enough to clear the floor honestly:
every frame of a clip becomes a key, which yields ~2N-1 reconstructed frames.

What it reports is the point: whether the repair RAN, and what the QA said about
the result afterwards. A repair the QA then refuses is a success for the loop --
it proves the pipeline round-trips -- and says nothing about repair quality.

Usage:
    python -m scripts.probe_session_repair --clip f000 --id-token-file <file>
"""
from __future__ import annotations

import argparse
import base64
import glob
import io
import json
import os

SUITE = os.path.join("benchmark", "suites", "suite_rife", "clips")

# The painted box, in frame coordinates. Deliberately larger than MIN_MODEL_SIDE
# on both axes: the model's floor applies to the CROP around the mask, so a small
# painted region is refused even on a large frame.
MASK_BOX = (24, 24, 300, 300)      # left, top, right, bottom


def all_frames(clip_id: str) -> list[str]:
    frames = sorted(glob.glob(os.path.join(SUITE, clip_id, "*.png")))
    if not frames:
        raise SystemExit(f"no frames for clip {clip_id!r} under {SUITE}")
    return frames


def mask_data_url(width: int, height: int) -> str:
    """A white box on black — `mask > 8` selects, so black is 'leave alone'."""
    from PIL import Image, ImageDraw

    img = Image.new("L", (width, height), 0)
    ImageDraw.Draw(img).rectangle(MASK_BOX, fill=255)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def main(url: str, keys: list[str], id_token: str, passes: int) -> None:
    import httpx
    from PIL import Image

    from scripts.probe_qa_verdicts import _authenticate

    origin = url.rstrip("/")
    width, height = Image.open(keys[0]).size
    print(f"[repair] {len(keys)} keys, frames are {width}x{height}")

    with httpx.Client(timeout=1800.0, follow_redirects=False) as client:
        _authenticate(client, url, id_token)

        files = [("keys", (os.path.basename(p), open(p, "rb"), "image/png"))
                 for p in keys]
        result = None
        with client.stream("POST", f"{url}/session", data={"engines": "box"},
                           headers={"Origin": origin}, files=files) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("data: "):
                    payload = json.loads(line[6:])
                    if "artifacts" in payload:
                        result = payload
        if result is None:
            raise SystemExit("no result event received")

        sid = int(result["sid"])
        mids = result.get("pair_mids") or {}
        print(f"[repair] session {sid}: flagged={result['flagged']} "
              f"abstained={result['abstained']} needs_key={result['needs_key']}")
        print(f"[repair] pairs with a rendered mid: {sorted(mids, key=int)}")
        if not mids:
            raise SystemExit("no pair has a generated frame; nothing to repair")

        index = int(sorted(mids, key=int)[0])
        print(f"[repair] repairing pair {index}, position 1 (the in-between)")

        # Fetch the in-between BEFORE touching it. A changed QA verdict is not
        # evidence that the model wrote pixels; only the pixels are. Three
        # defects in this repo were artefacts that were generated, stored and
        # URL'd while nothing downstream had actually changed.
        before_png = client.get(f"{url}{mids[str(index)]}",
                                headers={"Origin": origin})
        before_bytes = before_png.content if before_png.status_code == 200 else b""
        print(f"[repair] mid before: HTTP {before_png.status_code}, "
              f"{len(before_bytes)} bytes")

        body = {"masks": [{"frame": 1, "png": mask_data_url(width, height)}],
                "refinement_passes": passes}
        with client.stream("POST", f"{url}/session/{sid}/pair/{index}/repair",
                           headers={"Origin": origin,
                                    "Content-Type": "application/json"},
                           json=body) as r:
            if r.status_code != 200:
                r.read()
                # 422 names the rule that fired — that is the useful part.
                raise SystemExit(f"repair refused: HTTP {r.status_code}: "
                                 f"{r.text[:400]}")
            after = None
            for line in r.iter_lines():
                if not line.startswith("data: "):
                    continue
                payload = json.loads(line[6:])
                if "phase" in payload:
                    print(f"[repair]   {payload['phase']}")
                elif "message" in payload:
                    print(f"[repair]   ERROR {payload['message']}")
                elif "artifacts" in payload:
                    after = payload

        after_url = (after or {}).get("pair_mids", {}).get(str(index))
        after_bytes = b""
        if after_url:
            got = client.get(f"{url}{after_url}", headers={"Origin": origin})
            after_bytes = got.content if got.status_code == 200 else b""
            print(f"[repair] mid after : HTTP {got.status_code}, "
                  f"{len(after_bytes)} bytes  url={'same' if after_url == mids[str(index)] else 'new'}")

    if after is None:
        raise SystemExit("repair stream ended with no result event")

    import hashlib

    def _h(b):
        return hashlib.sha256(b).hexdigest()[:16] if b else "(none)"

    print(f"\n[repair] PIXELS before sha256={_h(before_bytes)} "
          f"after sha256={_h(after_bytes)}")
    if before_bytes and after_bytes:
        print("[repair] the in-between "
              + ("CHANGED — the model wrote pixels"
                 if before_bytes != after_bytes else
                 "IS BYTE-IDENTICAL — the repair did NOT touch the drawing"))

    print(f"\n[repair] AFTER: flagged={after['flagged']} "
          f"abstained={after['abstained']} n_autopass={after['n_autopass']} "
          f"n_corrected={after['n_corrected']}")
    was_flagged = index in result["flagged"]
    was_abstained = index in result["abstained"]
    now_flagged = index in after["flagged"]
    now_abstained = index in after["abstained"]
    print(f"[repair] pair {index}: "
          f"before flagged={was_flagged} abstained={was_abstained} -> "
          f"after flagged={now_flagged} abstained={now_abstained}")
    print("[repair] The loop re-judged the repaired frame. A verdict that still "
          "refuses is a WORKING loop, not a failed repair.")
    print(f"[repair] session {sid} is on the live deployment — delete it after.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://inbetween-copilot.click")
    ap.add_argument("--clip", default="f000")
    ap.add_argument("--passes", type=int, default=1)
    ap.add_argument("--max-keys", type=int, default=0,
                    help="use only the first N frames as keys, to find the "
                         "smallest cut that clears MIN_MODEL_FRAMES")
    ap.add_argument("--id-token-file", required=True)
    a = ap.parse_args()
    with open(a.id_token_file, encoding="utf-8") as fh:
        token = fh.read().strip()
    keys = all_frames(a.clip)
    if a.max_keys:
        keys = keys[:a.max_keys]
    main(a.url, keys, token, a.passes)
