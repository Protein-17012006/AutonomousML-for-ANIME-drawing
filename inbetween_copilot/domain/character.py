"""Character fidelity data shared by QA and generation policies."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class CharacterSpec:
    name: str
    palette: list
    mandatory_details: list
    reference_frames: list

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(document: dict) -> "CharacterSpec":
        return CharacterSpec(
            name=document["name"],
            palette=list(document["palette"]),
            mandatory_details=list(document["mandatory_details"]),
            reference_frames=list(document["reference_frames"]),
        )


def condition_qa_prompt(base_prompt: str, spec: "CharacterSpec | None") -> str:
    if spec is None:
        return base_prompt
    clause = (
        f" This is {spec.name}; palette {', '.join(spec.palette)}; "
        f"must keep {', '.join(spec.mandatory_details)}. "
        "Also flag any off-model identity drift from this character sheet."
    )
    return base_prompt + clause


def reference_frames_for_gen(spec: "CharacterSpec | None") -> list:
    return list(spec.reference_frames) if spec is not None else []
