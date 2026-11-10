"""Costco's weekly sale items for Western Canada, from cocowest.ca.

Costco Canada's own savings page blocks scripts and its flyer barely shows up in Flipp. Cocowest,
a long-running fan blog, posts every Western Canada sale item each week as a photo whose alt text
reads:

    1424066 COPPER BLUFF SEAFOOD SMOKED PINK SALMON 454 G ($3.00 INSTANT SAVINGS EXPIRES ON
    2026-11-15) $9.99

This reads the latest weekly post's home-page link and those alt texts: one page per week, and
nothing else from the site.
"""

from __future__ import annotations

import html
import re

import httpx

from meals.sources.flipp import Deal

HOME = "https://cocowest.ca/"
_POST = re.compile(
    r'href="(https://cocowest\.ca/\d{4}/\d{2}/costco-flyer-costco-sale-items-for-[^"#?]+)"', re.I
)
_ITEM = re.compile(
    r'alt="(?P<num>\d{5,8}) (?P<name>.+?)'
    r"(?: \((?P<save>\$[\d.,]+) INSTANT SAVINGS EXPIRES ON (?P<exp>\d{4}-\d{2}-\d{2})\))?"
    r' \$(?P<price>[\d.,]+)"'
)
_SRC = re.compile(r'(?:data-src|src)="([^"]+)"')


def latest_post_url(home_html: str) -> str | None:
    m = _POST.search(home_html)
    return m.group(1) if m else None


def parse_post(page: str, url: str | None = None) -> list[Deal]:
    out: list[Deal] = []
    seen: set[str] = set()
    for m in _ITEM.finditer(page):
        num = m.group("num")
        if num in seen:  # lazy-loaded images repeat in <noscript>
            continue
        seen.add(num)
        name = html.unescape(m.group("name")).strip()
        price = float(m.group("price").replace(",", ""))
        save = m.group("save")
        savings = float(save.strip("$").replace(",", "")) if save else None
        tag_start = page.rfind("<img", 0, m.start())
        tag = page[tag_start : page.find(">", m.end()) + 1] if tag_start >= 0 else ""
        src = _SRC.search(tag)
        out.append(
            Deal(
                store="Costco",
                name=name.title(),
                price=price,
                price_text=f"${price:.2f}" + (f" · save ${savings:.2f}" if savings else ""),
                regular_price=round(price + savings, 2) if savings else None,
                unit=None,
                valid_from=None,
                valid_to=m.group("exp"),
                image_url=src.group(1) if src else None,
                link=url,
                query="",
            )
        )
    return out


async def fetch(
    timeout_s: float = 15.0, transport: httpx.AsyncBaseTransport | None = None
) -> list[Deal]:
    headers = {"User-Agent": "Mozilla/5.0 (meal-planner; personal use)"}
    async with httpx.AsyncClient(
        timeout=timeout_s, headers=headers, transport=transport, follow_redirects=True
    ) as client:
        home = await client.get(HOME)
        home.raise_for_status()
        url = latest_post_url(home.text)
        if not url:
            raise ValueError("No weekly Costco post on cocowest.ca's home page.")
        post = await client.get(url)
        post.raise_for_status()
    return parse_post(post.text, url)
