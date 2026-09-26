"""Thin client for the external payment gateway."""

from dataclasses import dataclass


class GatewayTimeout(Exception):
    """The gateway did not respond in time.

    The charge MAY still have been applied on the gateway side. Retrying is
    safe only when the retry reuses the same idempotency key: the gateway
    deduplicates requests by key and returns the original charge.
    """


@dataclass(frozen=True)
class Charge:
    charge_id: str
    amount_cents: int


class PaymentGateway:
    def charge(self, *, amount_cents: int, idempotency_key: str) -> Charge:
        raise NotImplementedError("provided by the vendor SDK in production")
