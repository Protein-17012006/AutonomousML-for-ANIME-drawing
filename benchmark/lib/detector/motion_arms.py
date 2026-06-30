"""Motion benchmark arm: clip -> one multi-frame VLM call -> binary verdict.

vision_common already accepts a LIST of image paths (multi-image), and the local
Qwen server (.scratch/serve_openai.py) decodes them into one message, so a whole
clip goes in a single call — no new plumbing. base vs LoRA is an OPERATIONAL
choice (which adapter the server was launched with); the arm code is identical.
"""
from __future__ import annotations

import os

from vision_common import vision_json

from benchmark.lib.manifest.motion_manifest import MotionManifest

_FRAME_EXTS = (".png", ".jpg", ".jpeg", ".webp")

_MOTION_PROMPT = """\
These are consecutive frames of one short animation clip, in order. Judge ONLY
the motion across them.

Some clips are clean: smooth, coherent anime motion. Some contain a motion error
from a generative interpolator — a limb that warps or melts, the character's
identity or colors drifting between frames, a motion arc that breaks or reverses
illogically, flicker/popping, or an impossible morph.

Intentional anime stylization (smears, speed lines, squash-and-stretch) is NOT an
error. Only flag a genuine breakdown in motion coherence.

Return JSON: {"has_motion_error": true or false, "explanation": "<one sentence>"}"""


# Anchor-conditioned (IVC) framing — borrowed from Index-AniSora's Image-Video
# Consistency dimension. The endpoint frames are trusted reference keyframes (real
# for interpolated clips; the first appearance for mined clips); the arm asks
# whether the in-between frames stay faithful to them. Same binary verdict contract
# as _MOTION_PROMPT, so motion_score / the frozen scorer are untouched. See design
# §3a. Targets identity_instability / style drift the blind montage prompt misses.
_ANCHOR_PROMPT = """\
These are consecutive frames of one short animation clip, in order. The FIRST and
LAST frames are trusted reference keyframes — treat them as the ground truth for
who the character is and how the art looks. The frames BETWEEN them were produced
by a generative interpolator and must stay faithful to those references.

Judge whether the in-between frames preserve the SAME single character as the
reference frames: the same face, hair colour, eye shape, silhouette, and line/art
style. Flag an error if the character's identity drifts, wobbles, melts, or morphs
away from the reference frames, or if the art style breaks — even when the overall
motion looks smooth.

Intentional anime stylization (smears, speed lines, squash-and-stretch, expression
changes) is NOT an error, as long as it is clearly the same character in the same
style. Only flag a genuine breakdown in identity or style consistency.

Return JSON: {"has_motion_error": true or false, "explanation": "<one sentence>"}"""


# Visual-integrity framing — targets the `artifact` axis the identity/motion
# prompts miss. suite_identity re-audit (2026-06-17): 21/31 identity-"clean" clips
# carry unintended rendering degradation (smear/melt/ghost/warp/wobble) the
# identity arm passes. This arm asks ONLY about rendering breakdown, decoupled
# from "is it the same person". Same binary verdict contract as the other arms.
_ARTIFACT_PROMPT = """\
These are consecutive frames of one short animation clip, in order. Judge ONLY
the visual INTEGRITY of how the character is RENDERED across the frames — not
whether it stays the same person, not the story.

Flag an error if the character shows UNINTENDED generative degradation across the
frames: features smearing or melting, edges liquefying, ghosting or doubling,
limbs blurring into paste, or the face / body proportions wobbling or warping
from one frame to the next.

Intentional anime stylization (smears, speed lines, squash-and-stretch), ordinary
camera moves, head turns and expression changes are NOT errors. A deliberate
stylistic effect (magic swirl, aura, particles, glow) is NOT an error by itself —
only flag it if the CHARACTER itself dissolves or loses coherent form. Only flag a
genuine rendering breakdown / distortion of the character.

Return JSON: {"has_motion_error": true or false, "explanation": "<one sentence>"}"""


def _as_bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "yes"):
            return True
        if s in ("false", "no"):
            return False
    return None


def _clip_frames(clip_dir: str) -> list[str]:
    names = sorted(n for n in os.listdir(clip_dir)
                   if n.lower().endswith(_FRAME_EXTS))
    return [os.path.join(clip_dir, n) for n in names]


def _subsample(paths: list[str], k: int) -> list[str]:
    """Evenly pick k frames (incl. first and last), matching the training
    sampler in build_motion_sft.sample_frames. Used when the served LoRA was
    trained on fewer frames than the suite stores (e.g. 8-of-16) so eval matches
    train. k<=0 or k>=len keeps all frames (default = whole clip, unchanged)."""
    L = len(paths)
    if k <= 0 or k >= L:
        return paths
    idx = sorted({round(i * (L - 1) / (k - 1)) for i in range(k)})
    return [paths[i] for i in idx]


def _eval_frames() -> int:
    try:
        return int(os.environ.get("MOTION_EVAL_FRAMES", "0") or "0")
    except ValueError:
        return 0


