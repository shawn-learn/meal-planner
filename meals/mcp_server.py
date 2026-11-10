"""MCP tools for Claude (Claude Desktop, Claude Code, Cowork).

Deliberately few, narrow tools that return short text. All the thinking about deals,
schedules and tastes happens in the planner, so a chat needs only a handful of small calls
and has nothing to drift off on. Run with ``uv run meals mcp`` (stdio).
"""

from __future__ import annotations

import datetime as _dt
from typing import Any

from mcp.server.mcpserver import MCPServer

from meals.config import get_settings
from meals.keep import KeepError
from meals.service import Planner

INSTRUCTIONS = """Meal Planner for one household. Use these tools only for dinner planning,
recipes, grocery deals and the shopping list. The planner already weighs calendars, deals at
the household's stores and learned tastes, so prefer its choices and explain them with the
reasons it gives; don't invent recipes, prices or schedules. Keep replies short."""

mcp = MCPServer("meal-planner", instructions=INSTRUCTIONS)
_planner: Planner | None = None


def planner() -> Planner:
    global _planner
    if _planner is None:
        _planner = Planner(get_settings())
    return _planner


def _week_text(week: dict[str, Any]) -> str:
    if not week["planned"]:
        return f"Week of {week['week_start']} isn't planned yet. Call plan_week."
    lines = [f"Week of {week['week_start']}:"]
    for m in week["meals"]:
        r = m["recipe"]
        day = _dt.date.fromisoformat(m["day"]).strftime("%a %b %d")
        if m["kind"] == "skip":
            lines.append(f"- {day}: night off")
            continue
        name = r["name"] if r else "?"
        if m["kind"] == "leftovers":
            name = f"leftovers ({name})"
        bits = [f"- {day}: {name} [recipe {r['id'] if r else '-'}]"]
        if m["cook"]:
            bits.append(f"cook {m['cook']}")
        if m["start_by"] and m["kind"] == "cook":
            bits.append(f"start {m['start_by']}")
        if m["locked"]:
            bits.append("kept")
        why = "; ".join(x["text"] for x in m["reasons"][:2])
        lines.append(", ".join(bits) + (f" — {why}" if why else ""))
    sh = week["shopping"]
    lines.append(
        f"Shopping: {sh['count']} items, {sh['on_sale']} on sale"
        + (f", ~${sh['estimated_savings']:.2f} saved" if sh["estimated_savings"] else "")
        + "."
    )
    return "\n".join(lines)


@mcp.tool()
def get_week(week_start: str | None = None) -> str:
    """The planned dinners (who cooks, when to start, why) and a shopping summary.
    week_start: any date in the week (YYYY-MM-DD); default is the upcoming week."""
    p = planner()
    start = p.week_for(_dt.date.fromisoformat(week_start)) if week_start else None
    return _week_text(p.week(start))


@mcp.tool()
def plan_week(week_start: str | None = None, keep_kept: bool = True) -> str:
    """(Re)plan a week's dinners from calendars, deals and tastes. Kept dinners stay unless
    keep_kept is false."""
    p = planner()
    start = p.week_for(_dt.date.fromisoformat(week_start)) if week_start else None
    return _week_text(p.plan(start, keep_kept))


@mcp.tool()
def swap_dinner(day: str, recipe_id: int | None = None) -> str:
    """Replace one night's dinner (YYYY-MM-DD) with the next best option, or with recipe_id."""
    try:
        return _week_text(planner().swap(_dt.date.fromisoformat(day), recipe_id))
    except ValueError as exc:
        return str(exc)


@mcp.tool()
def keep_dinner(day: str, keep: bool = True) -> str:
    """Keep (or stop keeping) a night's dinner so re-planning doesn't change it."""
    planner().lock(_dt.date.fromisoformat(day), keep)
    return f"{'Keeping' if keep else 'Not keeping'} {day}."


