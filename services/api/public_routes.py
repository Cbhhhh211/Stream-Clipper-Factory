"""
Public-facing routes used by the marketing site, checkout, and launch workflows.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse

from services.storage.s3 import S3Storage

from .commerce import (
    build_qr_svg,
    complete_download,
    construct_stripe_event,
    create_checkout_session,
    create_order,
    creator_checkout_url,
    env_value,
    get_public_product,
    github_release_download_url,
    load_order,
    mark_order_paid,
    mark_order_status,
    public_products,
    require_order_access,
    studio_checkout_url,
    utc_now,
)
from .schemas import (
    LeadCaptureRequest,
    LeadCaptureResponse,
    PublicCheckoutRequest,
    PublicCheckoutResponse,
    PublicOrderStatusResponse,
    PublicProductResponse,
)

router = APIRouter(prefix="/api/v1/public", tags=["public"])


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


def _pricing_entry(
    prefix: str,
    fallback_name: str,
    fallback_price: str,
    fallback_desc: str,
    fallback_bullets: list[str],
    fallback_cta_label: str,
    fallback_cta_url: str,
    featured: bool,
) -> dict:
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
    booking_url = _site_config_value("PUBLIC_BOOKING_URL", f"mailto:{contact_email}?subject=%E6%B5%81%E5%89%AA%E5%B7%A5%E5%9D%8A%20Demo")
    creator_cta_url = creator_checkout_url()
    studio_cta_url = studio_checkout_url()
    download_url = _site_config_value("PUBLIC_DOWNLOAD_URL", studio_cta_url or creator_cta_url or "/studio")

    return {
        "brandName": _site_config_value("PUBLIC_SITE_BRAND", "流剪工坊"),
        "heroBadge": _site_config_value("PUBLIC_HERO_BADGE", "AI Highlight Engine for Creators"),
        "headline": _site_config_value(
            "PUBLIC_HERO_HEADLINE",
            "把长直播回放更快变成可发布、可复核、可交付的短视频素材。",
        ),
        "subheadline": _site_config_value(
            "PUBLIC_HERO_SUBHEADLINE",
            "面向主播、剪辑师和小团队的本地 AI 切片工具。导入素材后自动转写、打分、生成候选片段，再由人工快速复核导出。",
        ),
        "contactEmail": contact_email,
        "bookingUrl": booking_url,
        "downloadUrl": download_url,
        "demoUrl": _site_config_value("PUBLIC_DEMO_URL", "/studio"),
        "pricing": [
            _pricing_entry(
                "PUBLIC_PRICE_CREATOR",
                "创作者版",
                "CNY 9.9",
                "适合个人主播和兼职剪辑，先跑通直播回放到短视频的基础工作流。",
                ["本地导入与自动切片", "候选片段复核与导出", "适合每天 1-2 场直播"],
                "立即购买",
                creator_cta_url,
                False,
            ),
            _pricing_entry(
                "PUBLIC_PRICE_STUDIO",
                "工作室版",
                "CNY 29.9",
                "适合小团队和稳定接单的剪辑工作室，强调更可靠的交付节奏和支持。",
                ["优先支持与交付说明", "更适合高频批量任务", "推荐作为对外售卖主推款"],
                "购买工作室版",
                studio_cta_url,
                True,
            ),
            _pricing_entry(
                "PUBLIC_PRICE_TEAM",
                "团队定制",
                "CNY 999+",
                "适合机构、MCN 和团队部署，按流程、培训与服务范围定制。",
                ["定制部署与交付", "团队培训与售后", "支持商务咨询"],
                "预约咨询",
                booking_url,
                False,
            ),
        ],
    }


def _order_status_response(order: dict, *, access_token: str) -> PublicOrderStatusResponse:
    download_url = None
    if order.get("status") == "paid":
        download_url = f"/api/v1/public/orders/{order['order_id']}/download?token={access_token}"

    return PublicOrderStatusResponse(
        order_id=order["order_id"],
        product_id=order["product_id"],
        status=order["status"],
        email=order["email"],
        checkout_url=order.get("checkout_url") or None,
        download_url=download_url,
        created_at=datetime.fromisoformat(order["created_at"]),
        updated_at=datetime.fromisoformat(order["updated_at"]),
        paid_at=datetime.fromisoformat(order["paid_at"]) if order.get("paid_at") else None,
    )


@router.get("/site-config")
async def public_site_config():
    return _public_site_config()


@router.get("/products", response_model=list[PublicProductResponse])
async def list_public_products():
    return [
        PublicProductResponse(
            product_id=product.product_id,
            name=product.name,
            description=product.description,
            price_display=product.price_display,
            featured=product.featured,
            checkout_enabled=product.checkout_enabled,
        )
        for product in public_products().values()
    ]


@router.get("/products/{product_id}", response_model=PublicProductResponse)
async def get_public_product_detail(product_id: str):
    product = get_public_product(product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return PublicProductResponse(
        product_id=product.product_id,
        name=product.name,
        description=product.description,
        price_display=product.price_display,
        featured=product.featured,
        checkout_enabled=product.checkout_enabled,
    )


@router.post("/orders/checkout", response_model=PublicCheckoutResponse)
async def create_public_checkout(payload: PublicCheckoutRequest, request: Request):
    product = get_public_product(payload.product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not product.checkout_enabled:
        raise HTTPException(status_code=409, detail="Checkout is not enabled for this product")

    order = create_order(product, payload.email)
    try:
        checkout_url = create_checkout_session(request=request, order=order, product=product)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Failed to create checkout session: {exc}") from exc

    qr_svg_url = f"/api/v1/public/orders/{order['order_id']}/qr?token={order['access_token']}"
    return PublicCheckoutResponse(
        status="ok",
        order_id=order["order_id"],
        access_token=order["access_token"],
        checkout_url=checkout_url,
        qr_svg_url=qr_svg_url,
    )


@router.get("/orders/{order_id}", response_model=PublicOrderStatusResponse)
async def get_public_order_status(order_id: str, token: str = Query(default="")):
    try:
        order = require_order_access(order_id, token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Order not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Invalid order token") from exc
    return _order_status_response(order, access_token=token)


@router.get("/orders/{order_id}/qr")
async def get_public_order_qr(order_id: str, token: str = Query(default="")):
    try:
        order = require_order_access(order_id, token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Order not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Invalid order token") from exc

    if not order.get("checkout_url"):
        raise HTTPException(status_code=409, detail="Checkout URL is not ready")

    svg = build_qr_svg(order["checkout_url"])
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/orders/{order_id}/download")
async def download_public_order_asset(order_id: str, token: str = Query(default="")):
    try:
        order = require_order_access(order_id, token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Order not found") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="Invalid order token") from exc

    if order.get("status") != "paid":
        raise HTTPException(status_code=409, detail="Payment has not completed yet")

    product = get_public_product(order.get("product_id", ""))
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    target_url = ""
    if product.download_url:
        target_url = product.download_url
    elif product.download_s3_key:
        expires = int(env_value("PUBLIC_DOWNLOAD_LINK_TTL_SEC", "900"))
        try:
            storage = S3Storage()
            target_url = storage.presign_download(product.download_s3_key, expires=expires)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to prepare download: {exc}") from exc
    else:
        target_url = github_release_download_url(product)

    if not target_url:
        raise HTTPException(status_code=409, detail="Download is not configured for this product")

    complete_download(order)
    return RedirectResponse(url=target_url, status_code=302)


@router.post("/orders/webhooks/stripe")
async def stripe_checkout_webhook(request: Request):
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = construct_stripe_event(payload, signature)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid Stripe webhook: {exc}") from exc

    event_type = getattr(event, "type", "")
    data = getattr(event, "data", None)
    obj = getattr(data, "object", None)
    if obj is None:
        return {"status": "ignored"}

    metadata = getattr(obj, "metadata", {}) or {}
    order_id = metadata.get("order_id") or getattr(obj, "client_reference_id", None)
    if not order_id:
        return {"status": "ignored", "reason": "missing_order_id"}

    order = load_order(order_id)
    if not order:
        return {"status": "ignored", "reason": "order_not_found"}

    if event_type in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        payment_status = getattr(obj, "payment_status", "")
        if payment_status in {"paid", "no_payment_required"} or event_type == "checkout.session.async_payment_succeeded":
            mark_order_paid(order, event_type=event_type)
        else:
            mark_order_status(order, "processing", event_type=event_type)
    elif event_type == "checkout.session.expired":
        mark_order_status(order, "expired", event_type=event_type)
    elif event_type == "checkout.session.async_payment_failed":
        mark_order_status(order, "failed", event_type=event_type)

    return {"status": "ok"}


@router.post("/leads", response_model=LeadCaptureResponse)
async def capture_lead(payload: LeadCaptureRequest, request: Request):
    lead_id = f"lead_{uuid.uuid4().hex[:12]}"
    created_at = utc_now()

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
