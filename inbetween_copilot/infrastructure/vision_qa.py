"""Adapter from in-memory frames to the ``vision_common`` JSON client."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass


@dataclass(frozen=True)
class VisionJSONQA:
    prompt: str
    tier: str = "check"
    max_tokens: int = 800

    def __call__(self, frames) -> bool:
        from PIL import Image
        from vision_common import vision_json

        with tempfile.TemporaryDirectory(prefix="copilot_qa_") as tmpdir:
            paths = []
            for index, frame in enumerate(frames):
                path = os.path.join(tmpdir, f"{index:04d}.png")
                Image.fromarray(frame).save(path)
                paths.append(path)
            reply = vision_json(
                self.prompt, paths, tier=self.tier, max_tokens=self.max_tokens,
            )
        return bool(reply.get("has_motion_error"))
