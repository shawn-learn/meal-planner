"""The week's dinners.

For each night the planner picks who cooks (whoever has the most time before dinner, shared
out fairly), then the recipe that scores best for that night:

* **fits** the cook's time (hands-on and total; slow-cooker and make-ahead dishes can be
  started earlier in the day),
* **deals**: key ingredients on sale this week at your stores,
* **taste**: ratings and what it has learned you like,
* **variety**: not the same protein twice in a row, not something you had last week.

Every choice carries plain-language reasons, and the whole thing is ordinary code: the same
inputs give the same plan, it costs nothing to run, and it never wanders off topic.
"""

from __future__ import annotations

import datetime as _dt
import json
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from meals import deals as deal_mod
from meals import ingredients as ing
from meals import learn
from meals import recipes as recipe_mod
from meals.config import Household
from meals.db import DB
from meals.schedule import Evening

DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TIGHT_MINUTES = 20
SLOW_TAGS = {"slow-cooker", "make-ahead", "instant-pot"}


def week_start(day: _dt.date) -> _dt.date:
    """Plans run Monday to Sunday."""
    return day - _dt.timedelta(days=day.weekday())


@dataclass
class Reason:
    kind: str  # deal | taste | time | cook | variety | leftovers | new | note
    text: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "text": self.text}


@dataclass
class Choice:
    day: _dt.date
    kind: str  # cook | leftovers | skip
    recipe: dict[str, Any] | None = None
    cook: str | None = None
    free_minutes: int | None = None
    start_by: _dt.time | None = None
    reasons: list[Reason] = field(default_factory=list)
    score: float = 0.0
    locked: bool = False


@dataclass
class Context:
    household: Household
    weights: dict[str, float]
    deals: list[dict[str, Any]]
    last_served: dict[int, _dt.date]
    rng: random.Random
    shop: _dt.date = _dt.date.min
    # Once a few dinners are rated, "new" becomes worth pointing out.
    has_history: bool = False


# ── Scoring ─────────────────────────────────────────────────────────────────────


def _uses_avoided(recipe: dict[str, Any], avoid: list[str]) -> bool:
    if not avoid:
        return False
    items = " ".join(i["item"] for i in recipe["ingredients"])
    words = set(items.split())
    return any(set(ing.normalize(a).split()) <= words for a in avoid if ing.normalize(a))


def deal_score(
    recipe: dict[str, Any], ctx: Context, day: _dt.date | None = None
) -> tuple[float, list[Reason], list[dict[str, Any]]]:
    items = [
        i["item"]
        for i in recipe["ingredients"]
        if not ing.is_pantry(i["item"], ctx.household.pantry)
    ]
    deals = deal_mod.for_dinner(ctx.deals, day, ctx.shop) if day else ctx.deals
    best = deal_mod.best_by_item(items, deals)
    score = 0.0
    reasons: list[Reason] = []
    protein = recipe.get("protein")
    ordered = sorted(best.items(), key=lambda kv: protein is None or protein not in kv[0])
    for item, d in ordered:
        is_protein = bool(protein and protein in item.split())
        score += 0.7 if is_protein else 0.25
        if d.get("savings"):
            score += min(d["savings"] / 4, 0.5)
        if len(reasons) < 2:
            reasons.append(Reason("deal", f"{item.capitalize()} {d['price_text']} at {d['store']}"))
    return min(score, 1.8), reasons, list(best.values())


