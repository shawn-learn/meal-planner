"""HTTP API and the web page. Local by default (127.0.0.1:8200), like Daily Dashboard."""

from __future__ import annotations

import datetime as _dt
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from meals import keep
from meals.config import Settings, get_settings
from meals.service import Planner


class PlanIn(BaseModel):
    week_start: _dt.date | None = None
    keep_locked: bool = True


class SwapIn(BaseModel):
    recipe_id: int | None = None


class LockIn(BaseModel):
    locked: bool = True


class RateIn(BaseModel):
    recipe_id: int
    rating: int = Field(ge=1, le=5)
    who: str | None = None
    note: str | None = None
    served_on: str | None = None


class ImportIn(BaseModel):
    url: str


class RecipeIn(BaseModel):
    name: str
    ingredients: list[str]
    servings: int = 4
    prep_minutes: int = 15
    cook_minutes: int = 20
    hands_on_minutes: int | None = None
    tags: list[str] = []
    instructions: str = ""
    source_url: str | None = None
    makes_leftovers: bool = False


class DealIn(BaseModel):
    store: str
    name: str
    price: float | None = None
    valid_to: _dt.date | None = None
    note: str = ""


class SyncIn(BaseModel):
    week_start: _dt.date | None = None
    dry_run: bool = False


def create_app(planner: Planner | None = None, settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Meal Planner", version="0.1.0")
    p = planner or Planner(settings)
    app.state.planner = p

    def bad(exc: Exception) -> HTTPException:
        return HTTPException(400, str(exc))

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "recipes": len(p.recipes()), "today": p.today().isoformat()}

    @app.get("/api/week")
    def week(start: _dt.date | None = None) -> dict[str, Any]:
        return p.week(p.week_for(start) if start else None)

    @app.post("/api/week/plan")
    def plan(body: PlanIn) -> dict[str, Any]:
        start = p.week_for(body.week_start) if body.week_start else None
        return p.plan(start, body.keep_locked)

    @app.post("/api/days/{day}/swap")
    def swap(day: _dt.date, body: SwapIn) -> dict[str, Any]:
        try:
            return p.swap(day, body.recipe_id)
        except ValueError as exc:
            raise bad(exc) from exc

    @app.post("/api/days/{day}/lock")
    def lock(day: _dt.date, body: LockIn) -> dict[str, Any]:
        return p.lock(day, body.locked)

    @app.post("/api/ratings")
    def rate(body: RateIn) -> dict[str, Any]:
        try:
            return p.rate(body.recipe_id, body.rating, body.who, body.note, body.served_on)
        except ValueError as exc:
            raise bad(exc) from exc

    @app.get("/api/ratings/pending")
    def to_rate() -> list[dict[str, Any]]:
        return p.to_rate()

    @app.get("/api/preferences")
    def prefs() -> dict[str, Any]:
        return p.preferences()

    @app.get("/api/recipes")
    def recipes() -> list[dict[str, Any]]:
        return p.recipes()

    @app.get("/api/recipes/{recipe_id}")
    def recipe(recipe_id: int) -> dict[str, Any]:
        found = p.recipe(recipe_id)
        if not found:
            raise HTTPException(404, "No such recipe.")
        return found

    @app.post("/api/recipes")
    def add_recipe(body: RecipeIn) -> dict[str, Any]:
        return p.add_recipe(body.model_dump())

    @app.post("/api/recipes/import")
    def import_recipe(body: ImportIn) -> dict[str, Any]:
        try:
            return p.import_recipe(body.url)
        except Exception as exc:
            raise bad(exc) from exc

    @app.delete("/api/recipes/{recipe_id}")
    def retire(recipe_id: int) -> dict[str, bool]:
        p.retire_recipe(recipe_id)
        return {"ok": True}

    @app.get("/api/deals")
    def deals(q: str | None = None) -> list[dict[str, Any]]:
        return p.deals(q)

    @app.post("/api/deals/refresh")
    async def refresh() -> dict[str, Any]:
        return await p.refresh_deals()

    @app.post("/api/deals")
    def add_deal(body: DealIn) -> dict[str, bool]:
        p.add_deal(body.store, body.name, body.price, body.valid_to, body.note)
        return {"ok": True}

    @app.post("/api/keep/sync")
    def sync(body: SyncIn) -> dict[str, Any]:
        start = p.week_for(body.week_start) if body.week_start else None
        try:
            return p.sync_keep(start, body.dry_run)
        except keep.KeepError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/dashboard")
    def dashboard() -> dict[str, Any]:
        return p.dashboard()

    web = settings.web_dir
    if web.exists():
        app.mount("/static", StaticFiles(directory=web), name="static")

        @app.get("/", include_in_schema=False)
        def index() -> FileResponse:
            return FileResponse(web / "index.html")

    return app
