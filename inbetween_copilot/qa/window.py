"""Centered QA windows for production: feed the detector its calibrated 16-frame
window (key/mid interleaved) instead of a single pair's 3-frame triplet. See
vault 'Production VLM Window Widening' design."""
from __future__ import annotations


def centered_window(seq, center: int, W: int = 16):
    """W frames of `seq` with seq[center] at local offset W//2-1, clamp-padded
    (repeat first/last frame) so len(out) == W."""
    if W < 1:
        raise ValueError(f"W must be >= 1, got {W}")
    lo = W // 2 - 1
    n = len(seq)
    return [seq[min(max(i, 0), n - 1)] for i in range(center - lo, center - lo + W)]


def windows_for_run(filled, W: int = 16):
    """filled: ordered (pair_index, [a, mid, b]) for FILLED/GENERATED pairs only
    (needs_key pairs omitted -> their index gap breaks the segment). Returns
    {pair_index: centered 16-frame window}. Contiguous pairs share a key
    (b_j == a_{j+1}); each maximal contiguous run reconstructs to
    R = [a0, mid0, a1, mid1, ..., a_k, mid_k, b_k] and each pair's mid sits at
    local position 1 + 2*offset."""
    items = sorted(filled, key=lambda x: x[0])
    out = {}
    i = 0
    while i < len(items):
        j = i
        while j + 1 < len(items) and items[j + 1][0] == items[j][0] + 1:
            j += 1
        seg = items[i:j + 1]
        R = [seg[0][1][0]]                      # a0
        for _, fr in seg:
            R.append(fr[1])                     # mid
            R.append(fr[2])                     # b (== next a)
        for off, (pidx, _) in enumerate(seg):
            out[pidx] = centered_window(R, 1 + 2 * off, W)
        i = j + 1
    return out
