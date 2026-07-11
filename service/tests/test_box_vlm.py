"""P3 adapter contract: fail-safe {} + degraded flag, and prompt provenance."""
import numpy as np


def test_post_vlm_fails_safe_and_flips_degraded():
    from service.infrastructure.box_vlm import make_post_vlm
    post, status = make_post_vlm("http://127.0.0.1:1/v1/chat/completions", "m", timeout=1)
    assert status == {"degraded": False}
    out = post("prompt", [np.zeros((8, 8, 3), np.uint8)])   # connection refused -> {}
    assert out == {} and status["degraded"] is True


def test_binary_prompt_lives_beside_validated_prompts():
    """The LIVE binary prompt must import from qa.perception (not an inline
    literal in the engine factory) and still carry the anti-false-positive
    stylization clause the benchmarked prompt family shares."""
    from inbetween_copilot.qa.perception import BINARY_PROMPT, PERCEPTION_PROMPT
    assert "has_motion_error" in BINARY_PROMPT and "verdict_prob" in BINARY_PROMPT
    assert "NOT an error" in BINARY_PROMPT            # stylization guard clause
    assert "has_motion_error" in PERCEPTION_PROMPT
