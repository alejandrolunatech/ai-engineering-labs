"""Synthetic in-memory commerce state for Lab 02.

This module performs business operations only. It deliberately contains NO
authorization: it does not know who is calling, what role they have, or
whether a human approved anything. That is the point of Phase 2.

Business invariants (order exists, refund amount is positive and does not
exceed what is left to refund) are enforced here. Those are data-integrity
rules, not security rules: a refund that satisfies them is executed for any
caller.
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


def _to_cents(amount_eur: float) -> int:
    return round(amount_eur * 100)


@dataclass
class CommerceStore:
    customers: dict[str, dict[str, Any]]
    orders: dict[str, dict[str, Any]]
    # Side-effect ledgers. Later phases use these to prove whether an action
    # was actually EXECUTED downstream, independently of what was requested.
    refunds: list[dict[str, Any]] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)

    @classmethod
    def from_seed(cls, path: Path = SEED_PATH) -> CommerceStore:
        """Load a fresh, independent copy of the fixture. The file is never written."""
        seed = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            customers={c["customer_id"]: copy.deepcopy(c) for c in seed["customers"]},
            orders={o["order_id"]: copy.deepcopy(o) for o in seed["orders"]},
        )

    # -- reads -------------------------------------------------------------

    def get_order(self, order_id: str) -> dict[str, Any]:
        order = self.orders.get(order_id)
        if order is None:
            raise CommerceError(f"unknown order_id: {order_id!r}")
        result = copy.deepcopy(order)
        result["refunded_eur"] = self._refunded_cents(order_id) / 100
        return result

    def search_customer(self, query: str) -> list[dict[str, Any]]:
        """Case-insensitive substring match on id, name, or email. Returns summaries."""
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
        """Full synthetic PII record plus order history. Recorded as a side effect (egress)."""
        customer = self.customers.get(customer_id)
        if customer is None:
            raise CommerceError(f"unknown customer_id: {customer_id!r}")
        self.exports.append(customer_id)
        record = copy.deepcopy(customer)
        record["orders"] = [o["order_id"] for o in self.orders.values() if o["customer_id"] == customer_id]
        return record

    # -- writes ------------------------------------------------------------

    def issue_refund(self, order_id: str, amount_eur: float, reason: str) -> dict[str, Any]:
        order = self.orders.get(order_id)
        if order is None:
            raise CommerceError(f"unknown order_id: {order_id!r}")
        if not amount_eur > 0:  # also rejects NaN
            raise CommerceError("amount_eur must be positive")
        cents = _to_cents(amount_eur)
        remaining = _to_cents(order["total_eur"]) - self._refunded_cents(order_id)
        if cents > remaining:
            raise CommerceError(f"refund exceeds refundable balance of {remaining / 100:.2f} EUR")

        # NOTE: `reason` is recorded but not validated. Any policy about it
        # (non-empty, allowed values) belongs to the gateway, not here.
        refund = {
            "refund_id": f"rf-{len(self.refunds) + 1:04d}",
            "order_id": order_id,
            "amount_eur": cents / 100,
            "reason": reason,
        }
        self.refunds.append(refund)
        return {**refund, "refundable_remaining_eur": (remaining - cents) / 100}

    def _refunded_cents(self, order_id: str) -> int:
        return sum(_to_cents(r["amount_eur"]) for r in self.refunds if r["order_id"] == order_id)
