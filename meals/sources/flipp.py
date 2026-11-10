"""Weekly flyer deals from Flipp, the flyer app most Canadian grocers publish to.

Flipp's app talks to ``backflipp.wishabi.com``; it isn't an official public API, so this module
keeps to one plain search per ingredient and treats every field as optional. If Flipp changes
something, the planner keeps working; it just plans without deals until this is fixed.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
import re
from dataclasses import dataclass
from typing import Any
from zoneinfo import ZoneInfo

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


LOCAL = ZoneInfo("America/Edmonton")

# Words around a price that matter to a shopper ("2/", "2 for", "from", "save $3").
_PRE_OK = re.compile(r"^(\d+\s*(/|for)|from|starting|starts|each|ea|reg|save|buy)", re.I)
_STORY_OK = re.compile(r"(save|off|%|\bbuy\b|\bfor\b|\bpts\b|points|free|bonus|limit)", re.I)


def _date(value: Any, tz: ZoneInfo = LOCAL) -> str | None:
    """The local date. Flipp gives UTC: a flyer ending "2026-11-12T04:59:59Z" ends on the
    evening of the 11th in Calgary."""
    if not value:
        return None
    text = str(value)
    try:
        moment = _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text[:10]
    if moment.tzinfo is None:
        return moment.date().isoformat()
    return moment.astimezone(tz).date().isoformat()


def price_text(price: float | None, pre: str, post: str, story: str) -> str:
    """ "$3.99/lb", "2/$5.00", "$12.99 · Save $4", without flyer noise such as "VERIFIED" or
    "Available for Same-Day delivery at a higher price"."""
    pre = pre if _PRE_OK.match(pre) else ""
    parts = [pre, f"${price:.2f}" if price is not None else "", post]
    text = " ".join(p for p in parts if p).replace(" /", "/").replace("/ $", "/$")
    story = story if story and len(story) <= 40 and _STORY_OK.search(story) else ""
    if story and story.lower() not in text.lower():
        text = f"{text} · {story}" if text else story
    return text or "On sale"


def parse_item(raw: dict[str, Any], query: str, tz: ZoneInfo = LOCAL) -> Deal | None:
    name = str(raw.get("name") or "").strip()
    store = str(raw.get("merchant_name") or raw.get("merchant") or "").strip()
    if not name or not store:
        return None
    price = _float(raw.get("current_price"))
    pre = str(raw.get("pre_price_text") or "").strip()
    post = str(raw.get("post_price_text") or "").strip()
    story = str(raw.get("sale_story") or "").strip()
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
        price_text=price_text(price, pre, post, story),
        regular_price=_float(raw.get("original_price")),
        unit=unit,
        valid_from=_date(raw.get("valid_from"), tz),
        valid_to=_date(raw.get("valid_to"), tz),
        image_url=raw.get("clean_image_url") or raw.get("clipping_image_url"),
        link=FLYER_LINK.format(id=item_id) if item_id else None,
        query=query,
    )


def wanted_store(store: str, stores: list[str], exclude: list[str] | None = None) -> bool:
    low = store.lower()
    if any(x.lower() in low for x in exclude or []):
        return False
    return any(s.lower() in low for s in stores)


async def search(
    client: httpx.AsyncClient,
    postal_code: str,
    query: str,
    stores: list[str],
    exclude: list[str] | None = None,
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
        if deal and wanted_store(deal.store, stores, exclude):
            out.append(deal)
    return out


async def search_many(
    postal_code: str,
    queries: list[str],
    stores: list[str],
    timeout_s: float = 15.0,
    transport: httpx.AsyncBaseTransport | None = None,
    concurrency: int = 4,
    exclude: list[str] | None = None,
) -> tuple[list[Deal], list[str]]:
    """Run every query politely (a few at a time). Returns deals and the queries that failed."""
    sem = asyncio.Semaphore(concurrency)
    failed: list[str] = []
    headers = {"User-Agent": "Mozilla/5.0 (meal-planner; personal use)"}

    async with httpx.AsyncClient(timeout=timeout_s, headers=headers, transport=transport) as c:

        async def one(q: str) -> list[Deal]:
            async with sem:
                try:
                    return await search(c, postal_code, q, stores, exclude)
                except (httpx.HTTPError, ValueError):
                    failed.append(q)
                    return []

        results = await asyncio.gather(*(one(q) for q in queries))
    return [d for batch in results for d in batch], failed
