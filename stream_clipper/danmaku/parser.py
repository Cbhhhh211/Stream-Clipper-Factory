"""Parse Bilibili XML danmaku files into DanmakuComment objects."""

import xml.etree.ElementTree as ET
from typing import List

from .models import DanmakuComment


def parse_xml(xml_path: str) -> List[DanmakuComment]:
    """
    Parse a Bilibili-format danmaku XML file.

    Format of each <d> element:
        <d p="TIME,TYPE,SIZE,COLOR,TIMESTAMP,POOL,USER_HASH,DMID">TEXT</d>
    Index 0: time offset in seconds (float)
    Index 1: type (1=scrolling, 4=bottom, 5=top, 6=reverse, 7=special)
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
    except ET.ParseError as e:
        raise ValueError(f"Failed to parse danmaku XML: {e}") from e

    comments: List[DanmakuComment] = []
    for elem in root.iter("d"):
        p = elem.get("p", "")
        text = (elem.text or "").strip()
        if not text or not p:
            continue
        parts = p.split(",")
        try:
            time_offset = float(parts[0])
            dtype = int(parts[1]) if len(parts) > 1 else 1
            user_id = parts[6] if len(parts) > 6 else ""
        except (ValueError, IndexError):
            continue
        # Skip special/interactive danmaku (type 7, 8)
        if dtype in (7, 8):
            continue
        comments.append(DanmakuComment(
            time_offset=time_offset,
            text=text,
            user_id=user_id,
            dtype=dtype,
        ))

    comments.sort(key=lambda c: c.time_offset)
    return comments


def parse_bilibili_xml(xml_path: str) -> List[DanmakuComment]:
    """Backward-compatible alias used by newer worker code."""
    return parse_xml(xml_path)