def score_recipe(
    recipe: dict[str, Any],
    day: _dt.date,
    minutes: int,
    week: list[Choice],
    ctx: Context,
) -> tuple[float, list[Reason]] | None:
    """None when the recipe can't be made tonight."""
    if _uses_avoided(recipe, ctx.household.avoid):
        return None
    slow = bool(SLOW_TAGS & set(recipe["tags"]))
    hands_on = recipe["hands_on"]
    total = recipe["total_minutes"]
    if hands_on > minutes:
        return None
    if total > minutes + 10 and not slow:
        return None
    if any(c.recipe and c.recipe["id"] == recipe["id"] for c in week):
        return None

    reasons: list[Reason] = []
    taste, taste_reasons = learn.recipe_preference(recipe, ctx.weights)
    reasons += [Reason("taste", t) for t in taste_reasons]
    deal, deal_reasons, _ = deal_score(recipe, ctx, day)
    reasons = deal_reasons + reasons

    variety = 0.0
    protein = recipe.get("protein")
    cooked = [c for c in week if c.recipe]
    if protein:
        same = sum(1 for c in cooked if c.recipe and c.recipe.get("protein") == protein)
        variety -= 0.6 * same
        prev = next((c for c in reversed(cooked) if c.day < day), None)
        if prev and prev.recipe and prev.recipe.get("protein") == protein:
            variety -= 0.6
    tag_counts = Counter(t for c in cooked if c.recipe for t in c.recipe["tags"])
    variety -= 0.15 * sum(tag_counts[t] for t in recipe["tags"] if t not in {"quick", "easy"})

    novelty = 0.0
    last = ctx.last_served.get(recipe["id"])
    if last:
        ago = (day - last).days
        if ago < 10:
            novelty -= 1.2
        elif ago < 21:
            novelty -= 0.4
    elif recipe["ratings"]["count"] == 0 and ctx.has_history:
        reasons.append(Reason("new", "Something new to try"))

    # A "use up the leftovers" recipe only makes sense after a big-batch dinner.
    if "leftovers" in recipe["tags"]:
        made_extra = any(c.recipe and c.recipe["makes_leftovers"] and c.day < day for c in week)
        if not made_extra:
            return None

    # Fit: a quick dish on a busy night is good; a long one on a free night is fine too.
    fit = 0.0
    if minutes < 45 and total <= 30:
        fit += 0.3
    if slow and total > minutes:
        reasons.append(Reason("time", "Start it in the morning; it cooks itself"))
    if recipe["makes_leftovers"]:
        fit += 0.1

    jitter = ctx.rng.uniform(0, 0.25)
    return taste + deal + variety + novelty + fit + jitter, reasons


# ── Cooks ───────────────────────────────────────────────────────────────────────


def pick_cook(
    evenings: list[Evening], household: Household, counts: Counter[str]
) -> Evening | None:
    caps = {m.name: m.max_minutes for m in household.members}
    usable = [e for e in evenings if e.free_minutes >= TIGHT_MINUTES]
    if not usable:
        return max(evenings, key=lambda e: e.free_minutes, default=None)
    # Most time wins, but each night already cooked counts against you (shares the load).
    return max(
        usable,
        key=lambda e: (
            min(e.free_minutes, caps.get(e.member, 60)) - 25 * counts[e.member],
            e.member,
        ),
    )


def _fmt(t: _dt.time) -> str:
    # Not "%-I": Windows' strftime doesn't support it.
    return t.strftime("%I:%M %p").lstrip("0").lower()


def _start_by(household: Household, day: _dt.date, minutes: int) -> _dt.time:
    dinner = _dt.datetime.combine(day, household.dinner_time)
    start = dinner - _dt.timedelta(minutes=minutes)
    return start.replace(minute=start.minute - start.minute % 5).time()


# ── The plan ────────────────────────────────────────────────────────────────────


def _last_served(db: DB, before: _dt.date) -> dict[int, _dt.date]:
    rows = db.all(
        "SELECT recipe_id, MAX(day) AS day FROM plan_meals WHERE recipe_id IS NOT NULL "
        "AND kind = 'cook' AND day < ? GROUP BY recipe_id",
        before.isoformat(),
    )
    return {r["recipe_id"]: _dt.date.fromisoformat(r["day"]) for r in rows}


def build_context(
    db: DB, household: Household, start: _dt.date, today: _dt.date | None = None
) -> Context:
    shop = deal_mod.shop_day(start, today or start)
    return Context(
        household=household,
        weights=learn.weights(db),
        deals=deal_mod.current(db, shop),
        shop=shop,
        last_served=_last_served(db, start),
        rng=random.Random(start.toordinal()),
        has_history=bool(db.one("SELECT 1 AS x FROM ratings LIMIT 1 OFFSET 4")),
    )


