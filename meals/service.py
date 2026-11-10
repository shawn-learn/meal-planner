"""The planner's use cases, shared by the web page, the HTTP API, the CLI and the MCP tools,
so they all behave the same."""

from __future__ import annotations

import datetime as _dt
from collections import Counter
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo

from meals import deals as deal_mod
from meals import keep, learn, planner, schedule, shopping
from meals import recipes as recipe_mod
from meals.config import Household, Settings, load_household, secret
from meals.db import DB
from meals.planner import Choice
from meals.schedule import Evening

EveningsLoader = Callable[[Household, _dt.date], dict[_dt.date, list[Evening]]]


class Planner:
    def __init__(
        self,
        settings: Settings,
        db: DB | None = None,
        household: Household | None = None,
        evenings_loader: EveningsLoader | None = None,
        clock: Callable[[], _dt.datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.household = household or load_household(settings.household_file)
        self.db = db or DB(settings.db_path)
        self.tz = ZoneInfo(self.household.timezone)
        self._evenings_loader = evenings_loader
        self._clock = clock
        recipe_mod.seed(self.db)

    # ── Time ────────────────────────────────────────────────────────────────

    def now(self) -> _dt.datetime:
        return self._clock() if self._clock else _dt.datetime.now(self.tz)

    def today(self) -> _dt.date:
        return self.now().date()

    def week_for(self, day: _dt.date | None = None) -> _dt.date:
        return planner.week_start(day or self.today())

    def upcoming_week(self) -> _dt.date:
        """From Friday on, "the plan" means next week's."""
        today = self.today()
        start = self.week_for(today)
        return start + _dt.timedelta(days=7) if today.weekday() >= 4 else start

    def evenings(self, start: _dt.date) -> dict[_dt.date, list[Evening]]:
        if self._evenings_loader:
            return self._evenings_loader(self.household, start)
        return schedule.week_evenings(
            self.household, start, 7, self.settings.data_dir / "calendars"
        )

    # ── Plans ───────────────────────────────────────────────────────────────

    def plan(self, start: _dt.date | None = None, keep_locked: bool = True) -> dict[str, Any]:
        start = start or self.upcoming_week()
        planner.plan_week(
            self.db, self.household, start, self.evenings(start), keep_locked, self.today()
        )
        return self.week(start)

    def week(self, start: _dt.date | None = None) -> dict[str, Any]:
        start = start or self.upcoming_week()
        choices = planner.load_choices(self.db, start)
        current = deal_mod.current(self.db, deal_mod.shop_day(start, self.today()))
        lst = shopping.build(choices, self.household, current)
        cooks = Counter(c.cook for c in choices if c.cook and c.kind == "cook")
        plan_row = self.db.one("SELECT * FROM plans WHERE week_start = ?", start.isoformat())
        return {
            "today": self.today().isoformat(),
            "week_start": start.isoformat(),
            "week_end": (start + _dt.timedelta(days=6)).isoformat(),
            "planned": bool(choices),
            "updated_at": plan_row["updated_at"] if plan_row else None,
            "meals": [self._meal(c) for c in choices],
            "cooks": [{"name": n, "nights": k} for n, k in cooks.most_common()],
            "shopping": lst,
            "deals": {
                "count": len(current),
                "stores": sorted({d["store"] for d in current}),
                "last_checked": self._last_deals_check(),
            },
        }

    def _meal(self, c: Choice) -> dict[str, Any]:
        r = c.recipe
        return {
            "day": c.day.isoformat(),
            "weekday": c.day.strftime("%A"),
            "kind": c.kind,
            "cook": c.cook,
            "start_by": c.start_by.strftime("%H:%M") if c.start_by else None,
            "free_minutes": c.free_minutes,
            "locked": c.locked,
            "reasons": [x.as_dict() for x in c.reasons],
            "recipe": (
                {
                    "id": r["id"],
                    "name": r["name"],
                    "total_minutes": r["total_minutes"],
                    "hands_on": r["hands_on"],
                    "tags": r["tags"],
                    "protein": r["protein"],
                    "image_url": r["image_url"],
                    "source_url": r["source_url"],
                    "rating": r["ratings"]["average"],
                }
                if r
                else None
            ),
        }

    def _last_deals_check(self) -> str | None:
        row = self.db.one("SELECT at FROM events WHERE kind = 'deals' ORDER BY id DESC LIMIT 1")
        return row["at"] if row else None

    def swap(self, day: _dt.date, recipe_id: int | None = None) -> dict[str, Any]:
        start = self.week_for(day)
        if not planner.load_choices(self.db, start):
            raise ValueError("That week isn't planned yet.")
        planner.swap(
            self.db, self.household, start, day, self.evenings(start), recipe_id, self.today()
        )
        return self.week(start)

    def lock(self, day: _dt.date, locked: bool) -> dict[str, Any]:
        start = self.week_for(day)
        planner.set_locked(self.db, start, day, locked)
        return self.week(start)

    # ── Taste ───────────────────────────────────────────────────────────────

    def rate(
        self,
        recipe_id: int,
        rating: int,
        who: str | None = None,
        note: str | None = None,
        served_on: str | None = None,
    ) -> dict[str, Any]:
        recipe = recipe_mod.get(self.db, recipe_id)
        if recipe is None:
            raise ValueError("No such recipe.")
        learn.rate(self.db, recipe, rating, who, note, served_on)
        updated = recipe_mod.get(self.db, recipe_id)
        assert updated is not None
        return updated

    def to_rate(self) -> list[dict[str, Any]]:
        """Dinners from the last week that nobody has rated yet."""
        today = self.today()
        rows = self.db.all(
            """SELECT pm.day, r.id, r.name FROM plan_meals pm JOIN recipes r ON r.id = pm.recipe_id
               WHERE pm.kind = 'cook' AND pm.day < ? AND pm.day >= ?
               AND NOT EXISTS (SELECT 1 FROM ratings x WHERE x.recipe_id = r.id
                               AND x.served_on = pm.day)
               ORDER BY pm.day DESC""",
            today.isoformat(),
            (today - _dt.timedelta(days=8)).isoformat(),
        )
        return rows

    def preferences(self) -> dict[str, Any]:
        return learn.summary(self.db)

    # ── Recipes ─────────────────────────────────────────────────────────────

    def recipes(self) -> list[dict[str, Any]]:
        return recipe_mod.list_all(self.db)

    def recipe(self, recipe_id: int) -> dict[str, Any] | None:
        return recipe_mod.get(self.db, recipe_id)

    def import_recipe(self, url: str) -> dict[str, Any]:
        return recipe_mod.import_url(self.db, url, self.settings.http_timeout_s)

    def add_recipe(self, data: dict[str, Any]) -> dict[str, Any]:
        rid = recipe_mod.save(self.db, recipe_mod.Recipe(**data))
        found = recipe_mod.get(self.db, rid)
        assert found is not None
        return found

    def retire_recipe(self, recipe_id: int) -> None:
        recipe_mod.set_active(self.db, recipe_id, False)

    # ── Deals ───────────────────────────────────────────────────────────────

    async def refresh_deals(self) -> dict[str, Any]:
        return await deal_mod.refresh(
            self.db, self.household, self.today(), self.settings.http_timeout_s
        )

    def deals(self, query: str | None = None) -> list[dict[str, Any]]:
        rows = deal_mod.current(self.db, self.today())
        if query:
            from meals import ingredients as ing

            q = ing.normalize(query)
            rows = [d for d in rows if ing.matches(q, d["name"])]
        return rows

    def add_deal(
        self, store: str, name: str, price: float | None, valid_to: _dt.date | None, note: str
    ) -> None:
        deal_mod.add_manual(self.db, store, name, price, valid_to, note)

    # ── Keep ────────────────────────────────────────────────────────────────

    def sync_keep(self, start: _dt.date | None = None, dry_run: bool = False) -> dict[str, Any]:
        start = start or self.upcoming_week()
        lst = self.week(start)["shopping"]
        marker = self.household.keep_marker
        wanted = [(row["item"], shopping.keep_text(row, marker)) for row in lst["items"]]
        s = self.settings
        result = keep.sync(
            wanted,
            secret(s.keep_email, "keep-email"),
            secret(s.keep_master_token, "keep"),
            self.household.keep_list_title,
            marker,
            s.keep_state,
            dry_run,
        )
        if not dry_run:
            self.db.log("keep", added=len(result["add"]), removed=len(result["remove"]))
        return result

    # ── For Daily Dashboard ─────────────────────────────────────────────────

    def dashboard(self) -> dict[str, Any]:
        """Small and stable: what Daily Dashboard's Meals card shows."""
        today = self.today()
        start = self.week_for(today)
        week = self.week(start)
        by_day = {m["day"]: m for m in week["meals"]}
        tonight = by_day.get(today.isoformat())
        tomorrow = by_day.get((today + _dt.timedelta(days=1)).isoformat())

        def brief(m: dict[str, Any] | None) -> dict[str, Any] | None:
            if not m:
                return None
            r = m["recipe"]
            return {
                "day": m["day"],
                "kind": m["kind"],
                "name": r["name"] if r else ("Night off" if m["kind"] == "skip" else None),
                "cook": m["cook"],
                "start_by": m["start_by"],
                "minutes": r["total_minutes"] if r else None,
                "why": m["reasons"][0]["text"] if m["reasons"] else None,
                "recipe_id": r["id"] if r else None,
            }

        deals_used = [
            {"item": i["item"], "store": i["store"], "price_text": i["deal"]["price_text"]}
            for i in week["shopping"]["items"]
            if i["deal"]
        ]
        return {
            "date": today.isoformat(),
            "planned": week["planned"],
            "tonight": brief(tonight),
            "tomorrow": brief(tomorrow),
            "week": [
                {
                    "day": m["day"],
                    "name": m["recipe"]["name"] if m["recipe"] else None,
                    "kind": m["kind"],
                    "cook": m["cook"],
                }
                for m in week["meals"]
            ],
            "shopping": {
                "count": week["shopping"]["count"],
                "on_sale": week["shopping"]["on_sale"],
                "estimated_savings": week["shopping"]["estimated_savings"],
            },
            "deals": deals_used[:5],
            "to_rate": self.to_rate()[:3],
            "link": f"http://{self.settings.host}:{self.settings.port}/",
        }

    # ── The weekly job ──────────────────────────────────────────────────────

    async def weekly(self, sync: bool = True) -> dict[str, Any]:
        """Collect deals, plan the upcoming week, put the list on Keep. Run on a schedule."""
        out: dict[str, Any] = {"deals": await self.refresh_deals()}
        start = self.upcoming_week()
        out["week"] = self.plan(start)
        if sync:
            try:
                out["keep"] = self.sync_keep(start)
            except keep.KeepError as exc:
                out["keep"] = {"error": str(exc)}
        return out
