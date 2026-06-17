"""
Self-test for the price monitor's change-detection logic.

Runs entirely offline with synthetic before/after data, so it proves the diff
and summary without touching the MrScraper API. Run: python selftest.py
"""

from monitor import _normalize, diff, format_summary

TARGETS = [
    {"retailer": "BestBuy", "url": "u1"},
    {"retailer": "Amazon", "url": "u2"},
    {"retailer": "Walmart", "url": "u3"},
    {"retailer": "Amazon", "url": "u4"},
    {"retailer": "BestBuy", "url": "u5"},
    {"retailer": "Walmart", "url": "u6"},
]


def p(name, price, in_stock=True, currency="USD"):
    return {"name": name, "price": price, "currency": currency, "in_stock": in_stock}


def run() -> bool:
    previous = {
        "u1": p("Powerbeats Pro 2", 249.99),
        "u2": p("Samsung SSD 990 Pro 2TB", 169.99),
        "u3": p("Sony WH-1000XM6", 449.99),
        "u4": p("AirPods Pro 2", 199.99, in_stock=False),
        "u5": p("Logitech MX Master 3S", 99.99),
        "u6": p("Anker 737 Power Bank", 109.99),
    }
    current = {
        "u1": p("Powerbeats Pro 2", 199.99),              # price drop -20%
        "u2": p("Samsung SSD 990 Pro 2TB", None, in_stock=False),  # OOS, price hidden
        "u3": p("Sony WH-1000XM6", 469.99),               # +4.4%, under 5% threshold
        "u4": p("AirPods Pro 2", 199.99, in_stock=True),  # back in stock
        "u5": p("Logitech MX Master 3S", 119.99),         # price increase +20%
        "u6": p("Anker 737 Power Bank", 109.99),          # unchanged
    }

    result = diff(previous, current, TARGETS, threshold_pct=5.0)
    types = sorted(e["type"] for e in result["events"])

    expected = ["back_in_stock", "out_of_stock", "price_drop", "price_increase"]
    assert types == expected, f"event types wrong: {types}"
    assert result["unchanged"] == 2, f"unchanged should be 2 (XM6 sub-threshold + Anker), got {result['unchanged']}"

    drop = next(e for e in result["events"] if e["type"] == "price_drop")
    assert abs(drop["pct"] - (-20.0)) < 0.01, drop["pct"]

    oos = next(e for e in result["events"] if e["type"] == "out_of_stock")
    assert oos["name"] == "Samsung SSD 990 Pro 2TB"  # kept despite hidden price

    # New product on first sight produces no event.
    first_seen = diff({}, {"u1": p("X", 10.0)}, TARGETS, 5.0)
    assert first_seen["events"] == [] and first_seen["unchanged"] == 0

    # Blocked/empty render is rejected, not stored as a fake in-stock product.
    assert _normalize({"name": None, "price": None, "in_stock": None}) is None
    assert _normalize({"name": "the product title", "price": "number, digits only", "in_stock": None}) is None
    # A real out-of-stock page (title present, price hidden, explicit stock) is kept.
    oos_page = _normalize({"name": "Real Item", "price": None, "in_stock": "Out of stock"})
    assert oos_page is not None and oos_page["in_stock"] is False and oos_page["price"] is None
    # A normal in-stock page with a price is kept.
    ok_page = _normalize({"name": "Real Item", "price": "1,299.00", "in_stock": "In stock"})
    assert ok_page["price"] == 1299.0 and ok_page["in_stock"] is True

    print("All assertions passed.\n")
    print("=" * 48)
    # missing=1 simulates one product that failed to scrape this run.
    print(format_summary(result, missing=1))
    print("=" * 48)
    return True


if __name__ == "__main__":
    run()
