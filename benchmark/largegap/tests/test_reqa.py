from benchmark.largegap.reqa import flag_clip, flag_rate, subsample_paths


def test_subsample_even_coverage():
    paths = [f"{i:05d}.png" for i in range(65)]
    out = subsample_paths(paths, 16)
    assert len(out) == 16
    assert out[0] == "00000.png" and out[-1] == "00064.png"
    assert out == sorted(set(out))


def test_subsample_short_input_passthrough():
    paths = [f"{i}.png" for i in range(9)]
    assert subsample_paths(paths, 16) == paths


def test_flag_clip_parses_verdict():
    v = flag_clip(["a.png"], vision_fn=lambda p, i, **k: {
        "has_motion_error": "yes", "explanation": "ghosting"})
    assert v == {"flag": True, "explanation": "ghosting"}


def test_flag_clip_preserves_unknown_verdict():
    v = flag_clip(["a.png"], vision_fn=lambda p, i, **k: {
        "has_motion_error": "uncertain", "explanation": "ambiguous"})
    assert v == {"flag": None, "explanation": "ambiguous"}


def test_flag_clip_survives_vlm_error():
    def boom(p, i, **k):
        raise RuntimeError("dead port")

    v = flag_clip(["a.png"], vision_fn=boom)
    assert v["flag"] is None and "dead port" in v["explanation"]


def test_flag_rate_skips_none():
    vs = [{"flag": True}, {"flag": False}, {"flag": None}, {"flag": True}]
    assert flag_rate(vs) == 2 / 3
