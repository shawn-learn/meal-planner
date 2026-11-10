import asyncio

import httpx

from meals import deals
from meals.sources import cocowest

POST_URL = "https://cocowest.ca/2026/11/costco-flyer-costco-sale-items-for-november-9-15-2026-2026-for-bc-ab-sk-mb/"
HOME = f'<a href="{POST_URL}">This week</a><a href="https://cocowest.ca/about/">About</a>'
POST = """
<p><img decoding="async" data-src="https://cocowest.ca/wp-content/uploads/1424066.jpg"
 alt="1424066 COPPER BLUFF SEAFOOD SMOKED PINK SALMON 454 G ($3.00 INSTANT SAVINGS EXPIRES ON 2026-11-15) $9.99" class="lazy"></p>
<noscript><img src="x.jpg" alt="1424066 COPPER BLUFF SEAFOOD SMOKED PINK SALMON 454 G ($3.00 INSTANT SAVINGS EXPIRES ON 2026-11-15) $9.99"></noscript>
<p><img data-src="https://cocowest.ca/wp-content/uploads/77.jpg"
 alt="1234567 KIRKLAND SIGNATURE CHICKEN THIGHS BONELESS 2 KG ($4.00 INSTANT SAVINGS EXPIRES ON 2026-11-15) $21.99"></p>
<p><img data-src="y.jpg" alt="7654321 DURACELL AA BATTERIES 40 PK $19.99"></p>
<p><img src="logo.png" alt="Cocowest logo"></p>
"""


def test_parse_post() -> None:
    items = cocowest.parse_post(POST, POST_URL)
    assert [i.name for i in items] == [
        "Copper Bluff Seafood Smoked Pink Salmon 454 G",
        "Kirkland Signature Chicken Thighs Boneless 2 Kg",
        "Duracell Aa Batteries 40 Pk",
    ]
    salmon = items[0]
    assert salmon.store == "Costco"
    assert salmon.price == 9.99 and salmon.regular_price == 12.99
    assert salmon.valid_to == "2026-11-15"
    assert salmon.price_text == "$9.99 · save $3.00"
    assert salmon.image_url == "https://cocowest.ca/wp-content/uploads/1424066.jpg"
    assert items[2].valid_to is None and items[2].regular_price is None


def test_latest_post_url() -> None:
    assert cocowest.latest_post_url(HOME) == POST_URL
    assert cocowest.latest_post_url("<html></html>") is None


def test_fetch_and_match_to_recipe_items() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=HOME if req.url.path == "/" else POST)

    found = asyncio.run(cocowest.fetch(transport=httpx.MockTransport(handler)))
    matched = deals.match_to_items(found, ["chicken thigh", "salmon fillet", "garlic"])
    assert [(d.query, d.name.split()[2]) for d in matched] == [("chicken thigh", "Chicken")]
