"""What the household likes, learned from ratings and swaps, kept as small weights.

Weights are keyed like ``recipe:12``, ``tag:mexican``, ``protein:salmon`` and stay between -2
and +2. A 5★ nudges the recipe up a lot and its tags and protein up a little; a 1★ does the
opposite; swapping a meal out is a gentle "not this week". Nothing here calls a model, and it
can always say why it thinks something.
"""

from __future__ import annotations

from typing import Any

from meals.db import DB

PRIOR_MEAN = 3.5
PRIOR_WEIGHT = 2.0
LIMIT = 2.0


def _bump(db: DB, key: str, delta: float) -> None:
    with db.tx() as c:
        c.execute(
            """INSERT INTO preferences (key, weight) VALUES (?, ?)
               ON CONFLICT(key) DO UPDATE SET
               weight = MAX(?, MIN(?, weight + excluded.weight)), updated_at = datetime('now')""",
            (key, max(-LIMIT, min(LIMIT, delta)), -LIMIT, LIMIT),
        )


def weights(db: DB) -> dict[str, float]:
    return {r["key"]: r["weight"] for r in db.all("SELECT key, weight FROM preferences")}


def rate(
    db: DB,
    recipe: dict[str, Any],
    rating: int,
    who: str | None = None,
    note: str | None = None,
    served_on: str | None = None,
) -> None:
    if not 1 <= rating <= 5:
        raise ValueError("Ratings are 1 to 5.")
    with db.tx() as c:
        c.execute(
            "INSERT INTO ratings (recipe_id, rating, who, note, served_on) VALUES (?,?,?,?,?)",
            (recipe["id"], rating, who, note, served_on),
        )
    delta = rating - 3
    _bump(db, f"recipe:{recipe['id']}", 0.3 * delta)
    for tag in recipe["tags"]:
        _bump(db, f"tag:{tag}", 0.08 * delta)
    if recipe.get("protein"):
        _bump(db, f"protein:{recipe['protein']}", 0.12 * delta)
    db.log("rate", recipe_id=recipe["id"], rating=rating, who=who)


def swapped_out(db: DB, recipe: dict[str, Any]) -> None:
    _bump(db, f"recipe:{recipe['id']}", -0.1)


def recipe_preference(recipe: dict[str, Any], w: dict[str, float]) -> tuple[float, list[str]]:
    """A score around 0 (unknown) from ratings and learned weights, with reasons."""
    reasons: list[str] = []
    n = recipe["ratings"]["count"]
    avg = recipe["ratings"]["average"]
    score = 0.0
    if n:
        mean = (avg * n + PRIOR_MEAN * PRIOR_WEIGHT) / (n + PRIOR_WEIGHT)
        score += (mean - 3.0) / 1.5
        if avg >= 4.5:
            reasons.append(f"A favourite ({avg:.1f}★, rated {n}×)")
        elif avg >= 4:
            reasons.append(f"You liked it ({avg:.1f}★)")
    else:
        score += 0.1  # a little curiosity for things not tried yet
    score += w.get(f"recipe:{recipe['id']}", 0.0)
    tag_score = sum(w.get(f"tag:{t}", 0.0) for t in recipe["tags"])
    score += tag_score
    liked_tags = [t for t in recipe["tags"] if w.get(f"tag:{t}", 0.0) >= 0.3]
    if liked_tags and not reasons:
        reasons.append(f"You've been enjoying {', '.join(liked_tags[:2])}")
    if recipe.get("protein"):
        score += w.get(f"protein:{recipe['protein']}", 0.0)
    return score, reasons


def summary(db: DB, limit: int = 6) -> dict[str, list[dict[str, Any]]]:
    rows = db.all("SELECT key, weight FROM preferences WHERE key NOT LIKE 'recipe:%'")
    rows.sort(key=lambda r: r["weight"], reverse=True)
    likes = [r for r in rows if r["weight"] > 0.05][:limit]
    dislikes = [r for r in reversed(rows) if r["weight"] < -0.05][:limit]
    fav = db.all(
        """SELECT r.id, r.name, AVG(x.rating) AS average, COUNT(*) AS count FROM ratings x
           JOIN recipes r ON r.id = x.recipe_id GROUP BY r.id HAVING AVG(x.rating) >= 4
           ORDER BY average DESC, count DESC LIMIT ?""",
        limit,
    )
    return {"likes": likes, "dislikes": dislikes, "favourites": fav}
