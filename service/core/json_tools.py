"""Small, dependency-free helpers for forgiving model JSON envelopes."""
from __future__ import annotations

import json


def first_json_object(text: str) -> dict | None:
    """Return the first complete JSON object embedded in *text*.

    Model replies often wrap JSON in prose or Markdown. A greedy ``{.*}`` regex
    merges adjacent objects and breaks on braces inside JSON strings; the stdlib
    decoder understands both cases and lets callers retain their fail-soft API.
    """
    if not isinstance(text, str):
        return None
    decoder = json.JSONDecoder()
    for offset, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[offset:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None
