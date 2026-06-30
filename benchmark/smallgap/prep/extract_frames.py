"""Decode an mp4 to consecutive PNG frames with cv2 (no system ffmpeg on PATH).
Frames land as 0000.png, 0001.png, ... in decode order — the contiguous-segment
input scan_windows expects."""
from __future__ import annotations

import argparse
import os

import cv2


def extract_frames(video_path: str, out_dir: str, *, max_frames: int = 0,
                   width: int = 0, height: int = 0) -> int:
    """Decode to out_dir/0000.png... If width>0 and height>0, resize each frame
    to (width, height) — used to match the suite's 320x512 (HxW) clip scale and
    the detector's serve resolution."""
    os.makedirs(out_dir, exist_ok=True)
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open {video_path!r}")
    i = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if width and height:
                frame = cv2.resize(frame, (width, height),
                                   interpolation=cv2.INTER_AREA)
            cv2.imwrite(os.path.join(out_dir, f"{i:04d}.png"), frame)
            i += 1
            if max_frames and i >= max_frames:
                break
    finally:
        cap.release()
    return i


def main() -> int:
    ap = argparse.ArgumentParser(description="cv2 mp4 -> consecutive PNG frames")
    ap.add_argument("--video", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--width", type=int, default=0)
    ap.add_argument("--height", type=int, default=0)
    args = ap.parse_args()
    n = extract_frames(args.video, args.out, max_frames=args.max_frames,
                       width=args.width, height=args.height)
    print(f"wrote {n} frames to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
