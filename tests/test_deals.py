import asyncio
import datetime as dt

import httpx

from meals import deals
from meals.db import DB
from meals.sources import flipp

FLIPP = {
    "items": [
        {
            "flyer_item_id": 1,
            "name": "Maple Leaf Chicken Thighs",
            "merchant_name": "Safeway",
            "current_price": 3.99,
            "post_price_text": "/lb",
            "original_price": "6.49",
            "valid_from": "2026-11-06T00:00:00-07:00",
            "valid_to": "2026-11-12T23:59:59-07:00",
        },
        {"name": "Chicken Thighs", "merchant_name": "Walmart", "current_price": 2.0},
        {"name": "Chicken Nuggets", "merchant_name": "Calgary Co-op", "current_price": 7.0},
        {"name": "", "merchant_name": "Costco"},
    ]
}


def test_parse_item() -> None:
    d = flipp.parse_item(FLIPP["items"][0], "chicken thigh")
    assert d is not None
    assert d.price_text == "$3.99/lb"
    assert d.unit == "lb"
    assert d.regular_price == 6.49
    assert d.valid_to == "2026-11-12"
    assert flipp.parse_item(FLIPP["items"][3], "x") is None


def test_search_filters_stores_and_matches() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.params["postal_code"] == "T3A0A0"
        return httpx.Response(200, json=FLIPP)

    found, failed = asyncio.run(
        flipp.search_many(
            "T3A0A0",
            ["chicken thigh"],
            ["Safeway", "Co-op"],
            transport=httpx.MockTransport(handler),
        )
    )
    assert failed == []
    assert {d.store for d in found} == {"Safeway", "Calgary Co-op"}
    db = DB(":memory:")
    # Nuggets aren't chicken thighs, so only one is kept.
    assert deals.store_deals(db, found) == 1


def test_refresh_survives_flipp_being_down() -> None:
    from tests.conftest import household

    db = DB(":memory:")
    from meals import recipes

    recipes.seed(db)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    r = asyncio.run(
        deals.refresh(db, household(), dt.date(2026, 11, 9), transport=httpx.MockTransport(handler))
    )
    assert r["ok"] is False and "error" in r


def test_best_by_item_and_manual() -> None:
    db = DB(":memory:")
    deals.add_manual(
        db, "Costco", "Kirkland Chicken Thighs", 12.99, dt.date(2026, 11, 30), "coupon"
    )
    deals.add_manual(db, "Safeway", "Chicken Thighs", 9.99, None)
    rows = deals.current(db, dt.date(2026, 11, 9))
    best = deals.best_by_item(["chicken thigh", "salmon"], rows)
    assert best["chicken thigh"]["store"] == "Safeway"
    assert best["chicken thigh"]["others"] == 1
    assert "salmon" not in best
