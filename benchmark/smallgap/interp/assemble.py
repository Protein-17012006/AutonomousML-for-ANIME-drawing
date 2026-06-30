"""Interleave the 8 stored source frames with their 8 RIFE mids into the
16-frame 'stored' clip order from decimate(WINDOW_LEN=17): positions 0..15 =
[s0, m0, s1, m1, ..., s7, m7]. mid[k] is RIFE(source[k], source[k+1])."""
from __future__ import annotations


def assemble_clip(source_frames, mid_frames):
    if len(source_frames) < 8 or len(mid_frames) < 8:
        raise ValueError(
            f"need >=8 source and >=8 mid frames, got "
            f"{len(source_frames)}/{len(mid_frames)}")
    out = []
    for i in range(8):
        out.append(source_frames[i])
        out.append(mid_frames[i])
    return out
