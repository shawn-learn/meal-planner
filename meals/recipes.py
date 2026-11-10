"""Recipes: the planner's own small cookbook, filled from a starter set, by hand, or by
pasting a link to any recipe page (most recipe sites publish schema.org Recipe data, which is
read here directly, so there's no scraping per site and no AI call)."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

import httpx

from meals import ingredients as ing
from meals.db import DB

PROTEINS = [
    "chicken",
    "beef",
    "pork",
    "turkey",
    "salmon",
    "shrimp",
    "cod",
    "tilapia",
    "tuna",
    "fish",
    "sausage",
    "bacon",
    "ham",
    "lamb",
    "tofu",
    "chickpea",
    "lentil",
    "bean",
    "egg",
]


@dataclass
class Recipe:
    name: str
    ingredients: list[str]
    servings: int = 4
    prep_minutes: int = 15
    cook_minutes: int = 20
    hands_on_minutes: int | None = None
    tags: list[str] = field(default_factory=list)
    instructions: str = ""
    source_url: str | None = None
    image_url: str | None = None
    makes_leftovers: bool = False
    protein: str | None = None


def guess_protein(lines: list[str]) -> str | None:
    items = " ".join(ing.parse(line).item for line in lines)
    words = set(items.split())
    for p in PROTEINS:
        if p in words:
            return p
    return None


def save(db: DB, r: Recipe) -> int:
    protein = r.protein or guess_protein(r.ingredients)
    tags = sorted({t.strip().lower() for t in r.tags if t.strip()})
    with db.tx() as c:
        existing = c.execute("SELECT id FROM recipes WHERE name = ?", (r.name,)).fetchone()
        values = (
            r.source_url,
            r.image_url,
            r.servings,
            r.prep_minutes,
            r.cook_minutes,
            r.hands_on_minutes,
            json.dumps(tags),
            protein,
            r.instructions,
            int(r.makes_leftovers),
        )
        if existing:
            rid = int(existing["id"])
            c.execute(
                """UPDATE recipes SET source_url=?, image_url=?, servings=?, prep_minutes=?,
                   cook_minutes=?, hands_on_minutes=?, tags=?, protein=?, instructions=?,
                   makes_leftovers=?, active=1 WHERE id=?""",
                (*values, rid),
            )
            c.execute("DELETE FROM recipe_ingredients WHERE recipe_id = ?", (rid,))
        else:
            cur = c.execute(
                """INSERT INTO recipes (name, source_url, image_url, servings, prep_minutes,
                   cook_minutes, hands_on_minutes, tags, protein, instructions,
                   makes_leftovers) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (r.name, *values),
            )
            rid = int(cur.lastrowid or 0)
        for pos, line in enumerate(r.ingredients):
            p = ing.parse(line)
            c.execute(
                """INSERT INTO recipe_ingredients (recipe_id, position, line, quantity, unit, item)
                   VALUES (?,?,?,?,?,?)""",
                (rid, pos, p.line, p.quantity, p.unit, p.item),
            )
    return rid


