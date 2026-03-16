from pathlib import Path

import pytest

from stream_clipper.danmaku.parser import parse_xml


def test_parse_xml_filters_and_sorts(tmp_path: Path) -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<i>
  <d p="12.5,1,25,16777215,0,0,userA,0">哈哈</d>
  <d p="1.5,4,25,16777215,0,0,userB,0">牛逼</d>
  <d p="3.0,7,25,16777215,0,0,userC,0">special</d>
  <d p="bad,1,25,16777215,0,0,userD,0">invalid</d>
  <d p="2.0,1,25,16777215,0,0,userE,0"></d>
</i>
"""
    p = tmp_path / "danmaku.xml"
    p.write_text(xml, encoding="utf-8")

    comments = parse_xml(str(p))

    assert len(comments) == 2
    assert comments[0].time_offset == pytest.approx(1.5)
    assert comments[0].user_id == "userB"
    assert comments[1].time_offset == pytest.approx(12.5)
    assert comments[1].user_id == "userA"


def test_parse_xml_invalid_xml_raises(tmp_path: Path) -> None:
    p = tmp_path / "broken.xml"
    p.write_text("<i><d>", encoding="utf-8")

    with pytest.raises(ValueError):
        parse_xml(str(p))
