"""Released-video-as-test: simulate the artist by hiding frames.

Decimate a real anime cut -> kept frames are the "artist keys", hidden frames
are GT. Run the co-pilot, reconstruct the hidden frames, score reconstruction
(PSNR/SSIM vs GT) and the self-QA (precision/recall vs per-frame error labels).
"""
from __future__ import annotations

from dataclasses import dataclass

from inbetween_copilot.signals.objective import psnr, ssim, PSNR_MAX


@dataclass
class CopilotEval:
    psnr: float
    ssim: float
    qa_precision: float
    qa_recall: float
    auto_pass_rate: float
    n_inbetweens: int


def _prf(flags, labels):
    tp = sum(1 for f, l in zip(flags, labels) if f and l)
    fp = sum(1 for f, l in zip(flags, labels) if f and not l)
    fn = sum(1 for f, l in zip(flags, labels) if (not f) and l)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return precision, recall


def score_eval(recon_frames: list, gt_frames: list,
               qa_flags: list, error_labels: list) -> CopilotEval:
    if not (len(recon_frames) == len(gt_frames) == len(qa_flags) == len(error_labels)):
        raise ValueError("score_eval: all inputs must be the same length")
    n = len(recon_frames)
    psnrs = [min(psnr(r, g), PSNR_MAX) for r, g in zip(recon_frames, gt_frames)]
    ssims = [ssim(r, g) for r, g in zip(recon_frames, gt_frames)]
    mean_psnr = float(sum(psnrs) / n) if n else 0.0
    precision, recall = _prf(qa_flags, error_labels)
    auto_pass = sum(1 for f in qa_flags if not f) / n if n else 0.0
    return CopilotEval(psnr=mean_psnr, ssim=sum(ssims) / n if n else 0.0,
                       qa_precision=precision, qa_recall=recall,
                       auto_pass_rate=auto_pass, n_inbetweens=n)


@dataclass
class CorrectionEval:
    n_flagged: int
    correction_recall: float
    n_needs_key: int
    n_unresolved: int
    mean_psnr_gain: float


def score_correction(results, before_frames, after_frames, gt_frames) -> CorrectionEval:
    n = len(results)
    resolved = sum(1 for r in results if r.status == "resolved")
    needs_key = sum(1 for r in results if r.status == "needs_key")
    unresolved = sum(1 for r in results if r.status == "unresolved")
    gains = []
    for r, bf, af, g in zip(results, before_frames, after_frames, gt_frames):
        if r.status == "resolved":
            gains.append(min(psnr(af, g), PSNR_MAX) - min(psnr(bf, g), PSNR_MAX))
    return CorrectionEval(
        n_flagged=n,
        correction_recall=(resolved / n) if n else 0.0,
        n_needs_key=needs_key,
        n_unresolved=unresolved,
        mean_psnr_gain=float(sum(gains) / len(gains)) if gains else 0.0)


@dataclass
class DirectorComparison:
    director_recall: float
    fixed_recall: float
    director_mean_rounds: float
    fixed_mean_rounds: float


def director_vs_fixed(director_results, fixed_results) -> DirectorComparison:
    def recall(rs):
        return sum(1 for r in rs if r.status == "resolved") / len(rs) if rs else 0.0

    def mean_rounds(rs):
        return sum(len(r.rounds) for r in rs) / len(rs) if rs else 0.0

    return DirectorComparison(
        director_recall=recall(director_results),
        fixed_recall=recall(fixed_results),
        director_mean_rounds=mean_rounds(director_results),
        fixed_mean_rounds=mean_rounds(fixed_results))
