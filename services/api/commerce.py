"""
Helpers for public checkout, lightweight order persistence, and digital delivery.
"""

from __future__ import annotations

import io
import json
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


STRIPE_API_VERSION = "2026-02-25.clover"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def env_value(key: str, fallback: str = "") -> str:
    return os.getenv(key, "").strip() or fallback


@dataclass
class PublicProduct:
    product_id: str
    name: str
    description: str
    price_display: str
    stripe_price_id: str = ""
    download_s3_key: str = ""
    download_url: str = ""
    featured: bool = False

    @property
    def checkout_enabled(self) -> bool:
        return bool(self.stripe_price_id and (self.download_s3_key or self.download_url))


def public_products() -> dict[str, PublicProduct]:
    products = {
        "creator": PublicProduct(
            product_id="creator",
            name=env_value("PUBLIC_PRODUCT_CREATOR_NAME", "流剪工坊 创作者版"),
            description=env_value(
                "PUBLIC_PRODUCT_CREATOR_DESCRIPTION",
                "For solo creators who need a faster way to turn long live replays into short clips.",
            ),
            price_display=env_value("PUBLIC_PRODUCT_CREATOR_PRICE", "CNY 9.9"),
            stripe_price_id=env_value("STRIPE_PRICE_ID_CREATOR"),
            download_s3_key=env_value("PUBLIC_PRODUCT_CREATOR_S3_KEY"),
            download_url=env_value("PUBLIC_PRODUCT_CREATOR_DOWNLOAD_URL"),
            featured=False,
        ),
        "studio": PublicProduct(
            product_id="studio",
            name=env_value("PUBLIC_PRODUCT_STUDIO_NAME", "流剪工坊 工作室版"),
            description=env_value(
                "PUBLIC_PRODUCT_STUDIO_DESCRIPTION",
                "For small teams that want a more reliable delivery workflow and priority support.",
            ),
            price_display=env_value("PUBLIC_PRODUCT_STUDIO_PRICE", "CNY 29.9"),
            stripe_price_id=env_value("STRIPE_PRICE_ID_STUDIO"),
            download_s3_key=env_value("PUBLIC_PRODUCT_STUDIO_S3_KEY"),
            download_url=env_value("PUBLIC_PRODUCT_STUDIO_DOWNLOAD_URL"),
            featured=True,
        ),
    }
    return products


def get_public_product(product_id: str) -> Optional[PublicProduct]:
    return public_products().get(str(product_id).strip().lower())


def creator_checkout_url() -> str:
    product = get_public_product("creator")
    if product and product.checkout_enabled:
        return "/buy/creator"
    return env_value("PUBLIC_PRICE_CREATOR_URL", "")


def studio_checkout_url() -> str:
    product = get_public_product("studio")
    if product and product.checkout_enabled:
        return "/buy/studio"
    return env_value("PUBLIC_PRICE_STUDIO_URL", "")


def orders_root() -> Path:
    configured = env_value("PUBLIC_ORDERS_PATH")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        return path
    return (Path(env_value("OUTPUT_DIR", "./output")) / "_public" / "orders").resolve()


def order_path(order_id: str) -> Path:
    return orders_root() / f"{order_id}.json"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


def read_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def create_order(product: PublicProduct, email: str) -> dict[str, Any]:
    now = utc_now()
    order_id = f"order_{uuid.uuid4().hex[:12]}"
    payload = {
        "order_id": order_id,
        "product_id": product.product_id,
        "email": email.strip().lower(),
        "status": "pending",
        "access_token": secrets.token_urlsafe(24),
        "checkout_url": "",
        "stripe_session_id": "",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "paid_at": None,
        "fulfilled_at": None,
        "download_count": 0,
        "last_event_type": None,
    }
    save_order(payload)
    return payload


def save_order(order: dict[str, Any]) -> None:
    order["updated_at"] = utc_now().isoformat()
    write_json(order_path(order["order_id"]), order)


def load_order(order_id: str) -> Optional[dict[str, Any]]:
    return read_json(order_path(order_id))


def require_order_access(order_id: str, access_token: str) -> dict[str, Any]:
    order = load_order(order_id)
    if not order:
        raise ValueError("order_not_found")
    if not access_token or access_token != order.get("access_token"):
        raise PermissionError("invalid_access_token")
    return order


def mark_order_paid(order: dict[str, Any], *, event_type: str | None = None) -> dict[str, Any]:
    if order.get("status") != "paid":
        order["status"] = "paid"
        order["paid_at"] = utc_now().isoformat()
    if event_type:
        order["last_event_type"] = event_type
    save_order(order)
    return order


def mark_order_status(order: dict[str, Any], status: str, *, event_type: str | None = None) -> dict[str, Any]:
    order["status"] = status
    if event_type:
        order["last_event_type"] = event_type
    save_order(order)
    return order


def complete_download(order: dict[str, Any]) -> dict[str, Any]:
    order["download_count"] = int(order.get("download_count") or 0) + 1
    if not order.get("fulfilled_at"):
        order["fulfilled_at"] = utc_now().isoformat()
    save_order(order)
    return order


def absolute_url_for(request, path: str) -> str:
    base = str(request.base_url).rstrip("/")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{base}{path if path.startswith('/') else '/' + path}"


def stripe_client():
    api_key = env_value("STRIPE_SECRET_KEY")
    if not api_key:
        raise RuntimeError("missing_stripe_secret_key")

    import stripe

    stripe.api_key = api_key
    stripe.api_version = STRIPE_API_VERSION
    return stripe


def create_checkout_session(*, request, order: dict[str, Any], product: PublicProduct) -> str:
    stripe = stripe_client()
    success_path = (
        f"/checkout/success?order_id={order['order_id']}"
        f"&token={order['access_token']}&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_path = f"/buy/{product.product_id}?cancelled=1"
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[
            {
                "price": product.stripe_price_id,
                "quantity": 1,
            }
        ],
        customer_email=order["email"],
        success_url=absolute_url_for(request, success_path),
        cancel_url=absolute_url_for(request, cancel_path),
        metadata={
            "order_id": order["order_id"],
            "product_id": product.product_id,
        },
        payment_intent_data={
            "metadata": {
                "order_id": order["order_id"],
                "product_id": product.product_id,
            }
        },
        allow_promotion_codes=True,
    )
    order["checkout_url"] = session.url
    order["stripe_session_id"] = session.id
    save_order(order)
    return session.url


def construct_stripe_event(payload: bytes, signature: str):
    endpoint_secret = env_value("STRIPE_WEBHOOK_SECRET")
    if not endpoint_secret:
        raise RuntimeError("missing_stripe_webhook_secret")
    stripe = stripe_client()
    return stripe.Webhook.construct_event(payload=payload, sig_header=signature, secret=endpoint_secret)


def build_qr_svg(data: str) -> str:
    import qrcode
    from qrcode.image.svg import SvgPathImage

    image = qrcode.make(data, image_factory=SvgPathImage, box_size=10, border=2)
    buffer = io.BytesIO()
    image.save(buffer)
    return buffer.getvalue().decode("utf-8")
