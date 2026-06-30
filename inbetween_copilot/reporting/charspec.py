"""Per-show fidelity, training-free tier (H3 tier-1).

A CharacterSpec (the show's sheet, reusing the ADR-0010 spec idea) conditions
BOTH the self-QA prompt (catch character-specific off-model drift) and the
AniSora generator (reference frames keep larger-gap in-betweens on-model).
No training — pure data + prompt conditioning.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class CharacterSpec:
    name: str
    palette: list           # hex strings
    mandatory_details: list
    reference_frames: list  # image paths

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "CharacterSpec":
        return CharacterSpec(name=d["name"], palette=list(d["palette"]),
                             mandatory_details=list(d["mandatory_details"]),
                             reference_frames=list(d["reference_frames"]))


def condition_qa_prompt(base_prompt: str, spec: "CharacterSpec | None") -> str:
    if spec is None:
        return base_prompt
    clause = (f" This is {spec.name}; palette {', '.join(spec.palette)}; "
              f"must keep {', '.join(spec.mandatory_details)}. "
              f"Also flag any off-model identity drift from this character sheet.")
    return base_prompt + clause


def reference_frames_for_gen(spec: "CharacterSpec | None") -> list:
    return list(spec.reference_frames) if spec is not None else []
