import json

import numpy as np

from benchmark.largegap.clips import write_eval_clip
from benchmark.largegap.run_eval import (
    go_verdict,
    stage_gen,
    stage_keys,
    stage_report,
    stage_reqa,
    stage_score,
    stage_select,
)


def _mk_scene(tmp_path, name, n=70):
    frames = []
    for i in range(n):
        frame = np.zeros((64, 96, 3), dtype=np.uint8)
        position = (i * 3) % 160
        x = position if position <= 80 else 160 - position
        frame[24:40, x:x + 16] = 180
        frames.append(frame)
    path = tmp_path / name
    write_eval_clip(frames, path)
    return path


def test_pipeline_end_to_end_local_engines(tmp_path):
    scenes = [_mk_scene(tmp_path, f"s{i}.mp4") for i in range(2)]
    root = tmp_path / "root"
    stage_select(root, {"ood": scenes}, motion_min=0.0)
    manifest = json.loads((root / "manifest.json").read_text())
    kept = [row for row in manifest["clips"] if row["kept"]]
    assert len(kept) == 2

    stage_keys(root, tsfs=[2, 4])
    stage_gen(root, engines=["hold", "blend"], tsfs=[2, 4])
    stage_score(root, engines=["hold", "blend"], tsfs=[2, 4])
    scores = json.loads((root / "scores.json").read_text())
    assert scores["ood"]["2"]["blend"]["psnr_hold"] is not None

    result = stage_report(
        root,
        results_json=root / "largegap_go_v1.json",
        tsfs=[2, 4],
        reqa=None,
    )
    assert result["go"]["verdict"] is False


def test_gen_is_idempotent(tmp_path):
    scenes = [_mk_scene(tmp_path, "s0.mp4")]
    root = tmp_path / "root"
    stage_select(root, {"ood": scenes}, motion_min=0.0)
    stage_keys(root, tsfs=[2])
    stage_gen(root, engines=["hold"], tsfs=[2])
    first = sorted((root / "recon").rglob("*.png"))
    mtimes = {path: path.stat().st_mtime_ns for path in first}
    stage_gen(root, engines=["hold"], tsfs=[2])
    assert {path: path.stat().st_mtime_ns for path in first} == mtimes


def test_tier_filter_keeps_id_off_tsf4(tmp_path):
    root = tmp_path / "root"
    stage_select(root, {
        "ood": [_mk_scene(tmp_path, "ood.mp4")],
        "id": [_mk_scene(tmp_path, "id.mp4")],
    }, motion_min=0.0)
    stage_keys(root, tsfs=[4], tiers=["ood"])
    assert list((root / "keys" / "ood_0000" / "tsf4").glob("*.png"))
    assert not (root / "keys" / "id_0000" / "tsf4").exists()


def test_reqa_resumes_known_verdicts(tmp_path):
    root = tmp_path / "root"
    stage_select(root, {"ood": [_mk_scene(tmp_path, "s.mp4")]}, motion_min=0.0)
    stage_keys(root, [2])
    stage_gen(root, ["hold"], [2])
    calls = []

    def vision(prompt, paths, **kwargs):
        calls.append(paths)
        return {"has_motion_error": False, "explanation": "clean"}

    stage_reqa(root, ["hold"], [2], vision_fn=vision)
    assert len(calls) == 2  # GT control + hold
    stage_reqa(root, ["hold"], [2], vision_fn=vision)
    assert len(calls) == 2


def test_go_verdict_rule_and_missing_reqa_fails_closed():
    scores = {"ood": {str(tsf): {
        "ldf_ft": {"psnr_hold": 25.0, "ssim_hold": 0.9},
        "rife": {"psnr_hold": 24.0, "ssim_hold": 0.8},
    } for tsf in (8, 16)}}
    reqa = {"ood": {str(tsf): {"ldf_ft": 0.1, "rife": 0.2}
                     for tsf in (8, 16)}}
    assert go_verdict(scores, reqa)["verdict"] is True
    reqa["ood"]["16"]["ldf_ft"] = 0.5
    assert go_verdict(scores, reqa)["verdict"] is False
    assert go_verdict(scores, None)["verdict"] is False
