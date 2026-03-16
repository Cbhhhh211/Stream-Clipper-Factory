from pathlib import Path
from uuid import uuid4

from stream_clipper.ml.boundary_adaptation import (
    apply_boundary_adaptation,
    update_boundary_profile,
)


def test_update_boundary_profile_and_apply() -> None:
    profile_path = Path("output") / "_test_tmp_boundary" / uuid4().hex / "boundary_profile.json"
    profile_path.parent.mkdir(parents=True, exist_ok=True)

    # Learn a tendency: start earlier (-2s), end later (+3s)
    for _ in range(5):
        profile = update_boundary_profile(-2.0, 3.0, path=profile_path)

    assert profile["count"] >= 5
    assert profile["mean_start_delta"] < 0
    assert profile["mean_end_delta"] > 0

    s, e = apply_boundary_adaptation(
        100.0,
        130.0,
        video_duration=600.0,
        profile=profile,
        min_duration=5.0,
    )
    assert s < 100.0
    assert e > 130.0
    assert e - s >= 5.0
