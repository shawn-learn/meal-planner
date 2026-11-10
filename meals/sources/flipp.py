"""Weekly flyer deals from Flipp, the flyer app most Canadian grocers publish to.

Flipp's app talks to ``backflipp.wishabi.com``; it isn't an official public API, so this module
keeps to one plain search per ingredient and treats every field as optional. If Flipp changes
something, the planner keeps working; it just plans without deals until this is fixed.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

SEARCH_URL = "https://backflipp.wishabi.com/flipp/items/search"
FLYER_LINK = "https://flipp.com/en-ca/item/{id}"


@dataclass
class Deal:
    store: str
    name: str
    price: float | None
    price_text: str
    regular_price: float | None
    unit: str | None
    valid_from: str | None
    valid_to: str | None
    image_url: str | None
    link: str | None
    query: str


def _float(value: Any) -> float | None:
    try:
        return float(str(value).replace("$", "").strip()) if value not in (None, "") else None
    except ValueError:
        return None


def _date(value: Any) -> str | None:
    return str(value)[:10] if value else None


def parse_item(raw: dict[str, Any], query: str) -> Deal | None:
    name = str(raw.get("name") or "").strip()
    store = str(raw.get("merchant_name") or raw.get("merchant") or "").strip()
    if not name or not store:
        return None
    price = _float(raw.get("current_price"))
    pre = str(raw.get("pre_price_text") or "").strip()
    post = str(raw.get("post_price_text") or "").strip()
    story = str(raw.get("sale_story") or "").strip()
    parts = [pre, f"${price:.2f}" if price is not None else "", post]
    price_text = " ".join(p for p in parts if p).replace(" /", "/") or story or "On sale"
    if story and story.lower() not in price_text.lower():
        price_text = f"{price_text} · {story}" if price is not None else story
    unit = None
    low = post.lower()
    for u in ("/lb", "/kg", "/100 g", "/100g", "/ea", "each"):
        if u in low:
            unit = u.strip("/ ")
    item_id = raw.get("flyer_item_id") or raw.get("id")
    return Deal(
        store=store,
        name=name,
        price=price,
        price_text=price_text,
        regular_price=_float(raw.get("original_price")),
        unit=unit,
        valid_from=_date(raw.get("valid_from")),
        valid_to=_date(raw.get("valid_to")),
        image_url=raw.get("clean_image_url") or raw.get("clipping_image_url"),
        link=FLYER_LINK.format(id=item_id) if item_id else None,
        query=query,
    )


def wanted_store(store: str, stores: list[str]) -> bool:
    low = store.lower()
    return any(s.lower() in low for s in stores)


async def search(
    client: httpx.AsyncClient, postal_code: str, query: str, stores: list[str]
) -> list[Deal]:
    resp = await client.get(
        SEARCH_URL, params={"locale": "en-ca", "postal_code": postal_code, "q": query}
    )
    resp.raise_for_status()
    payload = resp.json()
    items = payload.get("items", []) if isinstance(payload, dict) else []
    out: list[Deal] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        deal = parse_item(raw, query)
        if deal and wanted_store(deal.store, stores):
            out.append(deal)
    return out


async def search_many(
    postal_code: str,
    queries: list[str],
    stores: list[str],
    timeout_s: float = 15.0,
    transport: httpx.AsyncBaseTransport | None = None,
    concurrency: int = 4,
) -> tuple[list[Deal], list[str]]:
    """Run every query politely (a few at a time). Returns deals and the queries that failed."""
    sem = asyncio.Semaphore(concurrency)
    failed: list[str] = []
    headers = {"User-Agent": "Mozilla/5.0 (meal-planner; personal use)"}

    async with httpx.AsyncClient(timeout=timeout_s, headers=headers, transport=transport) as c:

        async def one(q: str) -> list[Deal]:
            async with sem:
                try:
                    return await search(c, postal_code, q, stores)
                except (httpx.HTTPError, ValueError):
                    failed.append(q)
                    return []

        results = await asyncio.gather(*(one(q) for q in queries))
    return [d for batch in results for d in batch], failed
