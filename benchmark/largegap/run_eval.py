"""Stage-based, resume-safe orchestrator for ``largegap_go_v1``.

Stages:
  select  source scenes -> canonical 65-frame clips and manifest
  keys    canonical frames -> per-TSF sparse key sets
  gen     keys -> dense reconstructions for local or LDF engines
  score   hold-aware/raw PSNR and SSIM, win rates, evidence montages
  reqa    production detector flag rates, including a GT control
  report  merge metrics into the tracked GO/NO-GO result
"""
from __future__ import annotations

import argparse
import datetime as _dt
import glob
import json
import math
from pathlib import Path

import cv2
import numpy as np

from benchmark.largegap.clips import decode_video, select_clip, write_eval_clip
from benchmark.largegap.montage import strip
from benchmark.largegap.reconstruct import blend_recon, hold_copy_recon, rife_recon
from benchmark.largegap.reqa import flag_clip, flag_rate
from benchmark.largegap.score import aggregate, dup_mask, score_frames, win_rate
from benchmark.largegap.span import plan_span
from benchmark.lib.signals.motion_primitives import load_frames

GO_RULE = (
    "OOD tsf 8 & 16: ldf_ft > rife on psnr_hold AND ssim_hold "
    "AND reqa <= rife"
)

CAVEATS = [
    "ID tier is contaminated at show level (all 24 archive series including "
    "Wistoria were in LDF-FT training; ID measures within-show generalization only)",
    "even decimation differs from uneven production key spacing",
    "OOD source (Clevatess ep1) is a hardsubbed stream-rip (hardsub-filtered "
    "scenes only; source compression noted)",
]

LOCAL_ENGINES = {
    "hold": hold_copy_recon,
    "blend": blend_recon,
    "rife": rife_recon,
}
LDF_ENGINES = {"ldf_ft", "ldf_pre"}


