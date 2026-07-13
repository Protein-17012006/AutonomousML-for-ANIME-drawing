"""qa_degraded must reach the client when the served VLM was unreachable."""
from inbetween_copilot.pipeline.copilot import CopilotResult
from service.infrastructure.engine_bundle import _SERVICE_ONLY as _SERVICE_ONLY_KEYS
from service.sessions.schemas import ResultEvent


def _result():
    return CopilotResult(pairs=[], keys_requested_total=0, flagged=[], n_autopass=0)


def test_result_event_carries_qa_degraded():
    ev = ResultEvent.from_result(_result(), {}, qa_degraded=True)
    assert ev.qa_degraded is True


def test_qa_degraded_defaults_false():
    assert ResultEvent.from_result(_result(), {}).qa_degraded is False


def test_vlm_status_is_stripped_before_run_copilot():
    # run_copilot doesn't accept the service-layer key; runner must strip it
    assert "vlm_status" in _SERVICE_ONLY_KEYS
