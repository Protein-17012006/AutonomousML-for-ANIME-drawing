"""Flag-feedback: state persistence, domain snapshot, stores (box-free)."""
import io

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from service.app import app
from service.state import _state


def _png(v: int) -> io.BytesIO:
    b = io.BytesIO()
    Image.fromarray(np.full((8, 8, 3), v, np.uint8)).save(b, "PNG")
    b.seek(0)
    return b


def test_stub_session_state_carries_explanations_and_qa_degraded():
    c = TestClient(app)
    before = set(_state)
    r = c.post("/session",
               files=[("keys", (f"{i}.png", _png(i * 60), "image/png")) for i in range(3)],
               data={"engines": "stub"})
    assert r.status_code == 200 and "event: result" in r.text
    new_sids = set(_state) - before
    assert new_sids, "session did not register in _state"
    sid = new_sids.pop()
    assert isinstance(_state[sid]["explanations"], dict)
    assert _state[sid]["qa_degraded"] is False   # stub engines: no VLM, not degraded


# --- Task 3: FeedbackRecord + build_feedback tests ---

from inbetween_copilot.pipeline.copilot import CopilotResult, PairResult
from inbetween_copilot.qa.gate import FrameQA
from service.feedback import build_feedback
from service.schemas import SessionCfg


def _feedback_state():
    pairs = [
        PairResult(0, "filled", "rife", ["a", "m", "b"],
                   FrameQA("pass", "csq:pass", p_error=0.04, u=0.10), 0),
        PairResult(1, "filled", "rife", ["a", "m", "b"],
                   FrameQA("flag", "csq:flag", p_error=0.91, u=0.20), 0),
        PairResult(2, "needs_key", None, None, None, 1),
    ]
    res = CopilotResult(pairs=pairs, keys_requested_total=1, flagged=[1],
                        n_autopass=1, n_corrected=0)
    return {
        "result": res,
        "cfg": SessionCfg(engines="stub", cadence_fps=12, smoothness=2, show="Wistoria"),
        # real producer shape (service/explain.py's explain_pairs): keyed err_type/
        # region/explanation, NOT error_type — regression-guards the seam build_feedback
        # reads from.
        "explanations": {1: {"err_type": "ghost", "region": "mc", "explanation": "double edge"}},
        "qa_degraded": False,
        "rev": 0,
    }


def test_snapshot_carries_both_human_and_machine_sides():
    rec = build_feedback(_feedback_state(), sid=7, pair_index=1, vote="down", voter="anon")
    assert rec.sid == 7 and rec.pair_index == 1 and rec.vote == "down" and rec.voter == "anon"
    assert rec.qa_status == "flag" and rec.p_error == 0.91 and rec.u == 0.20
    assert rec.error_type == "ghost" and rec.region == "mc"
    assert rec.show == "Wistoria" and rec.engines == "stub"
    assert rec.cadence_fps == 12 and rec.smoothness == 2 and rec.qa_degraded is False
    assert rec.rev == 0
    assert rec.ts > 0


def test_pass_pair_without_explanation_snapshots_none_fields():
    rec = build_feedback(_feedback_state(), sid=7, pair_index=0, vote="up", voter="sub-1")
    assert rec.qa_status == "pass" and rec.error_type is None and rec.region is None


def test_needs_key_pair_is_not_votable():
    with pytest.raises(ValueError, match="needs_key"):
        build_feedback(_feedback_state(), sid=7, pair_index=2, vote="down", voter="anon")


def test_bad_pair_index_and_bad_vote_raise():
    with pytest.raises(ValueError):
        build_feedback(_feedback_state(), sid=7, pair_index=99, vote="up", voter="anon")
    with pytest.raises(ValueError):
        build_feedback(_feedback_state(), sid=7, pair_index=0, vote="meh", voter="anon")


# --- Task 4: feedback stores ---

from service.feedback import FeedbackRecord
from service.feedback_store import DynamoFeedbackStore, InMemoryFeedbackStore


def _rec(sid=1, pair=0, voter="anon", vote="up"):
    return FeedbackRecord(sid=sid, pair_index=pair, voter=voter, vote=vote,
                          ts=1, qa_status="pass", p_error=0.04, u=0.10)


class _FakeTable:
    def __init__(self):
        self.rows = {}

    def query(self, **kwargs):
        return {"Items": list(self.rows.values())}

    def put_item(self, Item):
        self.rows[(Item["sessionPk"], Item["feedbackSk"])] = dict(Item)


@pytest.mark.parametrize("store", [InMemoryFeedbackStore(),
                                   DynamoFeedbackStore(table=_FakeTable())])
def test_store_contract_upsert_is_last_write_wins(store):
    store.upsert(_rec(vote="up"))
    store.upsert(_rec(vote="down"))                       # same (sid, pair, voter)
    store.upsert(_rec(pair=1, voter="sub-9", vote="up"))  # different key
    rows = store.list_session(1)
    assert len(rows) == 2
    mine = [r for r in rows if r.pair_index == 0 and r.voter == "anon"]
    assert mine[0].vote == "down" and mine[0].p_error == 0.04


def test_dynamo_store_key_shape():
    table = _FakeTable()
    DynamoFeedbackStore(table=table).upsert(_rec(sid=7, pair=3, voter="sub-1"))
    assert ("SESSION#7", "PAIR#3#VOTER#sub-1") in table.rows


def test_dynamo_from_row_parses_real_all_decimal_shape():
    """Real DynamoDB returns every numeric attribute as decimal.Decimal, not the
    Python int/float boto3's docs sometimes suggest — pin that _from_row copes."""
    from decimal import Decimal

    row = {"sid": Decimal("7"), "pair_index": Decimal("3"), "voter": "anon",
           "vote": "up", "ts": Decimal("1"), "p_error": Decimal("0.04"),
           "u": Decimal("0.1"), "qa_degraded": False}
    rec = DynamoFeedbackStore._from_row(row)
    assert rec.sid == 7 and rec.p_error == 0.04
    assert isinstance(rec.p_error, float)


def test_feedback_store_for_prefers_app_state_injection():
    from service.feedback_store import feedback_store_for

    class App:
        class state:
            feedback_store = InMemoryFeedbackStore()

    assert feedback_store_for(App) is App.state.feedback_store
