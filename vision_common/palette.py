"""Deterministic palette extraction — shared vision utility.

Used by the EDA image tools and the Orchestrator's spec calibration
(Plan 2; moved from EDA tools/image/_palette).

Two extraction strategies:
  - extract_palette: median-cut quantization (legacy, kept for non-cel use).
  - dominant_colors: exact flat-color counting via NEAREST downscale (default
    for cel/anime footage where characters occupy ~1% of the frame and
    MEDIANCUT fails to allocate them a cluster).

Distances are plain Euclidean RGB. Thresholds live in config and get
calibrated by the Plan-2 benchmark; the functions here are pure and
threshold-free.
"""
from __future__ import annotations

import math

from PIL import Image

_ANALYSIS_EDGE = 256  # quantize on a small copy: stable + fast


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def extract_palette(image_path: str, n_colors: int = 8) -> list[dict]:
    """Return dominant color clusters: [{"rgb": (r,g,b), "hex": "#..",
    "share": 0.0-1.0}], sorted by share descending.

    Alpha is composited onto white (same as vision_common._encode_image) so
    the deterministic palette and the VLM see identical pixels.
    """
    img = Image.open(image_path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if max(img.size) > _ANALYSIS_EDGE:
        scale = _ANALYSIS_EDGE / max(img.size)
        img = img.resize((max(1, int(img.width * scale)),
                          max(1, int(img.height * scale))),
                         resample=Image.Resampling.LANCZOS)
    q = img.quantize(colors=n_colors, method=Image.Quantize.MEDIANCUT)
    counts = q.getcolors(maxcolors=n_colors * 2)
    # After quantize(colors=n) there are at most n distinct indices, so
    # getcolors can never overflow maxcolors — fail loudly if Pillow ever
    # changes that, instead of silently returning an empty palette.
    if counts is None:  # cannot happen after quantize(colors=n); fail loudly
        raise RuntimeError("extract_palette: getcolors overflowed after quantize")
    palette = q.getpalette() or []
    total = sum(c for c, _ in counts) or 1
    clusters = []
    for count, idx in counts:
        rgb = tuple(palette[idx * 3: idx * 3 + 3])
        if len(rgb) != 3:
            continue  # pathological palette — skip rather than crash
        clusters.append({"rgb": rgb, "hex": rgb_to_hex(rgb),
                         "share": count / total})
    clusters.sort(key=lambda c: c["share"], reverse=True)
    return clusters


def dominant_colors(image_path: str, *, max_colors: int = 64,
                    min_share: float = 0.001) -> list[dict]:
    """Exact flat-color masses: [{"rgb", "hex", "share"}] sorted by share.

    Cel/anime footage uses exact flat fills, so counting beats quantization:
    MEDIANCUT merges a ~1% character region into background clusters, but the
    region's exact color survives a NEAREST downscale (no invented blends).
    """
    img = Image.open(image_path)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])
        img = bg
    else:
        img = img.convert("RGB")
    if max(img.size) > _ANALYSIS_EDGE:
        scale = _ANALYSIS_EDGE / max(img.size)
        img = img.resize((max(1, int(img.width * scale)),
                          max(1, int(img.height * scale))),
                         resample=Image.Resampling.NEAREST)
    total = img.width * img.height
    counts = img.getcolors(maxcolors=total)
    if counts is None:  # cannot happen with maxcolors=total; fail loudly
        raise RuntimeError("dominant_colors: getcolors overflowed")
    out = [{"rgb": tuple(rgb), "hex": rgb_to_hex(tuple(rgb)),
            "share": n / total}
           for n, rgb in counts if n / total >= min_share]
    out.sort(key=lambda c: c["share"], reverse=True)
    return out[:max_colors]


def nearest_cluster_distance(canonical_hex: str, clusters: list[dict]) -> float:
    """Distance from a spec canonical color to the nearest extracted cluster.
    Large distance == that color is missing/shifted in the frame."""
    target = hex_to_rgb(canonical_hex)
    if not clusters:
        return float("inf")
    return min(color_distance(target, tuple(c["rgb"])) for c in clusters)
