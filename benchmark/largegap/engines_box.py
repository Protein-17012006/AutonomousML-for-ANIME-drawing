"""Box-only Practical-RIFE loader (CUDA; NOT unit-tested — exercised by the
Task 9 pilot). Same loading pattern as service/infrastructure/engines.py but
env-configured directly so the harness needs no service settings object.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def load_rife_engine():
    """-> engine(a, b) -> [a, mid, b] on uint8 HxWx3 RGB frames."""
    import torch
    import torch.nn.functional as F

    rife_root = Path(os.environ.get("RIFE_ROOT", str(Path.home() / "Practical-RIFE")))
    model_dir = Path(os.environ.get("RIFE_MODEL_DIR", str(rife_root / "train_log")))
    if str(rife_root) not in sys.path:
        sys.path.insert(0, str(rife_root))
    from train_log.RIFE_HDv3 import Model  # noqa: PLC0415

    device = torch.device("cuda")
    model = Model()
    model.load_model(str(model_dir), -1)
    model.eval()
    model.flownet.to(device)

    def engine(a, b):
        def prep(x):
            return (torch.tensor(x.transpose(2, 0, 1)).to(device).float() / 255.).unsqueeze(0)
        with torch.inference_mode():
            i0, i1 = prep(a), prep(b)
            _, _c, h, w = i0.shape
            ph = ((h - 1) // 64 + 1) * 64
            pw = ((w - 1) // 64 + 1) * 64
            i0 = F.pad(i0, (0, pw - w, 0, ph - h))
            i1 = F.pad(i1, (0, pw - w, 0, ph - h))
            mid = model.inference(i0, i1)
            mid_np = (mid[0] * 255).byte().cpu().numpy().transpose(1, 2, 0)[:h, :w]
        return [a, mid_np, b]

    return engine
