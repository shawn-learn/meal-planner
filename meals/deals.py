"""This week's deals: collected from the flyers once a week, matched to ingredients, and kept
in the database so the planner and the shopping list can use them without going online."""

from __future__ import annotations

import asyncio
import datetime as _dt
from dataclasses import asdict
from typing import Any

import httpx

from meals import ingredients as ing
from meals.config import Household
from meals.db import DB
from meals.sources import cocowest, flipp


def shopping_items(db: DB, household: Household) -> list[str]:
    """Every distinct item the active recipes need, minus the pantry, plus the watch list."""
    rows = db.all(
        "SELECT DISTINCT ri.item FROM recipe_ingredients ri JOIN recipes r ON r.id = ri.recipe_id "
        "WHERE r.active = 1"
    )
    items = {r["item"] for r in rows if not ing.is_pantry(r["item"], household.pantry)}
    items |= {ing.normalize(w) for w in household.watch}
    return sorted(i for i in items if i)


def match_to_items(deals: list[flipp.Deal], items: list[str]) -> list[flipp.Deal]:
    """Keep the deals (from a whole-flyer source) that offer something the recipes use, each
    tagged with that item as its query."""
    out: list[flipp.Deal] = []
    for d in deals:
        hit = next((i for i in items if ing.matches(i, d.name)), None)
        if hit:
            d.query = hit
            out.append(d)
    return out


def store_deals(db: DB, deals: list[flipp.Deal], source: str = "flipp") -> int:
    saved = 0
    with db.tx() as c:
        for d in deals:
            # The search is loose; keep only products that really are the thing searched for.
            if source in ("flipp", "cocowest") and not ing.matches(d.query, d.name):
                continue
            c.execute(
                """INSERT INTO deals (store, name, price, price_text, regular_price, unit,
                   valid_from, valid_to, image_url, link, query, source)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(store, name, valid_to) DO UPDATE SET price=excluded.price,
                   price_text=excluded.price_text, query=excluded.query,
                   fetched_at=datetime('now')""",
                (
                    d.store,
                    d.name,
                    d.price,
                    d.price_text,
                    d.regular_price,
                    d.unit,
                    d.valid_from,
                    d.valid_to,
                    d.image_url,
                    d.link,
                    d.query,
                    source,
                ),
            )
            saved += 1
    return saved


def prune(db: DB, today: _dt.date) -> None:
    with db.tx() as c:
        c.execute(
            "DELETE FROM deals WHERE valid_to IS NOT NULL AND valid_to < ?", (today.isoformat(),)
        )


async def refresh(
    db: DB,
    household: Household,
    today: _dt.date,
    timeout_s: float = 15.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    if not household.postal_code:
        return {"ok": False, "error": "Set deals.postal_code in planner.toml first."}
    queries = shopping_items(db, household)
    found, failed = await flipp.search_many(
        household.postal_code,
        queries,
        household.stores,
        timeout_s,
        transport,
        exclude=household.exclude_stores,
    )
    prune(db, today)
    if found or not failed:
        # A fresh search replaces the last one; manual deals stay.
        with db.tx() as c:
            c.execute("DELETE FROM deals WHERE source = 'flipp'")
    saved = store_deals(db, found)
    result: dict[str, Any] = {"searched": len(queries), "saved": saved}

    if household.cocowest and any("costco" in s.lower() for s in household.stores):
        try:
            costco = await cocowest.fetch(timeout_s, transport)
            matched = match_to_items(costco, queries)
            with db.tx() as c:
                c.execute("DELETE FROM deals WHERE source = 'cocowest'")
            result["costco_cocowest"] = store_deals(db, matched, source="cocowest")
        except (httpx.HTTPError, ValueError) as exc:
            result["costco_cocowest_error"] = str(exc) or type(exc).__name__

    total = saved + int(result.get("costco_cocowest", 0))
    db.log("deals", queries=len(queries), saved=total, failed=len(failed))
    ok = not (failed and len(failed) == len(queries))
    result["ok"] = ok
    if failed:
        result["failed"] = failed[:10]
        result["failed_count"] = len(failed)
    if not ok:
        result["error"] = "Couldn't reach Flipp. The plan will be made without deals."
    return result


def refresh_sync(db: DB, household: Household, today: _dt.date) -> dict[str, Any]:
    return asyncio.run(refresh(db, household, today))


def add_manual(
    db: DB,
    store: str,
    name: str,
    price: float | None,
    valid_to: _dt.date | None,
    note: str = "",
) -> None:
    """A deal you saw yourself (the Costco coupon book, an in-store sticker)."""
    deal = flipp.Deal(
        store=store,
        name=name,
        price=price,
        price_text=(f"${price:.2f}" if price is not None else "On sale")
        + (f" · {note}" if note else ""),
        regular_price=None,
        unit=None,
        valid_from=None,
        valid_to=valid_to.isoformat() if valid_to else None,
        image_url=None,
        link=None,
        query=ing.normalize(name),
    )
    store_deals(db, [deal], source="manual")


def shop_day(week_start: _dt.date, today: _dt.date) -> _dt.date:
    """When the week's shopping happens: today for a week already under way, otherwise the
    weekend before it. A deal only counts if it's on then."""
    return max(today, week_start - _dt.timedelta(days=2))


def current(db: DB, day: _dt.date) -> list[dict[str, Any]]:
    """Deals on sale on `day` (or starting the next day, as flyers often change overnight)."""
    return db.all(
        "SELECT * FROM deals WHERE (valid_to IS NULL OR valid_to >= ?) "
        "AND (valid_from IS NULL OR valid_from <= ?) ORDER BY store, name",
        day.isoformat(),
        (day + _dt.timedelta(days=1)).isoformat(),
    )


# Buy at most this many days ahead of the dinner, so a deal that ends Wednesday helps
# Thursday's and Friday's dinners but not Sunday's.
BUY_AHEAD_DAYS = 2


def on_for_dinner(deal: dict[str, Any], day: _dt.date, shop: _dt.date) -> bool:
    """Can this deal be used for a dinner on `day`, shopping no earlier than `shop`?"""
    latest_buy = max(shop, day - _dt.timedelta(days=BUY_AHEAD_DAYS))
    if deal.get("valid_to") and deal["valid_to"] < latest_buy.isoformat():
        return False
    return not (deal.get("valid_from") and deal["valid_from"] > day.isoformat())


def for_dinner(deals: list[dict[str, Any]], day: _dt.date, shop: _dt.date) -> list[dict[str, Any]]:
    return [d for d in deals if on_for_dinner(d, day, shop)]


def best_by_item(items: list[str], deals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """For each shopping item, the cheapest current deal that offers it."""
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        offers = [d for d in deals if ing.matches(item, d["name"])]
        if not offers:
            continue
        offers.sort(key=lambda d: (d["price"] is None, d["price"] or 0))
        top = dict(offers[0])
        top["savings"] = (
            round(top["regular_price"] - top["price"], 2)
            if top.get("regular_price") and top.get("price")
            else None
        )
        top["others"] = len(offers) - 1
        best[item] = top
    return best


def deal_dict(d: flipp.Deal) -> dict[str, Any]:
    return asdict(d)
