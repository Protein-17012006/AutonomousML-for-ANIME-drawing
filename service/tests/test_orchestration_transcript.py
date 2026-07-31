from service.orchestration.models import MAX_TRANSCRIPT_ENTRIES, TranscriptEntry
from service.orchestration.transcript import append_entries, entries_for, render_markdown


def _entry(seq, frm="orchestrator", to="triage", kind="ask", text="why?"):
    return TranscriptEntry(seq=seq, frm=frm, to=to, kind=kind, text=text,
                           data={}, ms=3, ts=1.0)


def test_entries_append_to_the_session_state():
    state = {}
    append_entries(state, [_entry(0), _entry(1)])
    assert len(entries_for(state)) == 2
    assert entries_for(state)[0]["frm"] == "orchestrator"


def test_a_second_turn_appends_rather_than_replaces():
    state = {}
    append_entries(state, [_entry(0)])
    append_entries(state, [_entry(1)])
    assert len(entries_for(state)) == 2


def test_the_transcript_is_capped_and_the_oldest_fall_off():
    state = {}
    append_entries(state, [_entry(i, text=f"m{i}") for i in range(MAX_TRANSCRIPT_ENTRIES + 10)])
    kept = entries_for(state)
    assert len(kept) == MAX_TRANSCRIPT_ENTRIES
    assert kept[-1]["text"] == f"m{MAX_TRANSCRIPT_ENTRIES + 9}"
    assert kept[0]["text"] == "m10"


def test_entries_survive_a_state_round_trip():
    import json
    state = {}
    append_entries(state, [_entry(0)])
    restored = json.loads(json.dumps(state))
    assert entries_for(restored)[0]["to"] == "triage"


def test_markdown_names_who_asked_whom():
    md = render_markdown([_entry(0).as_dict(),
                          _entry(1, frm="triage", to="orchestrator",
                                 kind="reply", text="pose_snap").as_dict()])
    assert "orchestrator" in md and "triage" in md
    assert "->" in md or "→" in md
    assert "pose_snap" in md


def test_markdown_of_an_empty_transcript_is_safe():
    assert isinstance(render_markdown([]), str)
