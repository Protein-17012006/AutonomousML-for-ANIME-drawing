"""Compatibility facade for character domain values.

New code imports these values from ``inbetween_copilot.domain.character``.
"""

from inbetween_copilot.domain.character import (
    CharacterSpec,
    condition_qa_prompt,
    reference_frames_for_gen,
)

__all__ = ["CharacterSpec", "condition_qa_prompt", "reference_frames_for_gen"]
