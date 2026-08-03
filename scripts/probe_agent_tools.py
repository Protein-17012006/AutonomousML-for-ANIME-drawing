"""Ask the live agent one question per tool and record what it actually proposes.

Spec 6, unit acceptance. Answers two questions the server test suite cannot:

  1. does a real DeepSeek turn, on a real session, propose the tool we expect?
  2. does the server ACCEPT that proposal, or refuse it (`rejected_tool`)?

What it deliberately does NOT prove: that the client renders a button and that
pressing it changes the screen. `image_edit` passed 14 server test files while
being invisible in the browser, so the on-screen half needs a human. This driver
exists so the human knows exactly which sentence to type.

Usage — run as a MODULE from the repo root:

    python -m scripts.probe_agent_tools --url https://inbetween-copilot.click \\
        --clip f000 --id-token-file <path>
"""
from __future__ import annotations

import argparse
import json
import os

from scripts.probe_qa_verdicts import _authenticate, clip_keys

# One question per tool. The wording is the artist's, not the registry's — the
# point is what a person would actually type.
#
# `expect` is the tool the question should provoke, or the literal "none" where
# a REFUSAL is the correct answer. Two of those refusals are worth filming: they
# are the system declining to do something useless, which is the whole argument
# for a proposal-and-confirm design.
#
# The pair index matters. image_edit needs a pair that still HAS a generated
# frame: a flagged pair whose correction loop escalated to needs_key has none,
# and the server refuses it — correctly.
QUESTIONS: list[tuple[str, str]] = [
    ("explain_pair", "why was pair 1 flagged?"),
    ("show_annotated", "show me the marked image for pair 1"),
    ("open_board", "open pair 2 on the board"),
    ("image_edit", "I want to paint over the bad region on pair {mid_pair} myself"),
    ("export_bundle", "give me the bundle to download"),
    ("rerun_session", "re-run this cut at cadence 24"),
    ("none", "re-run this cut at smoothness x2"),      # already x2 -> must refuse
    ("remember_memory", "remember that my cadence is 12"),
]


def create_session(client, url: str, keys: list[str]) -> tuple[int, dict]:
    files = [("keys", (os.path.basename(p), open(p, "rb"), "image/png")) for p in keys]
    result = None
    with client.stream("POST", f"{url}/session", data={"engines": "box"},
                       headers={"Origin": url.rstrip("/")}, files=files) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("data: "):
                payload = json.loads(line[6:])
                if "artifacts" in payload:
                    result = payload
    if result is None:
        raise SystemExit("no result event received")
    return int(result["sid"]), result


def ask(client, url: str, sid: int, message: str) -> dict:
    r = client.post(f"{url}/session/{sid}/agent",
                    headers={"Origin": url.rstrip("/"),
                             "Content-Type": "application/json"},
                    json={"message": message})
    if r.status_code != 200:
        return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
    return r.json()


def main(url: str, keys: list[str], id_token: str) -> None:
    import httpx

    with httpx.Client(timeout=900.0, follow_redirects=False) as client:
        _authenticate(client, url, id_token)
        sid, result = create_session(client, url, keys)
        mids = result.get("pair_mids") or {}
        print(f"[agent] session {sid}: flagged={result['flagged']} "
              f"needs_key={result['needs_key']} "
              f"explanations={sorted(result.get('explanations') or {})}")
        # `_valid_repairable` needs a RENDERED mid, so ask about a pair that has
        # one instead of guessing an index. Empty here means image_edit cannot be
        # proposed on this session at all, which is itself the finding.
        print(f"[agent] pair_mids present for: {sorted(mids)}")
        mid_pair = sorted(mids, key=lambda k: int(k))[0] if mids else "0"

        rows = []
        for expected, template in QUESTIONS:
            message = template.format(mid_pair=mid_pair)
            reply = ask(client, url, sid, message)
            action = reply.get("action") or {}
            rows.append({
                "expected": expected,
                "message": message,
                "proposed": action.get("tool"),
                "needs_confirm": action.get("needs_confirm"),
                "label": action.get("label"),
                "rejected_tool": reply.get("rejected_tool"),
                "say": (reply.get("say") or "")[:110],
                "error": reply.get("error"),
            })
            print(f"\n[{expected}] {message!r}")
            print(f"   proposed   : {action.get('tool')}"
                  f"{' (confirm)' if action.get('needs_confirm') else ''}")
            if reply.get("rejected_tool"):
                print(f"   REFUSED by server: {reply['rejected_tool']}")
            if reply.get("error"):
                print(f"   ERROR: {reply['error']}")
            print(f"   says       : {(reply.get('say') or '')[:110]}")

        for row in rows:
            if row["expected"] == "none":
                row["ok"] = row["proposed"] is None
            else:
                row["ok"] = row["proposed"] == row["expected"]
        hits = [r for r in rows if r["ok"]]
        print(f"\n[agent] provoked as expected: {len(hits)}/{len(rows)}")
        for r in rows:
            if not r["ok"]:
                print(f"[agent]   MISS {r['expected']}: got {r['proposed']!r}"
                      f"{' rejected=' + r['rejected_tool'] if r['rejected_tool'] else ''}")
        print(f"\n[agent] session {sid} was created on the live deployment — "
              f"delete it when the capture is done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="https://inbetween-copilot.click")
    ap.add_argument("--clip", default="f000")
    ap.add_argument("--id-token-file", required=True,
                    help="file holding a Cognito ID token; never pass it on argv")
    a = ap.parse_args()
    with open(a.id_token_file, encoding="utf-8") as fh:
        token = fh.read().strip()
    main(a.url, clip_keys(a.clip), token)