def choose(
    day: _dt.date,
    evenings: list[Evening],
    candidates: list[dict[str, Any]],
    week: list[Choice],
    counts: Counter[str],
    ctx: Context,
    exclude: set[int] | None = None,
) -> Choice:
    household = ctx.household
    if DAY_KEYS[day.weekday()] in household.skip_days:
        return Choice(day, "skip", reasons=[Reason("note", "Night off (set in planner.toml)")])

    ev = pick_cook(evenings, household, counts) if evenings else None
    cap = {m.name: m.max_minutes for m in household.members}
    minutes = min(ev.free_minutes, cap.get(ev.member, 60)) if ev else 60
    cook = ev.member if ev else None

    # A tight night after a big batch: eat the leftovers.
    prev = max((c for c in week if c.day < day), key=lambda c: c.day, default=None)
    if prev and prev.day != day - _dt.timedelta(days=1):
        prev = None
    if (
        minutes < TIGHT_MINUTES
        and household.leftovers_ok
        and prev
        and prev.recipe
        and prev.recipe["makes_leftovers"]
    ):
        return Choice(
            day,
            "leftovers",
            recipe=prev.recipe,
            cook=None,
            free_minutes=minutes,
            reasons=[
                Reason("leftovers", f"Leftover {prev.recipe['name']}"),
                Reason("time", _busy_text(evenings)),
            ],
        )

    scored: list[tuple[float, dict[str, Any], list[Reason]]] = []
    for r in candidates:
        if exclude and r["id"] in exclude:
            continue
        result = score_recipe(r, day, max(minutes, TIGHT_MINUTES), week, ctx)
        if result:
            scored.append((result[0], r, result[1]))
    if not scored:  # nothing fits: the quickest thing there is
        quick = sorted(
            (r for r in candidates if not (exclude and r["id"] in exclude)),
            key=lambda r: r["hands_on"],
        )
        if not quick:
            return Choice(day, "skip", reasons=[Reason("note", "No recipes yet")])
        scored = [(0.0, quick[0], [Reason("time", "Tight night, so the quickest option")])]
    scored.sort(key=lambda s: (-s[0], s[1]["name"]))
    best_score, recipe, reasons = scored[0]

    if ev and ev.free_minutes >= TIGHT_MINUTES:
        when = _fmt(ev.free_from) if ev.free_from else None
        why = f"{cook} is free from {when}" if when else f"{cook} has the evening"
        if ev.because:
            why += f" (after {ev.because})"
        reasons.append(Reason("cook", why))
    elif evenings:
        reasons.append(Reason("time", _busy_text(evenings)))
        cook = cook if ev and ev.free_minutes > 0 else None
    slow = bool(SLOW_TAGS & set(recipe["tags"]))
    need = recipe["hands_on"] if slow else recipe["total_minutes"]
    if cook:
        counts[cook] += 1
    return Choice(
        day,
        "cook",
        recipe=recipe,
        cook=cook,
        free_minutes=ev.free_minutes if ev else None,
        start_by=_start_by(household, day, need),
        reasons=reasons[:4],
        score=best_score,
    )


def _busy_text(evenings: list[Evening]) -> str:
    busy = [f"{e.member} ({e.because})" if e.because else e.member for e in evenings]
    return "Busy night: " + ", ".join(busy) if busy else "Busy night"


def plan_week(
    db: DB,
    household: Household,
    start: _dt.date,
    evenings: dict[_dt.date, list[Evening]],
    keep_locked: bool = True,
    today: _dt.date | None = None,
) -> list[Choice]:
    ctx = build_context(db, household, start, today)
    candidates = recipe_mod.list_all(db)
    existing = {c.day: c for c in load_choices(db, start)} if keep_locked else {}
    week: list[Choice] = []
    counts: Counter[str] = Counter()
    for i in range(7):
        day = start + _dt.timedelta(days=i)
        old = existing.get(day)
        if old and old.locked:
            week.append(old)
            if old.cook:
                counts[old.cook] += 1
            continue
        week.append(choose(day, evenings.get(day, []), candidates, week, counts, ctx))
    save_week(db, start, week)
    db.log("plan", week_start=start.isoformat())
    return week


