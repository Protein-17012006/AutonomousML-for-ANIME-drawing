"""Tests for service.infrastructure.engines — box-free assertions."""
import pytest
from service.infrastructure.engines import (
    _get_box_runtime,
    box_engines,
    stub_engines,
)
from service.sessions.schemas import SessionCfg
from inbetween_copilot.pipeline.copilot import run_copilot


def test_stub_engines_drive_run_copilot_deterministically():
    eng = stub_engines(SessionCfg())
    r = run_copilot([0, 1, 2, 50], **eng.copilot_kwargs())
    assert r.n_autopass == 2
    assert any(p.action == "needs_key" for p in r.pairs)


def test_import_engines_box_free():
    """import service.infrastructure.engines must succeed on a non-box machine."""
    import service.infrastructure.engines  # noqa — just verifying importability


def test_stub_engines_still_works():
    """stub_engines must still return a callable bundle (regression guard)."""
    eng = stub_engines(SessionCfg())
    assert callable(eng.gap_fn)
    assert callable(eng.interp_fn)


def test_box_engines_fails_loudly_off_box():
    """On this non-box machine, box_engines must raise a clear error (not silently succeed).

    box_engines setdefaults VISION_*_CHECK env vars BEFORE its box-only imports raise —
    without cleanup that pollutes the process env and breaks tests/test_vision_client.py
    default-model assertions later in the same bare-pytest run (seen 2026-07-02 when
    service/ joined testpaths). Snapshot + restore the touched keys."""
    import os
    keys = ("VISION_BASE_URL_CHECK", "VISION_MODEL_CHECK", "VISION_MAX_PIXELS_CHECK")
    before = {k: os.environ.get(k) for k in keys}
    try:
        with pytest.raises((ImportError, ModuleNotFoundError, RuntimeError, OSError)):
            box_engines(SessionCfg())
    finally:
        for k, v in before.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_stub_engines_has_vlm_struct_fn():
    """stub_engines must expose a callable vlm_struct_fn returning the clean stub dict."""
    eng = stub_engines(SessionCfg())
    assert callable(eng.vlm_struct_fn)
    result = eng.vlm_struct_fn([])
    assert result["has_motion_error"] is False
    assert result["error_type"] == "none"
    assert result["region"] == "none"
    assert "stub" in result["explanation"]


def test_gimm_runtime_dispatches_to_gimm_builder_once(monkeypatch, tmp_path):
    import service.infrastructure.engines as engines_module
    import service.infrastructure.gimm as gimm_module
    from service.core.config import BoxSettings, GimmSettings

    box_settings = BoxSettings(
        vlm_base_url="http://127.0.0.1:8001/v1",
        vlm_model="test",
        vlm_max_pixels=320,
        rife_root=tmp_path,
        rife_model_dir=tmp_path,
        rife_device="cpu",
        csq_artifact_path=tmp_path / "csq.json",
    )
    gimm_settings = GimmSettings(
        root=tmp_path / "GIMM-VFI",
        config_path=tmp_path / "gimm.yaml",
        checkpoint_path=tmp_path / "gimm.pt",
        device="cpu",
        ds_factor=1.0,
    )
    calls = []
    expected = lambda a, b: [a, "gimm-mid", b]
    signature = (
        str(gimm_settings.root),
        str(gimm_settings.config_path),
        str(gimm_settings.checkpoint_path),
        "cpu",
        1.0,
    )
    monkeypatch.setattr(
        gimm_module,
        "build_gimm_engine",
        lambda settings: (calls.append(settings) or expected, signature),
    )
    monkeypatch.setattr(engines_module, "_BOX_RUNTIMES", {})

    first = _get_box_runtime(
        "gimm",
        box_settings=box_settings,
        gimm_settings=gimm_settings,
    )
    second = _get_box_runtime(
        "gimm",
        box_settings=box_settings,
        gimm_settings=gimm_settings,
    )

    assert first is second
    assert first.interpolator == "gimm"
    assert first.interpolation_engine is expected
    assert calls == [gimm_settings]
