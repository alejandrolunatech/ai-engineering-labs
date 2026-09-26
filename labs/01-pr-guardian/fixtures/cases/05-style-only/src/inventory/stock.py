"""Stock-level helpers for the warehouse dashboard."""


def low_stock_items(items: list[dict], threshold: int = 5) -> list[str]:
    return [item["sku"] for item in items if item["qty"] <= threshold]


def stock_summary(items: list[dict]) -> str:
    total_units = sum(item["qty"] for item in items)
    return f"Total units: {total_units}"