def _run_arm(suite_dir: str, manifest: MotionManifest,
             prompt: str) -> dict[str, dict]:
    """One VLM call per clip with the given prompt -> binary verdict dict. Shared
    by run_clip_arm (blind montage) and run_anchor_arm (reference-conditioned);
    only the prompt differs, so behaviour stays identical across arms."""
    verdicts: dict[str, dict] = {}
    k = _eval_frames()
    for clip in manifest.clips:
        clip_dir = os.path.join(suite_dir, "clips", clip["id"])
        paths = _clip_frames(clip_dir)
        if not paths:
            verdicts[clip["id"]] = {"has_motion_error": None,
                                    "explanation": "no frames found"}
            continue
        if k:
            paths = _subsample(paths, k)
        try:
            reply = vision_json(prompt, paths, tier="check", max_tokens=800)
        except Exception as e:  # noqa: BLE001 — one bad clip != dead arm
            verdicts[clip["id"]] = {"has_motion_error": None,
                                    "explanation": f"arm call failed: {e}"}
            continue
        verdicts[clip["id"]] = {
            "has_motion_error": _as_bool(reply.get("has_motion_error")),
            "explanation": str(reply.get("explanation", "")),
        }
    return verdicts


def run_clip_arm(suite_dir: str, manifest: MotionManifest) -> dict[str, dict]:
    """Blind arm: judge the 16-frame montage with no anchor hint (_MOTION_PROMPT)."""
    return _run_arm(suite_dir, manifest, _MOTION_PROMPT)


def run_anchor_arm(suite_dir: str, manifest: MotionManifest) -> dict[str, dict]:
    """Anchor-conditioned arm (IVC, design §3a): first/last frames are the trusted
    reference; flag identity/style drift away from them (_ANCHOR_PROMPT)."""
    return _run_arm(suite_dir, manifest, _ANCHOR_PROMPT)


def run_artifact_arm(suite_dir: str, manifest: MotionManifest) -> dict[str, dict]:
    """Visual-integrity arm: flag unintended rendering degradation (smear/melt/
    ghost/warp/wobble) regardless of identity (_ARTIFACT_PROMPT). Targets the
    artifact axis the identity/motion prompts miss (suite_identity re-audit)."""
    return _run_arm(suite_dir, manifest, _ARTIFACT_PROMPT)


# Environment/FX framing (Phase C) — judge the SCENE + effects, not the character.
# Blind full-frame arm: env/FX coherence across the clip. Same "defect present" contract.
_ENV_PROMPT = """\
These are consecutive frames of one short animation clip, in order. Judge ONLY the
ENVIRONMENT and visual EFFECTS — the background, props, and any FX (fire, smoke,
magic, glow, impact, dust) — NOT the character's identity, NOT the story.

Flag an error if the scene fails to stay coherent across the frames: the background
melts / warps / changes layout, a prop pops in or out or jumps, perspective breaks,
the lighting or colour jumps with no in-scene cause, an effect detaches from where it
should come from, or an effect flickers / teleports / vanishes-and-reappears instead
of evolving smoothly.

Deliberate anime FX styling (an impact frame, a smear, debris, an intended glow or
aura, speed lines) is NOT an error. A correctly evolving effect (a flame steadily
growing, smoke drifting) is NOT an error. Only flag a genuine breakdown in the scene's
or effect's coherence.

Return JSON: {"has_motion_error": true or false, "explanation": "<one sentence>"}"""


# Keyframe-anchor (IVC, design §2.1) extended from character -> ENVIRONMENT. The
# endpoints are the trusted environment "spec"; the in-between must keep that scene and
# evolve FX monotonically between them.
_ENV_ANCHOR_PROMPT = """\
These are consecutive frames of one short animation clip, in order. The FIRST and LAST
frames are trusted reference keyframes — treat them as the ground truth for the
ENVIRONMENT: the background, the layout, the lighting, and the state of any effects
(fire, smoke, magic, glow). The frames BETWEEN them were produced by a generative
interpolator and must stay faithful to that environment and evolve plausibly between
the two references.

Flag an error if the in-between frames break the environment the keyframes establish:
the background melts or changes, a prop appears/disappears, the lighting or perspective
shifts away from the references, an effect is detached from its source, or — for an
effect that grows or moves between the two keyframes — it does NOT evolve monotonically
(it flickers, teleports, vanishes, or reverses) instead of smoothly interpolating
between its first-frame and last-frame state.

Deliberate anime FX styling (impact frames, smears, debris, intended glow/aura) is NOT
an error, as long as it is consistent with the references. Only flag a genuine
breakdown in environment or effect coherence.

Return JSON: {"has_motion_error": true or false, "explanation": "<one sentence>"}"""


def run_env_clip_arm(suite_dir: str, manifest: MotionManifest) -> dict[str, dict]:
    """Blind env/FX arm: judge scene + effect coherence with no anchor hint (_ENV_PROMPT)."""
    return _run_arm(suite_dir, manifest, _ENV_PROMPT)


def run_env_anchor_arm(suite_dir: str, manifest: MotionManifest) -> dict[str, dict]:
    """Keyframe-anchor env arm (design §2.1): first/last frames are the trusted
    environment reference; flag scene/FX drift away from them (_ENV_ANCHOR_PROMPT)."""
    return _run_arm(suite_dir, manifest, _ENV_ANCHOR_PROMPT)
