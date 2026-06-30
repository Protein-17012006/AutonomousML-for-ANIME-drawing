"""U3 -- the confidence aggregator. Folds the channel scores into one error-score
`s` and one uncertainty `u`. The weight of a channel is its (re-fit) base AUC
discounted by how often it flips under perturbation, so a destabilized channel
(the signature of a gamed frame) drops out of the vote. `u` blends inter-channel
disagreement with mean instability -- the single number that is both the
confidence and the anti-gaming signal."""
from __future__ import annotations


def aggregate(scores, flip_rates, *, base_auc, lam: float = 0.5):
    names = [n for n in scores if n in base_auc]
    if not names:
        return 0.5, 1.0
    w = {n: base_auc[n] * (1.0 - flip_rates.get(n, 1.0)) for n in names}
    wsum = sum(w.values())
    vals = [scores[n].score for n in names]
    mean_flip = sum(flip_rates.get(n, 1.0) for n in names) / len(names)
    if wsum <= 0.0:
        s = sum(vals) / len(vals)
        u = 1.0
        return float(s), float(min(1.0, max(0.0, u)))
    s = sum(w[n] * scores[n].score for n in names) / wsum
    var = sum(w[n] * (scores[n].score - s) ** 2 for n in names) / wsum
    disagree = var ** 0.5
    u = lam * disagree + (1.0 - lam) * mean_flip
    return float(s), float(min(1.0, max(0.0, u)))
