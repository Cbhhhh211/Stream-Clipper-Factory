"""
Keyword lexicons for excitement and coarse sentiment estimation.
"""

# High-engagement tokens seen in CN livestream chat.
EXCITEMENT_KEYWORDS: frozenset[str] = frozenset(
    {
        # Laughter / fun
        "哈哈",
        "哈哈哈",
        "笑死",
        "笑死我了",
        "绷不住了",
        "太逗了",
        "乐",
        "lol",
        "lmao",
        # Surprise / shock
        "卧槽",
        "我靠",
        "wc",
        "逆天",
        "离谱",
        "炸裂",
        "什么情况",
        "不会吧",
        "震惊",
        "惊了",
        # Admiration / hype
        "牛",
        "牛逼",
        "牛批",
        "nb",
        "666",
        "yyds",
        "awsl",
        "太强了",
        "神",
        "封神",
        "绝了",
        "顶级",
        # Cheer / positive burst
        "冲",
        "冲冲冲",
        "起飞",
        "爆了",
        "燃起来了",
        "可以",
        "好活",
        "太会了",
        # General exclamation
        "哇",
        "哇靠",
        "omg",
        "wow",
    }
)

# Positive/negative sentiment cues for polarity estimation.
POSITIVE_SENTIMENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "牛",
        "牛逼",
        "牛批",
        "神",
        "封神",
        "绝了",
        "太强了",
        "漂亮",
        "好活",
        "稳",
        "精彩",
        "爽",
        "厉害",
        "顶",
        "帅",
        "猛",
    }
)

NEGATIVE_SENTIMENT_KEYWORDS: frozenset[str] = frozenset(
    {
        "菜",
        "下饭",
        "离谱",
        "逆天",
        "寄",
        "崩",
        "蠢",
        "尬",
        "无语",
        "垃圾",
        "太烂",
        "炸了",
        "红温",
        "急了",
        "翻车",
        "破防",
    }
)


def excitement_ratio(texts: list[str]) -> float:
    """
    Return the fraction of texts containing at least one excitement keyword.
    """
    if not texts:
        return 0.0
    hits = sum(1 for text in texts if any(kw in text for kw in EXCITEMENT_KEYWORDS))
    return hits / len(texts)


def sentiment_ratios(texts: list[str]) -> tuple[float, float]:
    """
    Return (positive_ratio, negative_ratio) in [0, 1].
    """
    if not texts:
        return 0.0, 0.0
    pos_hits = sum(1 for text in texts if any(kw in text for kw in POSITIVE_SENTIMENT_KEYWORDS))
    neg_hits = sum(1 for text in texts if any(kw in text for kw in NEGATIVE_SENTIMENT_KEYWORDS))
    n = float(len(texts))
    return pos_hits / n, neg_hits / n

