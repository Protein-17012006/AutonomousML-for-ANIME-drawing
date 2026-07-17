import os
import stat
from pathlib import Path

import cv2
import numpy as np
import pytest

from benchmark.largegap.clips import write_eval_clip
from benchmark.largegap.ldf_runner import collect_frames, lq_parity, run_ldf


def _write_fake_infer(tmp_path: Path) -> Path:
    """A stand-in infer.sh that records its env and emits 5 PNG frames."""
    sh = tmp_path / "infer.sh"
    sh.write_text(
        "#!/bin/bash\nset -e\nmkdir -p \"$OUT/frames\" \"$OUT/lq\"\n"
        "echo \"MODEL=$MODEL TSF=$TSF STEPS=$STEPS DATA=$DATA\" > \"$OUT/env.txt\"\n"
        "python - <<'EOF'\n"
        "import os, numpy as np, cv2\n"
        "out = os.environ['OUT']\n"
        "for i in range(5):\n"
        "    cv2.imwrite(f'{out}/frames/{i:05d}.png', np.full((8,8,3), i*10, np.uint8))\n"
        "for j, i in enumerate([0, 4]):\n"
        "    cv2.imwrite(f'{out}/lq/{j:05d}.png', np.full((8,8,3), i*10, np.uint8))\n"
        "EOF\n")
    sh.chmod(sh.stat().st_mode | stat.S_IEXEC)
    return sh


def test_run_ldf_passes_env_and_collects_frames(tmp_path):
    sh = _write_fake_infer(tmp_path)
    clip = tmp_path / "eval.mp4"
    write_eval_clip([np.zeros((8, 8, 3), np.uint8)] * 5, clip)
    out = tmp_path / "out"
    run_ldf(sh, tmp_path / "model", clip, tsf=4, out_dir=out, steps=40)
    env = (out / "env.txt").read_text()
    assert "TSF=4" in env and "STEPS=40" in env
    frames = collect_frames(out, expect_n=5)
    assert len(frames) == 5
    assert frames[3][0, 0, 0] == 30


def test_collect_frames_from_mp4_fallback(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    write_eval_clip([np.full((8, 8, 3), v, np.uint8) for v in (0, 60, 120)],
                    out / "restored.mp4")
    frames = collect_frames(out, expect_n=3)
    assert len(frames) == 3


def test_collect_frames_from_real_nested_pred_layout(tmp_path):
    out = tmp_path / "out" / "input"
    out.mkdir(parents=True)
    write_eval_clip(
        [np.full((8, 8, 3), value, np.uint8) for value in (0, 60, 120)],
        out / "pred.mp4",
    )
    write_eval_clip([np.zeros((8, 8, 3), np.uint8)], out / "lq.mp4")
    frames = collect_frames(tmp_path / "out", expect_n=3)
    assert len(frames) == 3


def test_collect_frames_count_mismatch_raises(tmp_path):
    out = tmp_path / "out"
    (out / "frames").mkdir(parents=True)
    cv2.imwrite(str(out / "frames" / "00000.png"), np.zeros((8, 8, 3), np.uint8))
    with pytest.raises(RuntimeError):
        collect_frames(out, expect_n=5)


def test_lq_parity(tmp_path):
    sh = _write_fake_infer(tmp_path)
    clip = tmp_path / "eval.mp4"
    write_eval_clip([np.zeros((8, 8, 3), np.uint8)] * 5, clip)
    out = tmp_path / "out"
    run_ldf(sh, tmp_path / "model", clip, tsf=4, out_dir=out)
    keys = [np.full((8, 8, 3), 0, np.uint8), np.full((8, 8, 3), 40, np.uint8)]
    assert lq_parity(out, keys) is True
    assert lq_parity(out, [k + 50 for k in keys]) is False
