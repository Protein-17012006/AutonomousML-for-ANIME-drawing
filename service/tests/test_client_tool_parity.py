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
