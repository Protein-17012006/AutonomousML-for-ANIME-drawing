from service.assistant.agent import TOOLS
from service.orchestration import registry


def test_every_assistant_tool_is_addressable_as_a_tool():
    for name in TOOLS:
        target = registry.resolve(name)
        assert target is not None, name
        assert target.kind == "tool"


def test_needs_confirm_is_read_from_the_assistant_table_not_copied():
    assert registry.resolve("rerun_session").needs_confirm is True
    assert registry.resolve("open_board").needs_confirm is False
    # the tables must agree by construction
    for name, spec in TOOLS.items():
        assert registry.resolve(name).needs_confirm is spec["needs_confirm"]


def test_the_named_agents_are_addressable():
    for name in ("triage", "perception", "qa_csq"):
        target = registry.resolve(name)
        assert target is not None, name
        assert target.kind == "agent"


def test_an_agent_never_needs_confirmation():
    for name in registry.agent_names():
        assert registry.resolve(name).needs_confirm is False


def test_an_unregistered_target_does_not_resolve():
    assert registry.resolve("rm_rf") is None
    assert registry.resolve("") is None
    assert registry.resolve(None) is None


def test_the_prompt_description_names_every_target():
    text = registry.describe_for_prompt()
    for name in registry.agent_names() + registry.tool_names():
        assert name in text


def test_every_tool_gives_the_planner_an_ARGUMENT_SHAPE():
    """Live run 2026-08-01: without the shapes the planner invented
    remember_memory{"text":...}, open_board{} and rerun_session{} — 4 rejected
    steps in 12 goals. A new tool must not be addable without a hint."""
    text = registry.describe_for_prompt()
    for name in TOOLS:
        assert name in registry._TOOL_ARGS, f"{name} has no argument hint"
        assert registry._TOOL_ARGS[name] in text, name


def test_the_planner_is_told_the_allowed_memory_keys():
    from service.memory.models import ALLOWED_KEYS
    text = registry.describe_for_prompt()
    for keys in ALLOWED_KEYS.values():
        for key in keys:
            assert key in text, key


def test_the_planner_is_told_nothing_executes():
    text = registry.describe_for_prompt().lower()
    assert "until the artist accepts" in text or "not run" in text
