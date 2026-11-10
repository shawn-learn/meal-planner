"""The week's shopping list: every ingredient the planned dinners need, added up, minus the
pantry, each with the best deal on it and the store to get it at."""

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
) -> dict[str, Any]:
    totals: dict[tuple[str, str | None], float | None] = {}
    uses: dict[str, list[str]] = defaultdict(list)
    lines: dict[str, list[str]] = defaultdict(list)
    first_day: dict[str, _dt.date] = {}
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
                continue
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
            lines[item].append(i["line"])

    by_item: dict[str, list[str]] = defaultdict(list)
    for (item, unit), q in totals.items():
        if q is not None and unit in WHOLE_UNITS:
            q = float(math.ceil(q - 0.05))
        elif q is not None:
            q = round(q * 4) / 4 or q
        amount = ing.format_quantity(q, unit)
        if amount:
            by_item[item].append(amount)

    items = sorted({item for item, _ in totals})
    best: dict[str, dict[str, Any]] = {}
    for item in items:
        usable = deal_mod.for_dinner(deals, first_day[item], shop) if shop else deals
        best.update(deal_mod.best_by_item([item], usable))
    out: list[dict[str, Any]] = []
    for item in items:
        d = best.get(item)
        out.append(
            {
                "item": item,
                "amount": " + ".join(by_item.get(item, [])),
                "for": uses[item],
                "store": d["store"] if d else None,
                "deal": (
                    {
                        "name": d["name"],
                        "price_text": d["price_text"],
                        "savings": d.get("savings"),
                        "link": d.get("link"),
                        "valid_to": d.get("valid_to"),
                    }
                    if d
                    else None
                ),
            }
        )
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in out:
        groups[row["store"] or "Anywhere"].append(row)
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] == "Anywhere", kv[0]))
    savings = sum(r["deal"]["savings"] or 0 for r in out if r["deal"])
    return {
        "items": out,
        "by_store": [{"store": s, "items": rows} for s, rows in ordered],
        "count": len(out),
        "on_sale": sum(1 for r in out if r["deal"]),
        "estimated_savings": round(savings, 2),
    }


def keep_text(row: dict[str, Any], marker: str) -> str:
    """One Keep checkbox: "Chicken thigh · 3 lb · Safeway $3.99/lb 🍽"."""
    parts = [row["item"].capitalize()]
    if row["amount"]:
        parts.append(row["amount"])
    if row["deal"]:
        parts.append(f"{row['store']} {row['deal']['price_text']}")
    text = " · ".join(parts)
    return f"{text} {marker}".strip()
