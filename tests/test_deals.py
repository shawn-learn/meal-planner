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
            "valid_to": "2026-11-12T04:59:59+00:00",
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
    assert d.valid_to == "2026-11-11"  # 10:59 pm in Calgary
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


def test_price_text_drops_flyer_noise() -> None:
    assert flipp.price_text(3.99, "VERIFIED", "", "") == "$3.99"
    assert (
        flipp.price_text(11.99, "", "", "Available for Same-Day delivery at a higher price.")
        == "$11.99"
    )
    assert flipp.price_text(5.0, "2/", "", "SAVE $3") == "2/$5.00 · SAVE $3"
    assert flipp.price_text(5.99, "", "/lb $13.21/kg", "") == "$5.99/lb $13.21/kg"


def test_liquor_stores_are_skipped() -> None:
    stores, exclude = ["Costco", "Safeway", "Co-op"], ["Liquor", "Pharmacy"]
    assert flipp.wanted_store("Safeway", stores, exclude)
    assert flipp.wanted_store("Calgary Co-op", stores, exclude)
    assert not flipp.wanted_store("Sobeys & Safeway Liquor", stores, exclude)
    assert not flipp.wanted_store("Walmart", stores, exclude)


def test_expired_deals_dont_count_for_next_week() -> None:
    db = DB(":memory:")
    deals.add_manual(db, "Safeway", "Chicken Thighs", 3.99, dt.date(2026, 11, 11))
    deals.add_manual(db, "Costco", "Salmon Fillets", 9.99, dt.date(2026, 11, 15))
    next_week = dt.date(2026, 11, 16)
    shop = deals.shop_day(next_week, today=dt.date(2026, 11, 14))  # planned on Saturday
    assert [d["store"] for d in deals.current(db, shop)] == ["Costco"]
    # Planning the current week on Tuesday: shop today, both still on.
    shop = deals.shop_day(dt.date(2026, 11, 9), today=dt.date(2026, 11, 10))
    assert len(deals.current(db, shop)) == 2


def test_deal_counts_only_for_dinners_soon_after_it_ends() -> None:
    deal = {"valid_from": "2026-11-05", "valid_to": "2026-11-11"}
    shop = dt.date(2026, 11, 10)  # planning the current week on Tuesday
    on = [d for d in range(9, 16) if deals.on_for_dinner(deal, dt.date(2026, 11, d), shop)]
    assert on == [9, 10, 11, 12, 13]  # bought by Wednesday, so not for the weekend


def test_online_only_prices_are_skipped() -> None:
    raw = {
        "name": "Ambrosia Apples",
        "merchant_name": "Costco",
        "current_price": 9.99,
        "pre_price_text": "Online Price",
    }
    assert flipp.parse_item(raw, "apple") is None


def test_refresh_replaces_last_search() -> None:
    from meals import recipes
    from tests.conftest import household

    db = DB(":memory:")
    recipes.seed(db)
    hh = household(cocowest=False)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=FLIPP)

    for _ in range(2):
        asyncio.run(
            deals.refresh(db, hh, dt.date(2026, 11, 9), transport=httpx.MockTransport(handler))
        )
    deals.add_manual(db, "Costco", "Chicken Thighs", 12.99, None)
    asyncio.run(deals.refresh(db, hh, dt.date(2026, 11, 9), transport=httpx.MockTransport(handler)))
    rows = db.all("SELECT source, COUNT(*) AS n FROM deals GROUP BY source ORDER BY source")
    assert rows == [{"source": "flipp", "n": 1}, {"source": "manual", "n": 1}]


def test_noise_after_the_price_is_dropped() -> None:
    text = flipp.price_text(
        11.99, "", "Available for Same-Day delivery at a higher price.", "SAVE $3"
    )
    assert text == "$11.99 · SAVE $3"