def _row(db: DB, row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    row["tags"] = json.loads(row["tags"])
    row["makes_leftovers"] = bool(row["makes_leftovers"])
    row["active"] = bool(row["active"])
    row["total_minutes"] = row["prep_minutes"] + row["cook_minutes"]
    row["hands_on"] = row["hands_on_minutes"] or row["prep_minutes"] + min(row["cook_minutes"], 10)
    row["ingredients"] = db.all(
        "SELECT line, quantity, unit, item FROM recipe_ingredients WHERE recipe_id = ? "
        "ORDER BY position",
        row["id"],
    )
    stats = db.one(
        "SELECT COUNT(*) AS n, AVG(rating) AS avg FROM ratings WHERE recipe_id = ?", row["id"]
    )
    row["ratings"] = {
        "count": stats["n"] if stats else 0,
        "average": stats["avg"] if stats else None,
    }
    return row


def get(db: DB, recipe_id: int) -> dict[str, Any] | None:
    row = db.one("SELECT * FROM recipes WHERE id = ?", recipe_id)
    return _row(db, row) if row else None


def list_all(db: DB, include_inactive: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM recipes" + ("" if include_inactive else " WHERE active = 1")
    return [_row(db, r) for r in db.all(sql + " ORDER BY name")]


def set_active(db: DB, recipe_id: int, active: bool) -> None:
    with db.tx() as c:
        c.execute("UPDATE recipes SET active = ? WHERE id = ?", (int(active), recipe_id))


def seed(db: DB) -> int:
    """Load the starter recipes the first time (never overwrites your edits)."""
    if db.one("SELECT 1 AS x FROM recipes LIMIT 1"):
        return 0
    data = json.loads(
        resources.files("meals").joinpath("starter_recipes.json").read_text(encoding="utf-8")
    )
    for r in data:
        save(db, Recipe(**r))
    db.log("seed", count=len(data))
    return len(data)


# ── Import from a link ──────────────────────────────────────────────────────────

_ISO_DURATION = re.compile(
    r"P(?:(?P<d>\d+)D)?(?:T(?:(?P<h>\d+)H)?(?:(?P<m>\d+)M)?(?:[\d.]+S)?)?", re.I
)


def minutes(value: Any) -> int | None:
    """ISO 8601 duration ("PT1H15M") to minutes."""
    if not value or not isinstance(value, str):
        return None
    m = _ISO_DURATION.fullmatch(value.strip())
    if not m:
        return None
    d, h, mi = (int(m.group(k) or 0) for k in ("d", "h", "m"))
    return d * 1440 + h * 60 + mi or None


def _find_recipe(node: Any) -> dict[str, Any] | None:
    if isinstance(node, list):
        for n in node:
            found = _find_recipe(n)
            if found:
                return found
        return None
    if not isinstance(node, dict):
        return None
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    if "Recipe" in types:
        return node
    for key in ("@graph", "mainEntity", "itemListElement"):
        if key in node:
            found = _find_recipe(node[key])
            if found:
                return found
    return None


def _text(value: Any) -> str:
    if isinstance(value, str):
        return html.unescape(re.sub(r"<[^>]+>", " ", value)).strip()
    if isinstance(value, dict):
        return _text(value.get("text") or value.get("name") or "")
    if isinstance(value, list):
        return "\n".join(t for t in (_text(v) for v in value) if t)
    return ""


def _steps(value: Any) -> str:
    if isinstance(value, str):
        return _text(value)
    out: list[str] = []
    for v in value if isinstance(value, list) else [value]:
        if isinstance(v, dict) and v.get("@type") == "HowToSection":
            out.extend(_steps(v.get("itemListElement", [])).splitlines())
        else:
            t = _text(v)
            if t:
                out.append(t)
    return "\n".join(f"{i}. {s}" if not re.match(r"^\d+\.", s) else s for i, s in enumerate(out, 1))


def _servings(value: Any) -> int:
    if isinstance(value, list):
        value = value[0] if value else None
    m = re.search(r"\d+", str(value or ""))
    return int(m.group()) if m else 4


def _image(value: Any) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("url")
    return str(value) if value else None


def _keywords(node: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for key in ("recipeCuisine", "recipeCategory", "keywords"):
        v = node.get(key)
        if isinstance(v, str):
            tags.extend(v.split(","))
        elif isinstance(v, list):
            tags.extend(str(x) for x in v)
    clean = [t.strip().lower() for t in tags if 0 < len(t.strip()) <= 24]
    return list(dict.fromkeys(clean))[:8]


def from_html(page: str, url: str | None = None) -> Recipe:
    blocks = re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I)
    for block in blocks:
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        node = _find_recipe(data)
        if not node:
            continue
        lines = [_text(x) for x in node.get("recipeIngredient") or node.get("ingredients") or []]
        lines = [x for x in lines if x]
        if not lines:
            continue
        prep = minutes(node.get("prepTime"))
        cook = minutes(node.get("cookTime"))
        total = minutes(node.get("totalTime"))
        if prep is None and cook is None and total:
            prep, cook = min(15, total), max(total - 15, 0)
        return Recipe(
            name=_text(node.get("name")) or "Imported recipe",
            ingredients=lines,
            servings=_servings(node.get("recipeYield")),
            prep_minutes=prep if prep is not None else 15,
            cook_minutes=cook if cook is not None else 20,
            tags=_keywords(node),
            instructions=_steps(node.get("recipeInstructions") or ""),
            source_url=url,
            image_url=_image(node.get("image")),
        )
    raise ValueError("That page doesn't publish recipe data the planner can read.")


def import_url(db: DB, url: str, timeout_s: float = 15.0) -> dict[str, Any]:
    headers = {"User-Agent": "Mozilla/5.0 (meal-planner; personal use)"}
    with httpx.Client(timeout=timeout_s, follow_redirects=True, headers=headers) as client:
        resp = client.get(url)
        resp.raise_for_status()
    recipe = from_html(resp.text, url)
    rid = save(db, recipe)
    db.log("import", url=url, recipe_id=rid)
    found = get(db, rid)
    assert found is not None
    return found
