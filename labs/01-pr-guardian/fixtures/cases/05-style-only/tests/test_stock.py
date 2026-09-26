from inventory.stock import low_stock_items, stock_summary

ITEMS = [
    {"sku": "A-1", "qty": 2},
    {"sku": "B-2", "qty": 5},
    {"sku": "C-3", "qty": 40},
]


def test_low_stock_items():
    assert low_stock_items(ITEMS) == ["A-1", "B-2"]


def test_low_stock_custom_threshold():
    assert low_stock_items(ITEMS, threshold=1) == []


def test_stock_summary():
    assert stock_summary(ITEMS) == "Total units: 47"


def test_stock_summary_empty():
    assert stock_summary([]) == "Total units: 0"
