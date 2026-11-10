"""Turning a recipe's ingredient line into something a shopping list and a flyer can agree on.

"2 lb boneless skinless chicken thighs, trimmed" → quantity 2, unit "lb", item "chicken thigh".

The item is a short, singular, lowercase name with the prep words and brands taken off, so the
same thing from two recipes adds up, and a flyer's "Maple Leaf Chicken Thighs Value Pack" can
be matched to it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction

UNICODE_FRACTIONS = {
    "½": "1/2",
    "⅓": "1/3",
    "⅔": "2/3",
    "¼": "1/4",
    "¾": "3/4",
    "⅕": "1/5",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}

UNITS = {
    "tsp": "tsp",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tbsp": "tbsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "cup": "cup",
    "cups": "cup",
    "c": "cup",
    "oz": "oz",
    "ounce": "oz",
    "ounces": "oz",
    "lb": "lb",
    "lbs": "lb",
    "pound": "lb",
    "pounds": "lb",
    "g": "g",
    "gram": "g",
    "grams": "g",
    "kg": "kg",
    "ml": "ml",
    "l": "l",
    "litre": "l",
    "liter": "l",
    "can": "can",
    "cans": "can",
    "tin": "can",
    "jar": "jar",
    "jars": "jar",
    "package": "pkg",
    "packages": "pkg",
    "pkg": "pkg",
    "bunch": "bunch",
    "bunches": "bunch",
    "head": "head",
    "heads": "head",
    "clove": "clove",
    "cloves": "clove",
    "slice": "slice",
    "slices": "slice",
    "pinch": "pinch",
    "dash": "dash",
    "stalk": "stalk",
    "stalks": "stalk",
    "sprig": "sprig",
    "sprigs": "sprig",
    "bag": "bag",
    "bags": "bag",
}

# Words that describe how the thing is prepared or sold, not what it is.
DESCRIPTORS = {
    "fresh",
    "freshly",
    "frozen",
    "chopped",
    "diced",
    "minced",
    "sliced",
    "thinly",
    "finely",
    "roughly",
    "coarsely",
    "grated",
    "shredded",
    "crushed",
    "peeled",
    "seeded",
    "trimmed",
    "boneless",
    "skinless",
    "bone-in",
    "skin-on",
    "large",
    "medium",
    "small",
    "extra",
    "extra-virgin",
    "virgin",
    "lean",
    "extra-lean",
    "organic",
    "raw",
    "cooked",
    "uncooked",
    "dry",
    "dried",
    "packed",
    "softened",
    "melted",
    "room",
    "temperature",
    "cold",
    "warm",
    "hot",
    "optional",
    "divided",
    "plus",
    "more",
    "to",
    "taste",
    "for",
    "serving",
    "garnish",
    "about",
    "approx",
    "approximately",
    "whole",
    "halved",
    "quartered",
    "cubed",
    "rinsed",
    "drained",
    "canned",
    "low-sodium",
    "reduced-sodium",
    "unsalted",
    "salted",
    "of",
    "a",
    "an",
    "the",
    "and",
    "or",
    "into",
    "pieces",
    "piece",
    "inch",
    "cm",
    "x",
}

# Words where taking an "s" off would be wrong.
KEEP_S = {
    "hummus",
    "couscous",
    "asparagus",
    "molasses",
    "swiss",
    "brussels",
    "lentils",
    "oats",
    "grits",
    "series",
    "species",
    "chips",
    "greens",
    "noodles",
    "peas",
    "chickpeas",
}

IRREGULAR = {
    "tomatoes": "tomato",
    "potatoes": "potato",
    "leaves": "leaf",
    "loaves": "loaf",
    "knives": "knife",
    "berries": "berry",
    "cherries": "cherry",
    "anchovies": "anchovy",
    "tortillas": "tortilla",
    "chilies": "chili",
    "chillies": "chili",
    "radishes": "radish",
    "peaches": "peach",
    "sandwiches": "sandwich",
    "mangoes": "mango",
}

_NUM = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_LEAD = re.compile(rf"^\s*(?P<qty>{_NUM})(?:\s*(?:-|to|–)\s*(?P<qty2>{_NUM}))?\s*")
_PARENS = re.compile(r"\([^)]*\)")
_WORD = re.compile(r"[a-z][a-z'\-]*")


@dataclass(frozen=True)
class Ingredient:
    line: str
    quantity: float | None
    unit: str | None
    item: str

    def as_dict(self) -> dict[str, object]:
        return {"line": self.line, "quantity": self.quantity, "unit": self.unit, "item": self.item}


def singular(word: str) -> str:
    if word in KEEP_S or len(word) <= 3:
        return word
    if word in IRREGULAR:
        return IRREGULAR[word]
    if word.endswith("ies") and len(word) > 4:
        return word[:-3] + "y"
    if word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _number(text: str) -> float:
    total = Fraction(0)
    for part in text.split():
        total += Fraction(part)
    return float(total)


def normalize(text: str) -> str:
    """A shopping name: lowercase, singular, no descriptors. Also used on flyer names."""
    text = text.lower()
    for k in UNICODE_FRACTIONS:
        text = text.replace(k, " ")
    text = _PARENS.sub(" ", text)
    words = [singular(w.strip("'-")) for w in _WORD.findall(text)]
    kept = [w for w in words if w and w not in DESCRIPTORS and w not in UNITS]
    return " ".join(kept).strip()


def parse(line: str) -> Ingredient:
    raw = " ".join(line.split())
    text = raw
    for k, v in UNICODE_FRACTIONS.items():
        text = re.sub(rf"(\d){k}", rf"\1 {v}", text)
        text = text.replace(k, v)
    quantity: float | None = None
    unit: str | None = None
    m = _LEAD.match(text)
    if m:
        quantity = _number(m.group("qty"))
        if m.group("qty2"):  # "2-3 cloves": plan for the larger amount
            quantity = max(quantity, _number(m.group("qty2")))
        text = text[m.end() :]
    # A size in parentheses right after the number, e.g. "1 (28 oz) can tomatoes".
    text = re.sub(r"^\(\s*[^)]*\)\s*", "", text)
    first = text.split(" ", 1)
    if first and first[0].lower().rstrip(".") in UNITS:
        unit = UNITS[first[0].lower().rstrip(".")]
        text = first[1] if len(first) > 1 else ""
    # The item is what comes before the first comma ("onion, diced").
    name_part = text.split(",", 1)[0]
    item = normalize(name_part) or normalize(text) or raw.lower()
    return Ingredient(line=raw, quantity=quantity, unit=unit, item=item)


def tokens(text: str) -> set[str]:
    return set(normalize(text).split())


def matches(item: str, product: str) -> bool:
    """Does a flyer `product` name offer this shopping `item`? Every word of the item has to
    appear in the product, so "chicken thigh" matches "Chicken Thighs Value Pack" but "chicken
    breast" doesn't, and "pepper" doesn't match "Pepperoni"."""
    want = set(item.split())
    if not want:
        return False
    return want <= tokens(product)


def is_pantry(item: str, pantry: list[str]) -> bool:
    norm = {normalize(p) for p in pantry}
    if item in norm:
        return True
    # "salt pepper" (from "salt and pepper to taste"): every word is a one-word staple.
    singles = {n for n in norm if " " not in n}
    words = item.split()
    return len(words) > 1 and all(w in singles for w in words)


def format_quantity(quantity: float | None, unit: str | None) -> str:
    if quantity is None:
        return ""
    frac = Fraction(quantity).limit_denominator(8)
    whole, rest = divmod(frac.numerator, frac.denominator)
    if rest == 0:
        num = str(whole)
    elif whole == 0:
        num = f"{rest}/{frac.denominator}"
    else:
        num = f"{whole} {rest}/{frac.denominator}"
    return f"{num} {unit}" if unit else num
