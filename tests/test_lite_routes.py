from services.api import lite_routes


def test_build_config_uses_clip_duration_for_adaptive_caps_when_omitted() -> None:
    cfg = lite_routes._build_config({"clip_duration": 240, "top_n": 3})

    assert cfg.pad_before == 80.0
    assert cfg.pad_after == 160.0
    assert cfg.adaptive_max_before == 80.0
    assert cfg.adaptive_max_after == 160.0


def test_build_config_preserves_explicit_adaptive_caps() -> None:
    cfg = lite_routes._build_config(
        {
            "clip_duration": 240,
            "adaptive_max_before": 45,
            "adaptive_max_after": 60,
        }
    )

    assert cfg.adaptive_max_before == 45.0
    assert cfg.adaptive_max_after == 60.0
