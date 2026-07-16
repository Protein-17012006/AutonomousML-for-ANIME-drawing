"""Run Long's LDF-VFI inference via his infer.sh (env contract: MODEL, DATA,
TSF, OUT, STEPS, optional LDF_ROOT + MAX_CHUNKS) and collect the restored
frames. infer.sh self-activates ldf-venv, so the harness venv stays clean.

Long's current generate.py writes ``<OUT>/<input-stem>/pred.mp4`` and
``lq.mp4``.  The collectors also retain PNG support for older exports.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np

from benchmark.largegap.clips import decode_video


def _shell_command(infer_sh: Path) -> tuple[list[str], bool]:
    """Return the bash command and whether it uses Git Bash path semantics.

    ``bash.exe`` on a current Windows PATH is often the WSL launcher.  WSL
    cannot open a ``C:/...`` script path or the Windows paths passed in the
    inference environment.  Prefer an explicit Git Bash installation there;
    on the Linux box the normal PATH lookup remains the right behaviour.
    """
    if os.name != "nt":
        return ["bash", str(infer_sh)], False

    override = os.environ.get("LDF_BASH_EXE")
    candidates = [Path(override)] if override else []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env_name)
        if root:
            candidates.append(Path(root) / "Git" / "bin" / "bash.exe")
    git_bash = next((p for p in candidates if p.is_file()), None)
    if git_bash is None:
        found = shutil.which("bash")
        if not found:
            raise RuntimeError(
                "bash is required to run LDF infer.sh; install Git Bash or "
                "set LDF_BASH_EXE")
        git_bash = Path(found)
    return [str(git_bash), infer_sh.resolve().as_posix()], True


def _env_path(path: Path | str, git_bash: bool) -> str:
    value = Path(path)
    return value.resolve().as_posix() if git_bash else str(value)


def run_ldf(infer_sh: Path | str, model_dir: Path | str, clip_mp4: Path | str,
            tsf: int, out_dir: Path | str, steps: int = 16,
            ldf_root: Path | str | None = None, timeout_s: int = 7200,
            max_chunks: int | None = None) -> None:
    infer_sh = Path(infer_sh)
    command, git_bash = _shell_command(infer_sh)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({"MODEL": _env_path(model_dir, git_bash),
                "DATA": _env_path(clip_mp4, git_bash),
                "TSF": str(tsf),
                "OUT": _env_path(out_dir, git_bash),
                "STEPS": str(steps)})
    if ldf_root is not None:
        env["LDF_ROOT"] = _env_path(ldf_root, git_bash)
    if max_chunks is not None:
        env["MAX_CHUNKS"] = str(max_chunks)
    subprocess.run(command, env=env, check=True, timeout=timeout_s)


def _pngs(d: Path) -> list[Path]:
    return sorted(d.rglob("*.png")) if d.is_dir() else []


def collect_frames(out_dir: Path | str, expect_n: int) -> list[np.ndarray]:
    out_dir = Path(out_dir)
    pngs = [p for p in _pngs(out_dir)
            if not any("lq" in part.lower() for part in p.parts)]
    if len(pngs) == expect_n:
        from benchmark.lib.signals.motion_primitives import load_frames
        return load_frames([str(p) for p in pngs])
    mp4s = sorted(out_dir.rglob("pred.mp4"))
    if not mp4s:
        mp4s = [p for p in sorted(out_dir.rglob("*.mp4"))
                if p.stem.lower() not in {"lq", "gt"}]
    if mp4s:
        frames = decode_video(mp4s[0], max_frames=expect_n + 8)
        if len(frames) >= expect_n:
            return frames[:expect_n]
    raise RuntimeError(
        f"LDF output mismatch in {out_dir}: {len(pngs)} pngs, "
        f"{len(mp4s)} mp4s, expected {expect_n} frames")


def lq_parity(out_dir: Path | str, keys: list[np.ndarray], tol: int = 2) -> bool:
    """Verify save_lq has the same key count/order within codec tolerance."""
    lq_dirs = [d for d in Path(out_dir).rglob("*") if d.is_dir() and "lq" in d.name]
    lq = []
    for d in lq_dirs:
        lq = _pngs(d)
        if lq:
            break
    from benchmark.lib.signals.motion_primitives import load_frames
    if lq:
        if len(lq) != len(keys):
            return False
        got = load_frames([str(p) for p in lq])
    else:
        videos = sorted(Path(out_dir).rglob("lq.mp4"))
        if len(videos) != 1:
            return False
        got = decode_video(videos[0], max_frames=len(keys) + 1)
        if len(got) != len(keys):
            return False
    return all(int(np.abs(g.astype(int) - k.astype(int)).max()) <= tol
               for g, k in zip(got, keys))
