from stream_clipper.utils import parse_bool


def test_parse_bool_handles_common_truthy_and_falsy_values() -> None:
    assert parse_bool(True, False) is True
    assert parse_bool(1, False) is True
    assert parse_bool("YES", False) is True
    assert parse_bool("0", True) is False
    assert parse_bool(None, True) is True
    assert parse_bool("", True) is False