def swap(
    db: DB,
    household: Household,
    start: _dt.date,
    day: _dt.date,
    evenings: dict[_dt.date, list[Evening]],
    recipe_id: int | None = None,
    today: _dt.date | None = None,
) -> Choice:
    """Replace one night's dinner: with `recipe_id` if given, else the next best option."""
    week = load_choices(db, start)
    current = next((c for c in week if c.day == day), None)
    others = [c for c in week if c.day != day]
    ctx = build_context(db, household, start, today)
    if current and current.recipe and current.kind == "cook":
        learn.swapped_out(db, current.recipe)
    if recipe_id is not None:
        recipe = recipe_mod.get(db, recipe_id)
        if recipe is None:
            raise ValueError("No such recipe.")
        new = Choice(
            day,
            "cook",
            recipe=recipe,
            cook=current.cook if current else None,
            free_minutes=current.free_minutes if current else None,
            start_by=_start_by(household, day, recipe["total_minutes"]),
            reasons=[Reason("note", "Your pick")],
            locked=True,
        )
    else:
        exclude = {current.recipe["id"]} if current and current.recipe else set()
        counts: Counter[str] = Counter(c.cook for c in others if c.cook)
        new = choose(
            day, evenings.get(day, []), recipe_mod.list_all(db), others, counts, ctx, exclude
        )
    save_week(db, start, sorted(others + [new], key=lambda c: c.day))
    db.log("swap", day=day.isoformat())
    return new


def set_locked(db: DB, start: _dt.date, day: _dt.date, locked: bool) -> None:
    with db.tx() as c:
        c.execute(
            "UPDATE plan_meals SET locked = ? WHERE week_start = ? AND day = ?",
            (int(locked), start.isoformat(), day.isoformat()),
        )


# ── Persistence ─────────────────────────────────────────────────────────────────


def save_week(db: DB, start: _dt.date, week: list[Choice]) -> None:
    with db.tx() as c:
        c.execute(
            "INSERT INTO plans (week_start) VALUES (?) ON CONFLICT(week_start) "
            "DO UPDATE SET updated_at = datetime('now')",
            (start.isoformat(),),
        )
        c.execute("DELETE FROM plan_meals WHERE week_start = ?", (start.isoformat(),))
        for ch in week:
            c.execute(
                """INSERT INTO plan_meals (week_start, day, kind, recipe_id, cook, start_by,
                   free_minutes, reasons, locked) VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    start.isoformat(),
                    ch.day.isoformat(),
                    ch.kind,
                    ch.recipe["id"] if ch.recipe else None,
                    ch.cook,
                    ch.start_by.isoformat(timespec="minutes") if ch.start_by else None,
                    ch.free_minutes,
                    json.dumps([r.as_dict() for r in ch.reasons]),
                    int(ch.locked),
                ),
            )


def load_choices(db: DB, start: _dt.date) -> list[Choice]:
    rows = db.all("SELECT * FROM plan_meals WHERE week_start = ? ORDER BY day", start.isoformat())
    out: list[Choice] = []
    for r in rows:
        recipe = recipe_mod.get(db, r["recipe_id"]) if r["recipe_id"] else None
        out.append(
            Choice(
                day=_dt.date.fromisoformat(r["day"]),
                kind=r["kind"],
                recipe=recipe,
                cook=r["cook"],
                free_minutes=r["free_minutes"],
                start_by=_dt.time.fromisoformat(r["start_by"]) if r["start_by"] else None,
                reasons=[Reason(**x) for x in json.loads(r["reasons"])],
                locked=bool(r["locked"]),
            )
        )
    return out
