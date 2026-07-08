"""Display-depth expansion for the reconstructed video — NOT the QA path.

The co-pilot QA's the canonical x2 triplet [a, mid, b]. Smoothness ("display depth") re-expands
each already-QA'd pair at video-assembly time only:
  Off (1) -> keys only [a, b]     x2 (2) -> unchanged [a, mid, b]
  x4 (4)  -> rife: [a, mid(a,mid), mid, mid(mid,b), b]; hold/snap: [a, a, a, a, b] (never morph)
"""
from typing import Callable, Optional, Sequence

_COPY_ROUTES = ("hold", "snap_preserve")


def expand_pair(frames: Sequence, route: str, factor: int,
                mid_engine: Optional[Callable] = None) -> list:
    """Reshape one already-QA'd pair's frames for the output video: factor 1=Off (keys only),
    2=Standard (unchanged), 4=Extra (rife inserts 2 mids; hold/snap repeat the held frame)."""
    a, b = frames[0], frames[-1]
    if factor == 2:
        return list(frames)
    if factor == 1:
        return [a, b]
    if factor == 4:
        if route in _COPY_ROUTES:
            return [a, a, a, a, b]
        mid = frames[1]
        if mid_engine is None:
            raise ValueError("factor==4 on a rife pair needs a mid_engine")
        return [a, mid_engine(a, mid)[1], mid, mid_engine(mid, b)[1], b]
    raise ValueError(f"unsupported smoothness factor {factor!r} (expected 1, 2, or 4)")


def x4_displays_mid(route: str) -> bool:
    """True if expand_pair(..., factor=4) keeps the interpolated mid frame on
    screen for this route. Copy routes (hold/snap_preserve) drop it -> False;
    rife keeps it -> True. The x4 CSQ probe uses this to label windows by what
    is actually displayed, not by the native error_frames (vault 'Honest x4' §4)."""
    return route not in _COPY_ROUTES
