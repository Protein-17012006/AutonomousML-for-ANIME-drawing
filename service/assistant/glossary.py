"""Assistant feature: artist-facing product glossary — the UIA's second grounded tier.

Distilled from the vault's canonical `04 - Domain and Glossary/Glossary.md`
(+ the smoothness-control spec). Definitions only, NEVER session data: the
agent may explain terms from here but still answers *facts* only from the
per-session fact sheet. Edit the vault first, then mirror here.
"""

GLOSSARY = """\
gate: deterministic interpolability check run BEFORE any interpolation; per pair it decides FILL (safe to in-between) vs NEEDS_KEY (an artist must draw the key).
regime: a pair's motion class — hold (duplicate drawing, copied not morphed), small (content-close, RIFE-interpolated), snap (hard cut / on-2s timing, preserved not morphed).
RIFE: the frame-interpolation engine used for small-gap pairs.
key / keyframe: an artist-drawn frame; pairs are consecutive keys the system fills between.
pair: two consecutive keys plus the in-between frames generated for them.
CSQ (calibrated self-QA): the 3-state quality verdict on each filled pair — pass / abstain / flag; every internal failure biases to abstain, and an anti-Goodhart stillness guard keeps it honest.
pass: CSQ is confident the in-betweens are clean.
abstain: CSQ is NOT confident either way — the pair goes to human review; abstain is honesty, not an error.
flag: CSQ believes something is wrong; flagged pairs enter a bounded correction loop.
correction loop: LLM-directed retry on a flagged pair (region refill / engine escalation / ask for a key), bounded in rounds.
window: the 16-frame context the vision model looks at around a pair when judging it.
cadence: the shooting rate of the output — 24, 12, or 8 fps of unique drawings.
smoothness: display depth — x1 keeps cadence as-is, x2 doubles the in-between density (x4 does not exist).
needs_key: the gate refused to interpolate this pair; a drawn key is requested instead.
"""
