import pytest

from billing.gateway import Charge, GatewayTimeout
from billing.payments import Order, capture_payment


class FlakyGateway:
    def __init__(self, failures):
        self.failures = failures
        self.keys = []

    def charge(self, *, amount_cents, idempotency_key):
        self.keys.append(idempotency_key)
        if len(self.keys) <= self.failures:
            raise GatewayTimeout()
        return Charge(charge_id=f"ch_{len(self.keys)}", amount_cents=amount_cents)


def no_sleep(_seconds):
    pass


def test_charges_on_first_attempt():
    gateway = FlakyGateway(failures=0)
    charge = capture_payment(Order("o-1", 1999), gateway, sleep=no_sleep)
    assert charge.amount_cents == 1999
    assert len(gateway.keys) == 1


def test_retries_after_timeout():
    gateway = FlakyGateway(failures=2)
    charge = capture_payment(Order("o-1", 1999), gateway, sleep=no_sleep)
    assert charge.amount_cents == 1999
    assert len(gateway.keys) == 3


def test_gives_up_after_max_attempts():
    gateway = FlakyGateway(failures=10)
    with pytest.raises(GatewayTimeout):
        capture_payment(Order("o-1", 1999), gateway, sleep=no_sleep)


def test_each_attempt_is_traceable():
    gateway = FlakyGateway(failures=1)
    capture_payment(Order("o-1", 1999), gateway, sleep=no_sleep)
    assert gateway.keys == ["order-o-1-attempt-1", "order-o-1-attempt-2"]
