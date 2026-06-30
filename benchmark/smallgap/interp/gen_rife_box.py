"""BOX-ONLY RIFE generator for the small-gap probe. Loads Practical-RIFE once,
RIFEs the mid of each (a, b) source pair, writes mids to disk. Mirrors
service.engines.box_engines.rife_engine exactly so probe ghosts == production
ghosts. Run on the box:  ~/cogvideo-venv/bin/python gen_rife_box.py --pairs
pairs.json --out ~/rife_probe/mids"""
from __future__ import annotations

import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, "/home/long/Practical-RIFE")
import torch                                            # noqa: E402
from torch.nn import functional as F                    # noqa: E402
from train_log.RIFE_HDv3 import Model                   # noqa: E402


def _load_model():
    device = torch.device("cuda")
    torch.set_grad_enabled(False)
    m = Model()
    m.load_model("/home/long/Practical-RIFE/train_log", -1)
    m.eval()
    m.device()
    return m, device


def _rife_mid(model, device, a, b):
    def prep(x):
        return (torch.tensor(x.transpose(2, 0, 1)).to(device).float() / 255.).unsqueeze(0)
    i0, i1 = prep(a), prep(b)
    _, c, h, w = i0.shape
    ph = ((h - 1) // 64 + 1) * 64
    pw = ((w - 1) // 64 + 1) * 64
    i0 = F.pad(i0, (0, pw - w, 0, ph - h))
    i1 = F.pad(i1, (0, pw - w, 0, ph - h))
    mid = model.inference(i0, i1)
    return (mid[0] * 255).byte().cpu().numpy().transpose(1, 2, 0)[:h, :w]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", required=True)   # {clip_id: [a0,b0,a1,b1,...]}
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    pairs = json.load(open(args.pairs))
    model, device = _load_model()
    for cid, flat in pairs.items():
        d = os.path.join(args.out, cid)
        os.makedirs(d, exist_ok=True)
        for k in range(len(flat) // 2):
            a = cv2.cvtColor(cv2.imread(flat[2 * k]), cv2.COLOR_BGR2RGB)
            b = cv2.cvtColor(cv2.imread(flat[2 * k + 1]), cv2.COLOR_BGR2RGB)
            mid = _rife_mid(model, device, a, b)
            cv2.imwrite(os.path.join(d, f"mid_{k}.png"),
                        cv2.cvtColor(mid, cv2.COLOR_RGB2BGR))
    print(f"wrote mids for {len(pairs)} clips to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
