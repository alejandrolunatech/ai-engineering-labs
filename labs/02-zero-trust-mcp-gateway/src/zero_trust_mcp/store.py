"""Synthetic in-memory commerce state for Lab 02.

This module performs business operations only. It deliberately contains NO
authorization: it does not know who is calling, what role they have, or
whether a human approved anything. That is the point of Phase 2.

Business invariants are enforced here. Those are data-integrity rules, not
security rules: a refund that satisfies them is executed for any caller.

Refund amounts use integer minor units (cents) end-to-end. This avoids a
policy/execution mismatch where a fractional euro value could be authorized
by policy and then rounded differently by the executor.
"""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SEED_PATH = Path(__file__).resolve().parents[2] / "fixtures" / "commerce_seed.json"


class CommerceError(ValueError):
    """A business-rule failure (unknown id, invalid amount). Not an auth failure."""


def _eur_to_cents(amount_eur: float) -> int:
    """Convert trusted fixture prices to cents for comparison with refund minor units."""
    return round(amount_eur * 100)


@dataclass
class CommerceStore:
    customers: dict[str, dict[str, Any]]
    orders: dict[str, dict[str, Any]]
    refunds: list[dict[str, Any]] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)

    @classmethod
    def from_seed(cls, path: Path = SEED_PATH) -> CommerceStore:
        seed = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            customers={c["customer_id"]: copy.deepcopy(c) for c in seed["customers"]},
            orders={o["order_id"]: copy.deepcopy(o) for o in seed["orders"]},
        )

    def get_order(self, order_id: str) -> dict[str, Any]:
        order = self.orders.get(order_id)
        if order is None:
            raise CommerceError(f"unknown order_id: {order_id!r}")
        result = copy.deepcopy(order)
        result["refunded_cents"] = self._refunded_cents(order_id)
        return result

    def search_customer(self, query: str) -> list[dict[str, Any]]:
        needle = query.strip().lower()
        if not needle:
            return []
        matches = []
        for c in self.customers.values():
            haystack = (c["customer_id"], c["full_name"], c["email"])
            if any(needle in value.lower() for value in haystack):
                matches.append(
                    {"customer_id": c["customer_id"], "full_name": c["full_name"], "email": c["email"]}
                )
        return matches

    def export_customer_record(self, customer_id: str) -> dict[str, Any]:
        customer = self.customers.get(customer_id)
        if customer is None:
            raise CommerceError(f"unknown customer_id: {customer_id!r}")
        self.exports.append(customer_id)
        record = copy.deepcopy(customer)
        record["orders"] = [o["order_id"] for o in self.orders.values() if o["customer_id"] == customer_id]
        return record

    def issue_refund(self, order_id: str, amount_cents: int, reason: str) -> dict[str, Any]:
        order = self.orders.get(order_id)
        if order is None:
            raise CommerceError(f"unknown order_id: {order_id!r}")
        if isinstance(amount_cents, bool) or not isinstance(amount_cents, int) or amount_cents <= 0:
            raise CommerceError("amount_cents must be a positive integer")

        remaining = _eur_to_cents(order["total_eur"]) - self._refunded_cents(order_id)
        if amount_cents > remaining:
            raise CommerceError(f"refund exceeds refundable balance of {remaining} cents")

        refund = {
            "refund_id": f"rf-{len(self.refunds) + 1:04d}",
            "order_id": order_id,
            "amount_cents": amount_cents,
            "reason": reason,
        }
        self.refunds.append(refund)
        return {**refund, "refundable_remaining_cents": remaining - amount_cents}

    def _refunded_cents(self, order_id: str) -> int:
        return sum(r["amount_cents"] for r in self.refunds if r["order_id"] == order_id)
