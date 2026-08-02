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


def test_the_prompt_names_each_agent_OUTPUT_field():
    """A planner cannot write "$1.first_index" unless it is told the field exists."""
    from service.orchestration.registry import describe_for_prompt
    text = describe_for_prompt()
    assert "first_index" in text
    assert "err_type" in text
    assert "OUTPUTS" in text


def test_the_prompt_gives_cut_survey_EMPTY_args_not_an_index():
    from service.orchestration.registry import describe_for_prompt
    line = [ln for ln in describe_for_prompt().splitlines()
            if ln.strip().startswith("cut_survey")][0]
    assert "index" not in line


def test_every_agent_spec_is_a_four_tuple():
    from service.orchestration.registry import _AGENT_SPECS
    for name, spec in _AGENT_SPECS.items():
        assert len(spec) == 4, name
        assert all(isinstance(part, str) and part for part in spec), name


def test_resolve_still_returns_the_label_for_every_agent():
    from service.orchestration.registry import agent_names, resolve
    for name in agent_names():
        assert resolve(name).label
        assert resolve(name).kind == "agent"


def test_cut_survey_is_addressable():
    from service.orchestration.registry import agent_names
    assert "cut_survey" in agent_names()


def test_the_prompt_names_every_cut_survey_payload_key():
    """cut_survey_agent (service/orchestration/agents.py) returns nine payload
    keys unconditionally plus `first_index` only when there is actionable work.
    A field named here that the agent never returns produces a step the server
    rejects at runtime; a field the agent returns but this text omits is one the
    planner can never learn to reference."""
    text = registry.describe_for_prompt()
    # cut_survey's OUTPUTS line is the one right after its args line.
    lines = text.splitlines()
    idx = [i for i, ln in enumerate(lines)
           if ln.strip().startswith("cut_survey")][0]
    outputs_line = lines[idx + 1]
    for field in ("work_order", "buckets", "keys_outstanding", "n_pairs",
                  "n_evaluated", "not_evaluated", "not_evaluated_reasons",
                  "unreadable", "withheld", "first_index"):
        assert field in outputs_line, field


def test_the_prompt_names_every_triage_payload_key():
    """triage_agent returns cls/confidence/evidence always, plus either
    keys_suggested+brief (gate-refused pair) or out_of_population+withheld
    (gate-accepted pair) — never all seven at once, but the text must still
    name all seven so a planner can reference whichever branch fired."""
    text = registry.describe_for_prompt()
    lines = text.splitlines()
    idx = [i for i, ln in enumerate(lines)
           if ln.strip().startswith("triage")][0]
    outputs_line = lines[idx + 1]
    for field in ("cls", "confidence", "evidence", "keys_suggested", "brief",
                  "out_of_population", "withheld"):
        assert field in outputs_line, field
