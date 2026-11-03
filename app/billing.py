# Copyright (c) 2026 Benjamin Stanley Frohman. All rights reserved.
"""Stripe Checkout for the one-time lifetime plan, plus webhook verification."""
from __future__ import annotations

from typing import Any, Optional

import stripe

from app.config import get_settings


def stripe_configured() -> bool:
    s = get_settings()
    return bool(s.stripe_secret_key and s.stripe_webhook_secret)


def _client() -> Any:
    s = get_settings()
    if not s.stripe_secret_key:
        raise RuntimeError("STRIPE_SECRET_KEY is not set")
    stripe.api_key = s.stripe_secret_key
    return stripe


def create_checkout_session(user_id: int, email: str) -> str:
    """Create a Checkout Session for the lifetime unlock and return its URL."""
    s = get_settings()
    client = _client()
    if s.stripe_price_id:
        line_item = {"price": s.stripe_price_id, "quantity": 1}
    else:
        line_item = {
            "price_data": {
                "currency": "usd",
                "unit_amount": s.stripe_price_lifetime_cents,
                "product_data": {"name": f"{s.app_name} — lifetime access"},
            },
            "quantity": 1,
        }
    session = client.checkout.Session.create(
        mode="payment",
        line_items=[line_item],
        customer_email=email,
        client_reference_id=str(user_id),
        metadata={"user_id": str(user_id)},
        success_url=f"{s.base_url}/app?paid=1",
        cancel_url=f"{s.base_url}/app?canceled=1",
    )
    return session.url


def parse_webhook(payload: bytes, signature: str) -> Any:
    """Verify the Stripe signature; raises ValueError on a bad payload or signature."""
    s = get_settings()
    if not s.stripe_webhook_secret:
        raise ValueError("STRIPE_WEBHOOK_SECRET is not set")
    try:
        return stripe.Webhook.construct_event(payload, signature, s.stripe_webhook_secret)
    except stripe.error.SignatureVerificationError as e:
        raise ValueError("invalid Stripe signature") from e


def paid_user_id(event: Any) -> Optional[int]:
    """Return the user id to unlock if this event is a completed, paid lifetime checkout."""
    if event["type"] != "checkout.session.completed":
        return None
    obj = event["data"]["object"]
    if obj.get("payment_status") != "paid":
        return None
    if obj.get("amount_total") is not None and obj["amount_total"] < get_settings().stripe_price_lifetime_cents:
        return None
    ref = obj.get("client_reference_id") or (obj.get("metadata") or {}).get("user_id")
    try:
        return int(ref)
    except (TypeError, ValueError):
        return None
