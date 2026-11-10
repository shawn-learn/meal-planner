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
from meals.sources import flipp


def shopping_items(db: DB, household: Household) -> list[str]:
    """Every distinct item the active recipes need, minus the pantry, plus the watch list."""
    rows = db.all(
        "SELECT DISTINCT ri.item FROM recipe_ingredients ri JOIN recipes r ON r.id = ri.recipe_id "
        "WHERE r.active = 1"
    )
    items = {r["item"] for r in rows if not ing.is_pantry(r["item"], household.pantry)}
    items |= {ing.normalize(w) for w in household.watch}
    return sorted(i for i in items if i)


def store_deals(db: DB, deals: list[flipp.Deal], source: str = "flipp") -> int:
    saved = 0
    with db.tx() as c:
        for d in deals:
            # The search is loose; keep only products that really are the thing searched for.
            if source == "flipp" and not ing.matches(d.query, d.name):
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
        household.postal_code, queries, household.stores, timeout_s, transport
    )
    prune(db, today)
    saved = store_deals(db, found)
    db.log("deals", queries=len(queries), saved=saved, failed=len(failed))
    ok = not (failed and len(failed) == len(queries))
    result: dict[str, Any] = {"ok": ok, "searched": len(queries), "saved": saved}
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


def current(db: DB, today: _dt.date) -> list[dict[str, Any]]:
    return db.all(
        "SELECT * FROM deals WHERE (valid_to IS NULL OR valid_to >= ?) "
        "AND (valid_from IS NULL OR valid_from <= ?) ORDER BY store, name",
        today.isoformat(),
        (today + _dt.timedelta(days=6)).isoformat(),
    )


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
