"""
LLM-based reranking for highlight candidates.

Uses an OpenAI-compatible Chat Completions API.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

from ..utils import parse_bool


def _extract_json_object(text: str) -> Dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        obj = json.loads(raw[start : end + 1])
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


@dataclass
class LLMRerankConfig:
    enabled: bool = False
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout_sec: float = 30.0
    max_candidates: int = 20
    score_weight: float = 0.65

    @classmethod
    def from_env(
        cls,
        *,
        enabled: Optional[bool] = None,
        model: Optional[str] = None,
        max_candidates: Optional[int] = None,
        score_weight: Optional[float] = None,
        timeout_sec: Optional[float] = None,
    ) -> "LLMRerankConfig":
        env_enabled = parse_bool(os.getenv("ENABLE_LLM_RERANK", "0"), False)
        base_url = str(os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")).strip().rstrip("/")
        api_key = str(os.getenv("LLM_API_KEY", "")).strip()
        env_model = str(os.getenv("LLM_MODEL", "gpt-4o-mini")).strip() or "gpt-4o-mini"
        env_max = int(os.getenv("LLM_MAX_CANDIDATES", "20"))
        env_weight = float(os.getenv("LLM_SCORE_WEIGHT", "0.65"))
        env_timeout = float(os.getenv("LLM_TIMEOUT_SEC", "30"))
        return cls(
            enabled=env_enabled if enabled is None else bool(enabled),
            base_url=base_url,
            api_key=api_key,
            model=(model or env_model),
            timeout_sec=float(timeout_sec if timeout_sec is not None else env_timeout),
            max_candidates=max(1, int(max_candidates if max_candidates is not None else env_max)),
            score_weight=max(0.0, min(1.0, float(score_weight if score_weight is not None else env_weight))),
        )


def rerank_candidates_with_llm(
    candidates: List[Dict[str, Any]],
    config: LLMRerankConfig,
    *,
    client: Optional[httpx.Client] = None,
) -> Dict[int, Dict[str, Any]]:
    analyses = analyze_candidates_with_llm(candidates, config, client=client)
    if not analyses:
        return {}
    return {
        idx: {
            "score": item.get("score", 0.0),
            "title": item.get("title", ""),
            "reason": item.get("reason", ""),
        }
        for idx, item in analyses.items()
    }


def analyze_candidates_with_llm(
    candidates: List[Dict[str, Any]],
    config: LLMRerankConfig,
    *,
    client: Optional[httpx.Client] = None,
) -> Dict[int, Dict[str, Any]]:
    """
    Return a mapping:
      candidate_index -> {
        "score": float,
        "title": str,
        "reason": str,
        "summary": str,
        "tags": List[str],
        "hook": bool,
      }
    """
    if not candidates:
        return {}
    if not config.enabled:
        return {}
    if not config.model:
        return {}

    ranked = sorted(
        candidates,
        key=lambda c: float(c.get("base_rank_score", c.get("score", 0.0)) or 0.0),
        reverse=True,
    )[: config.max_candidates]

    prompt_items = []
    for c in ranked:
        idx = int(c.get("index", -1))
        if idx < 0:
            continue
        prompt_items.append(
            {
                "index": idx,
                "start": round(float(c.get("clip_start", 0.0)), 2),
                "end": round(float(c.get("clip_end", 0.0)), 2),
                "duration": round(float(c.get("duration", 0.0)), 2),
                "base_rank_score": round(float(c.get("base_rank_score", 0.0)), 4),
                "resonance_score": round(float(c.get("score", 0.0)), 4),
                "virality_score": (
                    None
                    if c.get("virality_score") is None
                    else round(float(c.get("virality_score", 0.0)), 4)
                ),
                "danmaku_count": int(c.get("danmaku_count", 0) or 0),
                "top_keywords": list(c.get("top_keywords", []) or [])[:6],
                "danmaku_excerpt": str(c.get("danmaku_excerpt", ""))[:320],
                "asr_excerpt": str(c.get("asr_excerpt", ""))[:320],
            }
        )

    if not prompt_items:
        return {}

    system_prompt = (
        "你是中文视频高光候选分析器。请根据每段的字幕与弹幕摘录判断传播价值，"
        "并输出一句中文摘要与标签。优先考虑：情绪爆发、反转、冲突、笑点、信息密度、"
        "上下文完整度。只返回 JSON，不要输出额外文本。"
    )
    user_payload = {
        "task": (
            "给每个候选片段打0-1分，分越高越值得进入最终高光列表；"
            "同时总结每段主要内容，给2-4个短标签，并标记它是否具备明显吸引力开头。"
        ),
        "schema": {
            "scores": [
                {
                    "index": 0,
                    "score": 0.0,
                    "title": "简短标题",
                    "reason": "一句话原因",
                    "summary": "一句话概括主要内容",
                    "tags": ["标签1", "标签2"],
                    "hook": True,
                }
            ]
        },
        "clips": prompt_items,
    }

    headers = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"

    own_client = client is None
    http = client or httpx.Client(timeout=float(config.timeout_sec))
    try:
        resp = http.post(
            f"{config.base_url}/chat/completions",
            headers=headers,
            json={
                "model": config.model,
                "temperature": 0.1,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
                ],
                "response_format": {"type": "json_object"},
            },
        )
        resp.raise_for_status()
        body = resp.json()
    finally:
        if own_client:
            http.close()

    choices = body.get("choices", []) if isinstance(body, dict) else []
    if not choices:
        return {}
    content = (
        ((choices[0] or {}).get("message") or {}).get("content")
        if isinstance(choices[0], dict)
        else ""
    )
    parsed = _extract_json_object(str(content or ""))
    rows = parsed.get("scores", []) if isinstance(parsed, dict) else []
    if not isinstance(rows, list):
        return {}

    valid_indices = {int(c["index"]) for c in prompt_items if "index" in c}
    result: Dict[int, Dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if idx not in valid_indices:
            continue
        try:
            score = float(item.get("score", 0.0))
        except (TypeError, ValueError):
            continue
        score = max(0.0, min(1.0, score))
        title = str(item.get("title", "") or "").strip()[:80]
        reason = str(item.get("reason", "") or "").strip()[:240]
        summary = str(item.get("summary", "") or "").strip()[:240]
        raw_tags = item.get("tags", [])
        tags = []
        if isinstance(raw_tags, list):
            for tag in raw_tags[:6]:
                text = str(tag or "").strip()[:24]
                if text:
                    tags.append(text)
        hook = bool(item.get("hook", False))
        result[idx] = {
            "score": score,
            "title": title,
            "reason": reason,
            "summary": summary,
            "tags": tags,
            "hook": hook,
        }

    return result


