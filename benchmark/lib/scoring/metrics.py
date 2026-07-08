"""Shared precision/recall arithmetic (P4, architecture review 2026-07-08).

The tp/fp/fn -> precision/recall(/f1) body with its div-by-zero guards was
re-implemented in fusion.prf, motion_score and the widegap eval. One body here;
callers keep their own output SHAPES (caught/missed vocab, rounding, dicts) —
only the arithmetic is shared.
"""
from __future__ import annotations


def precision_recall(tp: int, fp: int, fn: int) -> "tuple[float, float, float]":
    """Return (precision, recall, f1), each 0.0 when its denominator is 0."""
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return prec, rec, f1
