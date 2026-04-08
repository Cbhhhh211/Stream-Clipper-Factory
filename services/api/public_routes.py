"""
Public-facing routes used by the marketing site and launch workflows.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request

from .schemas import LeadCaptureRequest, LeadCaptureResponse

router = APIRouter(prefix="/api/v1/public", tags=["public"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _lead_log_path() -> Path:
    configured = os.getenv("PUBLIC_LEADS_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path
    return (Path(os.getenv("OUTPUT_DIR", "./output")) / "_public" / "leads.jsonl").resolve()


def _site_config_value(key: str, fallback: str = "") -> str:
    value = os.getenv(key, "").strip()
    return value or fallback


def _pricing_entry(prefix: str, fallback_name: str, fallback_price: str, fallback_desc: str, fallback_bullets: list[str], fallback_cta_label: str, fallback_cta_url: str, featured: bool) -> dict:
    bullets = _site_config_value(f"{prefix}_BULLETS", "")
    bullet_items = [item.strip() for item in bullets.split("|") if item.strip()] or fallback_bullets
    return {
        "name": _site_config_value(f"{prefix}_NAME", fallback_name),
        "price": _site_config_value(f"{prefix}_PRICE", fallback_price),
        "description": _site_config_value(f"{prefix}_DESCRIPTION", fallback_desc),
        "bullets": bullet_items,
        "ctaLabel": _site_config_value(f"{prefix}_CTA_LABEL", fallback_cta_label),
        "ctaUrl": _site_config_value(f"{prefix}_URL", fallback_cta_url),
        "featured": featured,
    }


def _public_site_config() -> dict:
    contact_email = _site_config_value("PUBLIC_CONTACT_EMAIL", "founder@example.com")
    booking_url = _site_config_value("PUBLIC_BOOKING_URL", f"mailto:{contact_email}?subject=Stream%20Clipper%20Demo")
    return {
        "brandName": _site_config_value("PUBLIC_SITE_BRAND", "Stream Clipper"),
        "heroBadge": _site_config_value("PUBLIC_HERO_BADGE", "AI Highlight Engine for Creators"),
        "headline": _site_config_value("PUBLIC_HERO_HEADLINE", "把长直播切成能发、能涨粉、能成交的短视频。"),
        "subheadline": _site_config_value(
            "PUBLIC_HERO_SUBHEADLINE",
            "面向主播、切片团队和内容工作室的本地 AI 高光剪辑工具。导入视频后自动转写、打分、出片、复核。",
        ),
        "contactEmail": contact_email,
        "bookingUrl": booking_url,
        "downloadUrl": _site_config_value("PUBLIC_DOWNLOAD_URL", "/studio"),
        "demoUrl": _site_config_value("PUBLIC_DEMO_URL", "/studio"),
        "pricing": [
            _pricing_entry(
                "PUBLIC_PRICE_CREATOR",
                "创作者版",
                "¥99 / 月",
                "给单人创作者和主播，快速把一场直播拆成多个可发片段。",
                ["本地导入与自动切片", "剪辑复核与批量导出", "适合每天 1-2 场直播"],
                "立即开通",
                "",
                False,
            ),
            _pricing_entry(
                "PUBLIC_PRICE_STUDIO",
                "工作室版",
                "¥299 / 月",
                "给小团队和职业切片号，追求更稳定的出片效率和复用能力。",
                ["反馈学习与边界微调", "更适合高频批量任务", "优先支持定制流程"],
                "购买工作室版",
                "",
                True,
            ),
            _pricing_entry(
                "PUBLIC_PRICE_TEAM",
                "团队定制",
                "¥999 起 / 月",
                "给 MCN、品牌直播团队和企业内容团队，按流程与数据要求定制。",
                ["私有部署或内部流程接入", "批量任务和协作方案", "专属培训与支持"],
                "预约咨询",
                booking_url,
                False,
            ),
        ],
    }


@router.get("/site-config")
async def public_site_config():
    return _public_site_config()


@router.post("/leads", response_model=LeadCaptureResponse)
async def capture_lead(payload: LeadCaptureRequest, request: Request):
    lead_id = f"lead_{uuid.uuid4().hex[:12]}"
    created_at = _utc_now()

    record = {
        "lead_id": lead_id,
        "created_at": created_at.isoformat(),
        "name": payload.name.strip(),
        "email": payload.email,
        "role": payload.role.strip(),
        "platform": payload.platform.strip(),
        "goal": payload.goal.strip(),
        "monthly_budget": payload.monthlyBudget.strip(),
        "notes": payload.notes.strip(),
        "source": payload.source.strip(),
        "client_ip": request.client.host if request.client else None,
        "user_agent": request.headers.get("user-agent"),
        "referer": request.headers.get("referer"),
    }

    path = _lead_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")

    return LeadCaptureResponse(
        status="ok",
        lead_id=lead_id,
        created_at=created_at,
    )
