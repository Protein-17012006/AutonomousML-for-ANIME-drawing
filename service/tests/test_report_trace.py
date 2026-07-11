"""report.md must show the correction-loop director trace."""
import numpy as np

from inbetween_copilot.generate.correction import CorrectionResult, CorrectionRound
from inbetween_copilot.pipeline.copilot import CopilotResult, PairResult
from inbetween_copilot.qa.gate import FrameQA
from service.media.artifacts import build_report

_F = [np.zeros((4, 4, 3), np.uint8)] * 3


def test_report_renders_director_trace(tmp_path):
    rounds = [CorrectionRound("region_refill", None, None, reason="director: localized ghost"),
              CorrectionRound("escalate_engine", None, None, reason="fixed:round1")]
    corr = CorrectionResult("resolved", _F, rounds, 0, None)
    pairs = [
        PairResult(0, "filled", "rife", _F, FrameQA(status="pass", reason=""), 0),
        PairResult(1, "filled", "rife", _F, FrameQA(status="flag", reason="detector"), 0,
                   correction=corr),
    ]
    res = CopilotResult(pairs=pairs, keys_requested_total=0, flagged=[],
                        n_autopass=1, n_corrected=1)
    path = build_report(res, str(tmp_path))
    text = open(path, encoding="utf-8").read()
    assert "Correction loop (director trace)" in text
    assert "pair 1: resolved after 2 round(s)" in text
    assert "region_refill — director: localized ghost" in text
    assert "escalate_engine — fixed:round1" in text


def test_report_omits_trace_when_no_corrections(tmp_path):
    pairs = [PairResult(0, "filled", "rife", _F, FrameQA(status="pass", reason=""), 0)]
    res = CopilotResult(pairs=pairs, keys_requested_total=0, flagged=[], n_autopass=1)
    text = open(build_report(res, str(tmp_path)), encoding="utf-8").read()
    assert "Correction loop" not in text
