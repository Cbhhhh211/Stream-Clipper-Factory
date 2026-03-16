import json

from stream_clipper.ml.llm_reranker import (
    LLMRerankConfig,
    analyze_candidates_with_llm,
    rerank_candidates_with_llm,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.called = False
        self.last_json = None

    def post(self, _url, headers=None, json=None):
        _ = headers
        self.called = True
        self.last_json = json
        return _FakeResponse(self.payload)

    def close(self):
        return None


def _candidates():
    return [
        {
            "index": 0,
            "clip_start": 0.0,
            "clip_end": 20.0,
            "duration": 20.0,
            "score": 0.4,
            "base_rank_score": 0.4,
            "danmaku_count": 10,
            "top_keywords": ["普通"],
            "danmaku_excerpt": "普通片段",
            "asr_excerpt": "普通叙述",
        },
        {
            "index": 1,
            "clip_start": 30.0,
            "clip_end": 55.0,
            "duration": 25.0,
            "score": 0.7,
            "base_rank_score": 0.8,
            "danmaku_count": 200,
            "top_keywords": ["封神", "666"],
            "danmaku_excerpt": "封神 666 666",
            "asr_excerpt": "这波操作太强了",
        },
    ]


def test_rerank_candidates_with_llm_parses_json_content() -> None:
    content = json.dumps(
        {
            "scores": [
                {"index": 1, "score": 0.92, "title": "极限反杀", "reason": "情绪与反转都很强"},
            ]
        },
        ensure_ascii=False,
    )
    fake = _FakeClient(
        {"choices": [{"message": {"content": content}}]}
    )
    cfg = LLMRerankConfig(
        enabled=True,
        base_url="https://example.com/v1",
        api_key="test-key",
        model="test-model",
        max_candidates=10,
        score_weight=0.7,
        timeout_sec=5.0,
    )
    out = rerank_candidates_with_llm(_candidates(), cfg, client=fake)

    assert fake.called
    assert 1 in out
    assert abs(float(out[1]["score"]) - 0.92) < 1e-9
    assert out[1]["title"] == "极限反杀"


def test_rerank_candidates_with_llm_parses_wrapped_json() -> None:
    wrapped = "```json\n" + json.dumps({"scores": [{"index": 1, "score": 0.8}]}) + "\n```"
    fake = _FakeClient({"choices": [{"message": {"content": wrapped}}]})
    cfg = LLMRerankConfig(enabled=True, model="x")
    out = rerank_candidates_with_llm(_candidates(), cfg, client=fake)
    assert 1 in out
    assert abs(float(out[1]["score"]) - 0.8) < 1e-9


def test_rerank_candidates_with_llm_disabled_returns_empty() -> None:
    fake = _FakeClient({"choices": []})
    cfg = LLMRerankConfig(enabled=False)
    out = rerank_candidates_with_llm(_candidates(), cfg, client=fake)
    assert out == {}
    assert not fake.called


def test_analyze_candidates_with_llm_parses_summary_tags_and_hook() -> None:
    content = json.dumps(
        {
            "scores": [
                {
                    "index": 1,
                    "score": 0.88,
                    "title": "反杀瞬间",
                    "reason": "冲突和结果都明确",
                    "summary": "主播先被压制，随后完成快速反杀。",
                    "tags": ["反杀", "冲突", "高能"],
                    "hook": True,
                }
            ]
        },
        ensure_ascii=False,
    )
    fake = _FakeClient({"choices": [{"message": {"content": content}}]})
    cfg = LLMRerankConfig(enabled=True, model="x")

    out = analyze_candidates_with_llm(_candidates(), cfg, client=fake)

    assert 1 in out
    assert out[1]["summary"] == "主播先被压制，随后完成快速反杀。"
    assert out[1]["tags"] == ["反杀", "冲突", "高能"]
    assert out[1]["hook"] is True
