"""In-Between Co-pilot — box demo client.

Decodes a video cut, keeps every stride-th frame as a key, POSTs to the
/session endpoint, streams SSE events, and downloads the session artifacts.

Usage:
    python -m service.demo_client --cut <mp4> --stride 2 --out <dir> [--url http://localhost:8000]

The client does NOT require a running GPU; it delegates all heavy work to the
server.  Use --engines box to route to real model callables on the box.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import tempfile

import cv2
import httpx


def decode_keys(cut_path: str, stride: int) -> list[str]:
    """Decode *cut_path* with cv2, keep every *stride*-th frame; write PNGs to
    a temp dir and return the sorted list of PNG paths."""
    cap = cv2.VideoCapture(cut_path)
    if not cap.isOpened():
        print(f"[demo_client] ERROR: cannot open {cut_path!r}", file=sys.stderr)
        sys.exit(1)

    tmp = tempfile.mkdtemp(prefix="copilot_keys_")
    paths = []
    idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        if idx % stride == 0:
            p = os.path.join(tmp, f"{len(paths):06d}.png")
            cv2.imwrite(p, frame)
            paths.append(p)
        idx += 1
    cap.release()

    if len(paths) < 2:
        print(
            f"[demo_client] ERROR: need >= 2 key frames; got {len(paths)} "
            f"(stride={stride}, total_frames={idx})",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"[demo_client] decoded {idx} frames -> {len(paths)} keys (stride={stride})")
    return paths


def post_session(key_paths: list[str], url: str, engines: str) -> httpx.Response:
    """POST to /session with the key PNGs as multipart files.  Returns the raw
    streaming response (the caller iterates SSE lines)."""
    client = httpx.Client(timeout=None)
    with contextlib.ExitStack() as stack:
        files = [
            ("keys", (os.path.basename(p), stack.enter_context(open(p, "rb")), "image/png"))
            for p in sorted(key_paths)
        ]
        resp = client.post(
            f"{url}/session",
            files=files,
            data={"engines": engines},
        )
    return resp


def download_artifacts(artifacts: dict, url: str, out_dir: str) -> None:
    """Download all artifact URLs into *out_dir*."""
    os.makedirs(out_dir, exist_ok=True)
    for name, path_url in artifacts.items():
        full = url + path_url if path_url.startswith("/") else path_url
        out_file = os.path.join(out_dir, os.path.basename(path_url))
        r = httpx.get(full, timeout=60)
        if r.status_code == 200:
            with open(out_file, "wb") as fh:
                fh.write(r.content)
            print(f"[demo_client]   saved {name} -> {out_file}")
        else:
            print(f"[demo_client]   WARN: could not fetch {path_url} ({r.status_code})")


def main(argv=None):
    parser = argparse.ArgumentParser(description="In-Between Co-pilot demo client")
    parser.add_argument("--cut",     required=True, help="Path to an mp4 video cut")
    parser.add_argument("--stride",  type=int, default=2, help="Keep every N-th frame as a key")
    parser.add_argument("--out",     required=True, help="Output directory for artifacts")
    parser.add_argument("--url",     default="http://localhost:8000", help="Service URL")
    parser.add_argument("--engines", default="stub", choices=["stub", "box"],
                        help="Engine set (stub=box-free, box=real models)")
    args = parser.parse_args(argv)

    # 1. decode keys
    key_paths = decode_keys(args.cut, args.stride)

    # 2. stream session
    print(f"[demo_client] POST {args.url}/session  ({len(key_paths)} keys, engines={args.engines})")
    resp = post_session(key_paths, args.url, args.engines)
    if resp.status_code != 200:
        print(f"[demo_client] ERROR: server returned {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)

    artifacts = {}
    event = ""
    for line in resp.text.splitlines():
        line = line.strip()
        if line.startswith("event:"):
            event = line[len("event:"):].strip()
            print(f"[demo_client] {line}")
        elif line.startswith("data:"):
            payload = line[len("data:"):].strip()
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                print(f"[demo_client]   (raw) {payload}")
                continue
            print(f"[demo_client]   {json.dumps(data, indent=2)}")
            if event == "result" and "artifacts" in data:
                artifacts = data["artifacts"]

    # 3. download artifacts
    if artifacts:
        print(f"[demo_client] downloading artifacts -> {args.out}")
        download_artifacts(artifacts, args.url, args.out)
    else:
        print("[demo_client] WARN: no artifacts in result event")

    print(f"[demo_client] DONE -> {args.out}")


if __name__ == "__main__":
    main()
