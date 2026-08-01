from service.orchestration.binding import is_reference, resolve_args


def _agent(payload):
    return {"kind": "agent", "payload": payload}


def test_a_reference_resolves_from_an_earlier_agent_step():
    sources = {1: _agent({"first_index": 2})}
    resolved, bound, error = resolve_args({"index": "$1.first_index"}, sources)
    assert error == ""
    assert resolved == {"index": 2}
    assert bound == {"index": "$1.first_index"}


def test_a_literal_passes_through_untouched():
    resolved, bound, error = resolve_args({"index": 0, "note": "hello"}, {})
    assert error == ""
    assert resolved == {"index": 0, "note": "hello"}
    assert bound == {}


def test_a_forward_reference_is_refused():
    resolved, _bound, error = resolve_args({"index": "$3.first_index"}, {})
    assert resolved is None
    assert "has not run" in error


def test_a_reference_to_a_TOOL_step_is_refused():
    sources = {1: {"kind": "tool", "payload": {"args": {"index": 2}}}}
    resolved, _bound, error = resolve_args({"index": "$1.args"}, sources)
    assert resolved is None
    assert "tool" in error


def test_a_missing_field_is_refused_and_names_what_was_reported():
    sources = {1: _agent({"cls": "pose_snap", "evidence": {}})}
    resolved, _bound, error = resolve_args({"index": "$1.first_index"}, sources)
    assert resolved is None
    assert "cls" in error and "evidence" in error


def test_a_non_scalar_value_is_refused():
    sources = {1: _agent({"work_order": [{"index": 2}]})}
    resolved, _bound, error = resolve_args({"index": "$1.work_order"}, sources)
    assert resolved is None
    assert "list" in error


def test_a_none_value_is_refused():
    sources = {1: _agent({"first_index": None})}
    resolved, _bound, error = resolve_args({"index": "$1.first_index"}, sources)
    assert resolved is None


def test_a_REFUSED_source_is_still_readable():
    """models.py: payload survives a refusal by design — that is how Triage
    returns a class while refusing to supply a key count."""
    sources = {1: _agent({"cls": "pose_snap", "out_of_population": True})}
    resolved, _bound, error = resolve_args({"kind": "$1.cls"}, sources)
    assert error == ""
    assert resolved == {"kind": "pose_snap"}


def test_only_the_exact_shape_counts_as_a_reference():
    for value in ["$0.field", "$1.Field", "$1.", "$.field", "1.field",
                  "cost me $5.50 to print", "$1.field extra", ""]:
        assert not is_reference(value), value
    assert is_reference("$1.first_index")
    assert is_reference("$12.cls")


def test_a_non_dict_args_is_tolerated():
    resolved, bound, error = resolve_args(None, {})
    assert resolved == {} and bound == {} and error == ""


def test_a_step_id_with_too_many_digits_does_not_raise_valueerror():
    """Regression: very long step IDs (>6 digits) used to crash int() conversion.
    Now the regex bounds them, so long IDs simply don't match and pass through."""
    very_long_id = "$" + "9" * 5000 + ".field"
    resolved, bound, error = resolve_args({"index": very_long_id}, {})
    assert resolved is not None  # Should return successfully, not raise
    assert resolved == {"index": very_long_id}  # Passes through as literal
    assert error == ""


def test_a_non_dict_sources_entry_does_not_raise_attributeerror():
    """Regression: malformed sources entries (non-dict) used to crash on .get().
    Now we check isinstance(source, dict) and return an error."""
    sources = {1: "not-a-dict"}
    resolved, _bound, error = resolve_args({"index": "$1.field"}, sources)
    assert resolved is None  # Should return error, not raise
    assert "malformed" in error
