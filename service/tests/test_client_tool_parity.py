"""The server tool registry and the client executor must agree.

`image_edit` was registered on the server, rendered a Confirm button, and did
NOTHING when pressed: CopilotApp's switch had no case for it and no default, so
the press fell through silently. 14 server test files were green throughout,
because every one of them stopped at the validator or the route.

This matches a RENDERING (`case "x":`) rather than an AST, which the Spec 1
rules warn against — accepted deliberately: frontend/package.json has no test
runner (no vitest, jest, playwright or testing-library), so Python reading the
file is the only place both facts exist at once. A reformat can fail this test
spuriously; that failure is loud and cheap, and the one it prevents is silent
and shipped.
"""
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / "frontend" / "src" / "components" / "copilot" / "CopilotApp.tsx"


@pytest.fixture(scope="module")
def executor_source() -> str:
    if not _APP.exists():
        pytest.skip(f"canonical frontend not present at {_APP}")
    source = _APP.read_text(encoding="utf-8")
    start = source.index("const acceptAction")
    return source[start:source.index("const handleSignOut", start)]


def test_the_executor_switch_has_a_default_branch(executor_source: str):
    """Without this, a tool with no case fails MUTE — the image_edit defect."""
    assert re.search(r"^\s*default:", executor_source, re.MULTILINE), (
        "acceptAction's switch has no `default:`; a server tool with no client "
        "case will silently do nothing when the artist confirms it"
    )


def test_every_server_tool_has_a_client_case(executor_source: str):
    from service.assistant.agent import TOOLS

    missing = [name for name in TOOLS
               if not re.search(rf'case\s+"{re.escape(name)}"\s*:', executor_source)]
    assert not missing, (
        f"registered on the server with no client case: {missing}. The artist gets "
        f"a Confirm button that reaches the default branch and reports failure."
    )


def test_every_server_tool_survives_the_client_parser():
    """`TOOL_NAMES` is the real gate, and it fails EARLIER and more quietly.

    `asAction` (api.ts) returns null for a tool absent from this array, and
    `rejected_tool` is only set when the SERVER refuses — so a missing name
    yields no card, no button and no refusal line at all, while the agent's
    reply still describes the action. A `case` in the executor is unreachable
    dead code without this list.
    """
    from service.assistant.agent import TOOLS

    api = _REPO / "frontend" / "src" / "components" / "copilot" / "api.ts"
    if not api.exists():
        pytest.skip(f"canonical frontend not present at {api}")
    source = api.read_text(encoding="utf-8")
    # Anchor on the "= [" that opens the array, not on the declaration: the type
    # annotation `AgentToolName[]` contains a `]` and truncated the slice to
    # nothing, which made this test fail listing every tool as missing.
    decl = source.index("const TOOL_NAMES")
    open_bracket = source.index("[", source.index("=", decl))
    block = source[open_bracket:source.index("]", open_bracket)]

    missing = [name for name in TOOLS if f'"{name}"' not in block]
    assert not missing, (
        f"absent from TOOL_NAMES, so the client drops the proposal before it can "
        f"be rendered: {missing}"
    )
