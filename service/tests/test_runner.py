from service.sessions.runner import run_session
from service.infrastructure.engines import stub_engines
from service.sessions.schemas import SessionCfg


def test_run_session_streams_each_pair():
    eng = stub_engines(SessionCfg())
    seen = []
    r = run_session([0, 1, 2, 50], eng, on_pair=lambda p: seen.append(p.index))
    assert seen == [0, 1, 2] and r.keys_requested_total >= 1
