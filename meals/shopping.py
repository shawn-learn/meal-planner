"""The week's shopping list: every ingredient the planned dinners need, added up, minus what
you already have (pantry staples and anything you ticked off), each with every store that has
it on sale and the cheapest one to get it at."""

from __future__ import annotations

import datetime as _dt
import math
from collections import defaultdict
from typing import Any

from meals import deals as deal_mod
from meals import ingredients as ing
from meals.config import Household
from meals.planner import Choice

# Units that come in whole packages, so 1.5 cans is 2 cans on the list.
WHOLE_UNITS = {"can", "jar", "pkg", "bunch", "head", "bag", None}


def build(
    week: list[Choice],
    household: Household,
    deals: list[dict[str, Any]],
    shop: _dt.date | None = None,
    marks: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """`marks` maps an item to True ("we have it, don't buy") or False ("we're out, buy it").
    Pantry staples count as had unless marked otherwise. `items` is only what to buy; what
    you have is in `have`, so it can be ticked back on."""
    marks = marks or {}
    totals: dict[tuple[str, str | None], float | None] = {}
    uses: dict[str, list[str]] = defaultdict(list)
    first_day: dict[str, _dt.date] = {}
    staples: set[str] = set()
    for ch in week:
        if ch.kind != "cook" or not ch.recipe:
            continue
        r = ch.recipe
        factor = 1.0
        if not r["makes_leftovers"] and r["servings"]:
            factor = household.servings / r["servings"]
        for i in r["ingredients"]:
            item = i["item"]
            if ing.is_pantry(item, household.pantry):
                staples.add(item)
            key = (item, i["unit"])
            q = i["quantity"]
            if q is None:
                totals.setdefault(key, None)
            else:
                prev = totals.get(key)
                totals[key] = (prev or 0) + q * factor
            first_day.setdefault(item, ch.day)
            if r["name"] not in uses[item]:
                uses[item].append(r["name"])

    by_item: dict[str, list[str]] = defaultdict(list)
    for (item, unit), q in totals.items():
        if q is not None and unit in WHOLE_UNITS:
            q = float(math.ceil(q - 0.05))
        elif q is not None:
            q = round(q * 4) / 4 or q
        amount = ing.format_quantity(q, unit)
        if amount:
            by_item[item].append(amount)

    buy: list[dict[str, Any]] = []
    have: list[dict[str, Any]] = []
    for item in sorted({item for item, _ in totals}):
        usable = deal_mod.for_dinner(deals, first_day[item], shop) if shop else deals
        sales = deal_mod.by_store(item, usable)
        d = sales[0] if sales else None
        staple = item in staples
        row = {
            "item": item,
            "amount": " + ".join(by_item.get(item, [])),
            "for": uses[item],
            "store": d["store"] if d else None,
            "deal": _deal(d) if d else None,
            # Every store with it on sale, cheapest first ("deal" is the first of these).
            "sales": [{"store": x["store"], **_deal(x)} for x in sales],
            "have": marks.get(item, staple),
            "staple": staple,
        }
        (have if row["have"] else buy).append(row)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in buy:
        groups[row["store"] or "Anywhere"].append(row)
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] == "Anywhere", kv[0]))
    savings = sum(r["deal"]["savings"] or 0 for r in buy if r["deal"])
    return {
        "items": buy,
        "by_store": [{"store": s, "items": rows} for s, rows in ordered],
        "count": len(buy),
        "on_sale": sum(1 for r in buy if r["deal"]),
        "estimated_savings": round(savings, 2),
        "have": have,
        "have_count": len(have),
    }


def _deal(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": d["name"],
        "price_text": d["price_text"],
        "savings": d.get("savings"),
        "link": d.get("link"),
        "valid_to": d.get("valid_to"),
    }


def sale_text(row: dict[str, Any], limit: int = 3) -> str:
    """Where it's on sale: "Safeway $3.99/lb, also Co-op $4.49/lb"."""
    sales = row.get("sales") or (
        [{"store": row["store"], **row["deal"]}] if row.get("deal") else []
    )
    if not sales:
        return ""
    first, rest = sales[0], sales[1:limit]
    text = f"{first['store']} {first['price_text']}"
    if rest:
        text += ", also " + ", ".join(f"{x['store']} {x['price_text']}" for x in rest)
    return text


def keep_text(row: dict[str, Any], marker: str) -> str:
    """One Keep checkbox: "Chicken thigh · 3 lb · Safeway $3.99/lb, also Co-op $4.49/lb 🍽"."""
    parts = [row["item"].capitalize()]
    if row["amount"]:
        parts.append(row["amount"])
    sale = sale_text(row)
    if sale:
        parts.append(sale)
    text = " · ".join(parts)
    return f"{text} {marker}".strip()