def _json_read(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def _json_write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=1, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def _json_number(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _mean_known(values) -> float | None:
    known = [float(value) for value in values if value is not None]
    return float(np.mean(known)) if known else None


def _manifest_path(root: Path, manifest: Path | None) -> Path:
    return manifest if manifest is not None else root / "manifest.json"


def _frames_of(clip_dir: Path) -> list[np.ndarray]:
    paths = sorted((clip_dir / "frames").glob("*.png"))
    return load_frames([str(path) for path in paths])


def _write_pngs(frames: list[np.ndarray], directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.png"):
        old.unlink()
    for index, frame in enumerate(frames):
        destination = directory / f"{index:05d}.png"
        ok = cv2.imwrite(
            str(destination), cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))
        if not ok:
            raise RuntimeError(f"failed to write frame: {destination}")


def _manifest(root: Path, manifest: Path | None = None) -> dict:
    path = _manifest_path(root, manifest)
    if not path.exists():
        raise FileNotFoundError(f"manifest does not exist: {path}")
    return _json_read(path, {})


def _kept(
    root: Path,
    manifest: Path | None = None,
    tiers: list[str] | None = None,
) -> list[dict]:
    wanted = set(tiers) if tiers else None
    return [
        row for row in _manifest(root, manifest)["clips"]
        if row["kept"] and (wanted is None or row["tier"] in wanted)
    ]


def _selection_complete(root: Path, row: dict) -> bool:
    if not row.get("kept"):
        return True
    clip_dir = root / "clips" / row["clip_id"]
    return (
        (clip_dir / "eval.mp4").is_file()
        and len(list((clip_dir / "frames").glob("*.png"))) == 65
    )


def _next_clip_id(rows: list[dict], tier: str) -> str:
    used = {row["clip_id"] for row in rows}
    index = 0
    while f"{tier}_{index:04d}" in used:
        index += 1
    return f"{tier}_{index:04d}"


def stage_select(
    root: Path,
    tiers: dict[str, list[Path]],
    motion_min: float = 0.01,
    manifest: Path | None = None,
) -> None:
    """Select sources once and preserve human-veto edits on resumed runs."""
    if not any(tiers.values()):
        raise ValueError("selection received no source paths")
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = _manifest_path(root, manifest)
    document = _json_read(
        manifest_path, {"suite": "largegap_go_v1", "clips": []})
    rows = document.get("clips", [])
    by_source = {
        (row["tier"], str(Path(row["src"]).expanduser().resolve())): row
        for row in rows
    }
    changed = False

    for tier, sources in tiers.items():
        for source in sorted({Path(path).expanduser().resolve() for path in sources}):
            key = (tier, str(source))
            previous = by_source.get(key)
            if previous is not None and _selection_complete(root, previous):
                continue
            clip_id = previous["clip_id"] if previous else _next_clip_id(rows, tier)
            row = select_clip(source, clip_id, tier, root / "clips", motion_min)
            if previous is None:
                rows.append(row)
            else:
                rows[rows.index(previous)] = row
            by_source[key] = row
            changed = True
            # Selection can take minutes on long source scenes.  Persist each
            # completed row so an SSH drop resumes instead of rescanning the
            # entire pool.
            _json_write(
                manifest_path, {"suite": "largegap_go_v1", "clips": rows})

    if changed or not manifest_path.exists():
        _json_write(manifest_path, {"suite": "largegap_go_v1", "clips": rows})

    kept = [row for row in rows if row.get("kept")]
    for start in range(0, len(kept), 6):
        batch = kept[start:start + 6]
        destination = root / "montages" / f"select_{start // 6:02d}.jpg"
        if destination.exists() and not changed:
            continue
        strip(
            {
                row["clip_id"]: _frames_of(root / "clips" / row["clip_id"])
                for row in batch
            },
            col_idx=[0, 16, 32, 48, 64],
            out_jpg=destination,
        )


def stage_keys(
    root: Path,
    tsfs: list[int],
    tiers: list[str] | None = None,
    manifest: Path | None = None,
) -> None:
    for row in _kept(root, manifest, tiers):
        frames = _frames_of(root / "clips" / row["clip_id"])
        for tsf in tsfs:
            plan = plan_span(len(frames), tsf)
            directory = root / "keys" / row["clip_id"] / f"tsf{tsf}"
            keys = [frames[index] for index in plan.key_idx]
            if len(list(directory.glob("*.png"))) != len(plan.key_idx):
                _write_pngs(keys, directory)
            input_mp4 = directory / "input.mp4"
            if not input_mp4.exists():
                write_eval_clip(keys, input_mp4)
            decoded = decode_video(input_mp4, max_frames=len(keys) + 1)
            if len(decoded) != len(keys) or any(
                int(np.abs(got.astype(int) - expected.astype(int)).max()) > 2
                for got, expected in zip(decoded, keys)
            ):
                raise RuntimeError(
                    f"canonical key-video parity FAILED: {row['clip_id']} tsf{tsf}")


def _recon_dir(root: Path, engine: str, clip_id: str, tsf: int) -> Path:
    return root / "recon" / engine / clip_id / f"tsf{tsf}"


def _validate_ldf_cfg(engine: str, ldf_cfg: dict | None) -> dict:
    cfg = ldf_cfg or {}
    models = cfg.get("models") or {}
    missing = [name for name, value in {
        "infer_sh": cfg.get("infer_sh"),
        f"models.{engine}": models.get(engine),
    }.items() if value is None]
    if missing:
        raise ValueError(f"missing LDF configuration: {', '.join(missing)}")
    return cfg


def stage_gen(
    root: Path,
    engines: list[str],
    tsfs: list[int],
    rife_engine=None,
    ldf_cfg: dict | None = None,
    tiers: list[str] | None = None,
    manifest: Path | None = None,
) -> None:
    """Generate only incomplete arms; a rerun resumes at the first gap."""
    unknown = set(engines) - set(LOCAL_ENGINES) - LDF_ENGINES
    if unknown:
        raise ValueError(f"unknown engines: {', '.join(sorted(unknown))}")

    for row in _kept(root, manifest, tiers):
        clip_id = row["clip_id"]
        frames = _frames_of(root / "clips" / clip_id)
        for tsf in tsfs:
            plan = plan_span(len(frames), tsf)
            keys = [frames[index] for index in plan.key_idx]
            for engine in engines:
                recon_dir = _recon_dir(root, engine, clip_id, tsf)
                if len(list(recon_dir.glob("*.png"))) == plan.n_used:
                    continue

                if engine in {"hold", "blend"}:
                    recon = LOCAL_ENGINES[engine](keys, plan)
                elif engine == "rife":
                    if rife_engine is None:
                        from benchmark.largegap.engines_box import load_rife_engine
                        rife_engine = load_rife_engine()
                    recon = rife_recon(keys, plan, rife_engine)
                else:
                    from benchmark.largegap.ldf_runner import (
                        collect_frames,
                        lq_parity,
                        run_ldf,
                    )
                    cfg = _validate_ldf_cfg(engine, ldf_cfg)
                    raw_dir = root / "ldf_raw" / engine / clip_id / f"tsf{tsf}"
                    input_mp4 = root / "keys" / clip_id / f"tsf{tsf}" / "input.mp4"
                    if not input_mp4.exists():
                        raise RuntimeError(
                            f"missing LDF key video; run keys stage first: {input_mp4}")
                    run_ldf(
                        cfg["infer_sh"],
                        cfg["models"][engine],
                        input_mp4,
                        tsf,
                        raw_dir,
                        steps=cfg.get("steps", 16),
                        ldf_root=cfg.get("ldf_root"),
                        timeout_s=cfg.get("timeout_s", 7200),
                        max_chunks=cfg.get("max_chunks"),
                    )
                    if not lq_parity(raw_dir, keys, tol=cfg.get("lq_tol", 16)):
                        raise RuntimeError(
                            f"lq parity FAILED: {engine} {clip_id} tsf{tsf}")
                    recon = collect_frames(raw_dir, expect_n=plan.n_used)
                _write_pngs(recon, recon_dir)


def _evidence_columns(n_used: int, tsf: int, limit: int = 5) -> list[int]:
    midpoints = list(range(tsf // 2, n_used, tsf))
    if len(midpoints) <= limit:
        return midpoints
    positions = sorted({
        int(round(value))
        for value in np.linspace(0, len(midpoints) - 1, limit)
    })
    return [midpoints[index] for index in positions]


def _write_evidence_montage(
    root: Path,
    tier: str,
    clip_id: str,
    tsf: int,
    gt: list[np.ndarray],
) -> None:
    paths = {
        engine: sorted(_recon_dir(root, engine, clip_id, tsf).glob("*.png"))
        for engine in ("rife", "ldf_ft")
    }
    if any(len(engine_paths) != len(gt) for engine_paths in paths.values()):
        return
    destination = (
        root / "montages" / "evidence" / tier / f"tsf{tsf}" / f"{clip_id}.jpg")
    if destination.exists():
        return
    strip(
        {"gt": gt, **{
            engine: load_frames([str(path) for path in engine_paths])
            for engine, engine_paths in paths.items()
        }},
        _evidence_columns(len(gt), tsf),
        destination,
    )


def stage_score(
    root: Path,
    engines: list[str],
    tsfs: list[int],
    tiers: list[str] | None = None,
    manifest: Path | None = None,
) -> None:
    output: dict = _json_read(root / "scores.json", {})
    per_clip: dict[tuple[str, int, str], dict[str, dict]] = {}

    for row in _kept(root, manifest, tiers):
        clip_id, tier = row["clip_id"], row["tier"]
        full_gt = _frames_of(root / "clips" / clip_id)
        for tsf in tsfs:
            plan = plan_span(len(full_gt), tsf)
            gt = full_gt[:plan.n_used]
            duplicates = dup_mask(gt)
            for engine in engines:
                recon_paths = sorted(_recon_dir(
                    root, engine, clip_id, tsf).glob("*.png"))
                if len(recon_paths) != plan.n_used:
                    continue
                recon = load_frames([str(path) for path in recon_paths])
                rows = score_frames(gt, recon, plan.mid_idx, duplicates)
                per_clip.setdefault((tier, tsf, engine), {})[clip_id] = aggregate(rows)
            _write_evidence_montage(root, tier, clip_id, tsf, gt)

    for (tier, tsf, engine), clip_aggs in per_clip.items():
        aggregates = list(clip_aggs.values())
        engine_out = output.setdefault(tier, {}).setdefault(str(tsf), {})
        engine_out[engine] = {
            "psnr_hold": _mean_known(a["psnr_hold"] for a in aggregates),
            "ssim_hold": _mean_known(a["ssim_hold"] for a in aggregates),
            "psnr_raw": _mean_known(a["psnr_raw"] for a in aggregates),
            "ssim_raw": _mean_known(a["ssim_raw"] for a in aggregates),
            "n_scored": int(sum(a["n_scored"] for a in aggregates)),
            "n_held": int(sum(a["n_held"] for a in aggregates)),
            "n_clips": len(aggregates),
            "win_rate_vs_rife": None,
        }

    for (tier, tsf, engine), clip_aggs in per_clip.items():
        if engine == "rife":
            continue
        rife_aggs = per_clip.get((tier, tsf, "rife"))
        if not rife_aggs:
            continue
        common = sorted(set(clip_aggs) & set(rife_aggs))
        if not common:
            continue
        rate = win_rate(
            [clip_aggs[clip_id] for clip_id in common],
            [rife_aggs[clip_id] for clip_id in common],
        )
        output[tier][str(tsf)][engine]["win_rate_vs_rife"] = _json_number(rate)

    _json_write(root / "scores.json", output)


def _existing_verdicts(root: Path) -> dict[tuple[str, str, str, str], dict]:
    document = _json_read(root / "reqa.json", {"verdicts": {}})
    indexed = {}
    for tier, by_tsf in document.get("verdicts", {}).items():
        for tsf, by_engine in by_tsf.items():
            for engine, verdicts in by_engine.items():
                for verdict in verdicts:
                    clip_id = verdict.get("clip_id")
                    if clip_id:
                        indexed[(tier, tsf, engine, clip_id)] = verdict
    return indexed


def stage_reqa(
    root: Path,
    engines: list[str],
    tsfs: list[int],
    vision_fn=None,
    tiers: list[str] | None = None,
    manifest: Path | None = None,
) -> None:
    """Run only missing detector calls and retain per-clip audit records."""
    indexed = _existing_verdicts(root)
    gt_cache: dict[str, dict] = {
        clip_id: verdict
        for (_tier, _tsf, engine, clip_id), verdict in indexed.items()
        if engine == "gt"
    }

    for row in _kept(root, manifest, tiers):
        clip_id, tier = row["clip_id"], row["tier"]
        for tsf in tsfs:
            for engine in ["gt"] + engines:
                key = (tier, str(tsf), engine, clip_id)
                if key in indexed:
                    if engine == "gt":
                        gt_cache[clip_id] = indexed[key]
                    continue
                directory = (
                    root / "clips" / clip_id / "frames"
                    if engine == "gt"
                    else _recon_dir(root, engine, clip_id, tsf)
                )
                paths = [str(path) for path in sorted(directory.glob("*.png"))]
                if not paths:
                    continue
                if engine == "gt" and clip_id in gt_cache:
                    verdict = dict(gt_cache[clip_id])
                else:
                    verdict = flag_clip(paths, vision_fn=vision_fn)
                verdict = {"clip_id": clip_id, **verdict}
                indexed[key] = verdict
                if engine == "gt":
                    gt_cache[clip_id] = verdict

    verdicts: dict = {}
    for (tier, tsf, engine, _clip_id), verdict in sorted(indexed.items()):
        verdicts.setdefault(tier, {}).setdefault(tsf, {}).setdefault(
            engine, []).append(verdict)
    rates = {
        tier: {
            tsf: {
                engine: _json_number(flag_rate(engine_verdicts))
                for engine, engine_verdicts in by_engine.items()
            }
            for tsf, by_engine in by_tsf.items()
        }
        for tier, by_tsf in verdicts.items()
    }
    _json_write(root / "reqa.json", {"rates": rates, "verdicts": verdicts})


def _finite_metric(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def go_verdict(scores: dict, reqa: dict | None) -> dict:
    """Apply the frozen per-TSF decision rule and fail closed on missing data."""
    detail: dict = {}
    passes = []
    for tsf in ("8", "16"):
        score_arms = scores.get("ood", {}).get(tsf, {})
        ldf = score_arms.get("ldf_ft")
        rife = score_arms.get("rife")
        reqa_arms = (reqa or {}).get("ood", {}).get(tsf, {})
        ldf_reqa = reqa_arms.get("ldf_ft")
        rife_reqa = reqa_arms.get("rife")
        needed = [
            (ldf or {}).get("psnr_hold"),
            (ldf or {}).get("ssim_hold"),
            (rife or {}).get("psnr_hold"),
            (rife or {}).get("ssim_hold"),
            ldf_reqa,
            rife_reqa,
        ]
        complete = all(_finite_metric(value) for value in needed)
        checks = {
            "psnr": complete and ldf["psnr_hold"] > rife["psnr_hold"],
            "ssim": complete and ldf["ssim_hold"] > rife["ssim_hold"],
            "reqa": complete and ldf_reqa <= rife_reqa,
        }
        passed = complete and all(checks.values())
        detail[tsf] = {
            "pass": passed,
            "complete": complete,
            "checks": checks,
            "ldf_ft": {"score": ldf, "reqa": ldf_reqa},
            "rife": {"score": rife, "reqa": rife_reqa},
        }
        passes.append(passed)
    return {"rule": GO_RULE, "verdict": all(passes), "detail": detail}


def stage_report(
    root: Path,
    results_json: Path,
    tsfs: list[int],
    reqa: dict | None = None,
    ckpt: str = "checkpoint-9334",
) -> dict:
    scores = _json_read(root / "scores.json", {})
    if reqa is None and (root / "reqa.json").exists():
        reqa = _json_read(root / "reqa.json", {})["rates"]
    result = {
        "suite": "largegap_go_v1",
        "date": _dt.date.today().isoformat(),
        "ckpt": ckpt,
        "tsfs": tsfs,
        "caveats": CAVEATS,
        "scores": scores,
        "reqa": reqa,
        "go": go_verdict(scores, reqa),
    }
    _json_write(results_json, result)
    return result


def _list_paths(path: Path) -> list[Path]:
    paths = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        candidate = Path(line).expanduser()
        if not candidate.is_absolute():
            relative = path.parent / candidate
            candidate = relative if relative.exists() else candidate
        paths.append(candidate)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "stage", choices=["select", "keys", "gen", "score", "reqa", "report"])
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument(
        "--manifest", type=Path,
        help="shared manifest (default: <root>/manifest.json)")
    parser.add_argument("--ood-glob", help="select: glob of OOD scene mp4s")
    parser.add_argument(
        "--id-list", type=Path, help="select: file of ID clip paths")
    parser.add_argument(
        "--engines", nargs="+",
        default=["hold", "blend", "rife", "ldf_pre", "ldf_ft"])
    parser.add_argument("--tsfs", nargs="+", type=int, default=[2, 4, 8, 16])
    parser.add_argument(
        "--tiers", nargs="+", choices=["ood", "id"],
        help="limit non-select stages to tiers (needed for ID's 2/8/16 sweep)")
    parser.add_argument("--motion-min", type=float, default=0.01)
    parser.add_argument("--ldf-infer-sh", type=Path)
    parser.add_argument("--ldf-root", type=Path)
    parser.add_argument("--ldf-ft-model", type=Path)
    parser.add_argument("--ldf-pre-model", type=Path)
    parser.add_argument("--ldf-steps", type=int, default=16)
    parser.add_argument("--ldf-max-chunks", type=int)
    parser.add_argument("--ldf-timeout-s", type=int, default=7200)
    parser.add_argument(
        "--ldf-lq-tol", type=int, default=16,
        help="max abs RGB delta allowed for generate.py's CRF-10 save_lq.mp4")
    parser.add_argument("--ckpt", default="checkpoint-9334")
    parser.add_argument(
        "--results-json", type=Path,
        default=Path("benchmark/results/largegap_go_v1.json"))
    args = parser.parse_args()

    if args.stage == "select":
        sources: dict[str, list[Path]] = {}
        if args.ood_glob:
            pattern = str(Path(args.ood_glob).expanduser())
            sources["ood"] = [Path(value) for value in glob.glob(pattern)]
        if args.id_list:
            sources["id"] = _list_paths(args.id_list.expanduser())
        if not sources:
            parser.error("select requires --ood-glob and/or --id-list")
        if not any(sources.values()):
            parser.error("select source patterns/lists matched no files")
        stage_select(args.root, sources, args.motion_min, args.manifest)
    elif args.stage == "keys":
        stage_keys(args.root, args.tsfs, args.tiers, args.manifest)
    elif args.stage == "gen":
        ldf_cfg = None
        if LDF_ENGINES & set(args.engines):
            ldf_cfg = {
                "infer_sh": args.ldf_infer_sh,
                "ldf_root": args.ldf_root,
                "steps": args.ldf_steps,
                "max_chunks": args.ldf_max_chunks,
                "timeout_s": args.ldf_timeout_s,
                "lq_tol": args.ldf_lq_tol,
                "models": {
                    "ldf_ft": args.ldf_ft_model,
                    "ldf_pre": args.ldf_pre_model,
                },
            }
        stage_gen(
            args.root, args.engines, args.tsfs,
            ldf_cfg=ldf_cfg, tiers=args.tiers, manifest=args.manifest)
    elif args.stage == "score":
        stage_score(args.root, args.engines, args.tsfs, args.tiers, args.manifest)
    elif args.stage == "reqa":
        stage_reqa(args.root, args.engines, args.tsfs,
                   tiers=args.tiers, manifest=args.manifest)
    else:
        stage_report(
            args.root, args.results_json, args.tsfs, ckpt=args.ckpt)


if __name__ == "__main__":
    main()
