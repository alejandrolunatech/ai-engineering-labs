"""Capture payment for an order, retrying on gateway timeouts."""

import logging
import time
from dataclasses import dataclass

from billing.gateway import Charge, GatewayTimeout, PaymentGateway

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 0.5


@dataclass(frozen=True)
class Order:
    id: str
    total_cents: int


def capture_payment(order: Order, gateway: PaymentGateway, sleep=time.sleep) -> Charge:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        idempotency_key = f"order-{order.id}-attempt-{attempt}"
        try:
            return gateway.charge(
                amount_cents=order.total_cents,
                idempotency_key=idempotency_key,
            )
        except GatewayTimeout:
            logger.warning(
                "gateway timeout for order %s (attempt %d/%d, key=%s)",
                order.id,
                attempt,
                MAX_ATTEMPTS,
                idempotency_key,
            )
            if attempt == MAX_ATTEMPTS:
                raise
            sleep(BACKOFF_SECONDS * attempt)
    raise AssertionError("unreachable")