@mcp.tool()
def rate_dinner(recipe_id: int, stars: int, note: str | None = None, day: str | None = None) -> str:
    """Record how a dinner went, 1–5 stars. The planner learns from this."""
    try:
        r = planner().rate(recipe_id, stars, note=note, served_on=day)
    except ValueError as exc:
        return str(exc)
    avg, n = r["ratings"]["average"], r["ratings"]["count"]
    return f"Saved {stars}★ for {r['name']} (now {avg:.1f}★ over {n})."


@mcp.tool()
def find_recipes(query: str = "", max_minutes: int | None = None, limit: int = 12) -> str:
    """Search the household cookbook by name, tag or ingredient."""
    q = query.lower().strip()
    out = []
    for r in planner().recipes():
        hay = " ".join([r["name"].lower(), *r["tags"], *(i["item"] for i in r["ingredients"])])
        if q and q not in hay:
            continue
        if max_minutes and r["total_minutes"] > max_minutes:
            continue
        stars = f", {r['ratings']['average']:.1f}★" if r["ratings"]["count"] else ""
        out.append(f"- [{r['id']}] {r['name']} ({r['total_minutes']} min{stars})")
    return "\n".join(out[:limit]) or "No recipes match."


@mcp.tool()
def add_recipe_from_link(url: str) -> str:
    """Add a recipe from a web page that publishes recipe data (most recipe sites)."""
    try:
        r = planner().import_recipe(url)
    except Exception as exc:
        return f"Couldn't add it: {exc}"
    n = len(r["ingredients"])
    return f"Added [{r['id']}] {r['name']}: {n} ingredients, {r['total_minutes']} min."


@mcp.tool()
def deals(query: str = "", limit: int = 15) -> str:
    """This week's saved deals at the household's stores, optionally filtered."""
    rows = planner().deals(query or None)
    lines = [f"- {d['store']}: {d['name']} — {d['price_text']}" for d in rows[:limit]]
    return "\n".join(lines) or "No matching deals saved. Try check_flyers."


@mcp.tool()
async def check_flyers() -> str:
    """Search this week's flyers (Flipp) for everything the recipes use. Takes a minute."""
    r = await planner().refresh_deals()
    if not r.get("ok"):
        return str(r.get("error", "Couldn't check the flyers."))
    return f"Searched {r['searched']} items; {r['saved']} deals at your stores."


@mcp.tool()
def shopping_list(week_start: str | None = None) -> str:
    """The week's shopping list grouped by store, with deals."""
    p = planner()
    start = p.week_for(_dt.date.fromisoformat(week_start)) if week_start else None
    sh = p.week(start)["shopping"]
    lines: list[str] = []
    for g in sh["by_store"]:
        lines.append(f"{g['store']}:")
        for i in g["items"]:
            deal = f" ({i['deal']['price_text']})" if i["deal"] else ""
            amount = f" — {i['amount']}" if i["amount"] else ""
            lines.append(f"  - {i['item']}{amount}{deal}")
    return "\n".join(lines) or "Nothing to buy."


@mcp.tool()
def send_list_to_keep(dry_run: bool = False) -> str:
    """Put the upcoming week's list on the Google Keep shopping list (only 🍽 items change)."""
    try:
        r = planner().sync_keep(dry_run=dry_run)
    except KeepError as exc:
        return str(exc)
    verb = "Would add" if dry_run else "Added"
    return f"{verb} {len(r['add'])}, removed {len(r['remove'])} old items. {r['link']}"


@mcp.tool()
def tastes() -> str:
    """What the planner has learned the household likes and doesn't."""
    s = planner().preferences()

    def fmt(rows: list[dict[str, Any]]) -> str:
        return ", ".join(r["key"].split(":", 1)[1] for r in rows) or "nothing yet"

    fav = ", ".join(f"{f['name']} ({f['average']:.1f}★)" for f in s["favourites"]) or "none yet"
    return f"Likes: {fmt(s['likes'])}\nLess keen on: {fmt(s['dislikes'])}\nFavourites: {fav}"


def run() -> None:
    mcp.run()
