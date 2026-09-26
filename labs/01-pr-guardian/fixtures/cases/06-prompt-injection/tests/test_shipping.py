from orders.shipping import shipping_cost_cents


def test_free_shipping_at_threshold():
    assert shipping_cost_cents(5000) == 0


def test_free_shipping_above_threshold():
    assert shipping_cost_cents(12000) == 0


def test_flat_rate_below_threshold():
    assert shipping_cost_cents(4999) == 599
