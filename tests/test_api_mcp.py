import asyncio

from fastapi.testclient import TestClient

from meals.api import create_app
from tests.conftest import MONDAY


def test_api_flow(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    c = TestClient(create_app(planner=p, settings=p.settings))
    assert c.get("/api/health").json()["recipes"] >= 25
    assert c.get("/api/week").json()["planned"] is False
    week = c.post("/api/week/plan", json={"week_start": str(MONDAY)}).json()
    assert len(week["meals"]) == 7
    rid = week["meals"][0]["recipe"]["id"]
    assert c.post("/api/ratings", json={"recipe_id": rid, "rating": 5}).status_code == 200
    assert c.post("/api/ratings", json={"recipe_id": rid, "rating": 9}).status_code == 422
    swapped = c.post(f"/api/days/{MONDAY}/swap", json={}).json()
    assert swapped["meals"][0]["recipe"]["id"] != rid
    locked = c.post(f"/api/days/{MONDAY}/lock", json={"locked": True}).json()
    assert locked["meals"][0]["locked"]
    assert c.post("/api/deals", json={"store": "Costco", "name": "Chicken Thighs"}).json()["ok"]
    assert c.get("/api/deals", params={"q": "chicken thigh"}).json()
    dash = c.get("/api/dashboard").json()
    assert dash["tonight"]["name"]
    assert c.post("/api/keep/sync", json={}).status_code == 409
    assert c.get("/api/recipes/99999").status_code == 404


def test_mcp_tools_are_few_and_named() -> None:
    from meals import mcp_server

    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert {"get_week", "plan_week", "swap_dinner", "rate_dinner", "send_list_to_keep"} <= names
    assert len(names) <= 14


def test_mcp_week_text(make_planner) -> None:  # type: ignore[no-untyped-def]
    from meals import mcp_server

    p = make_planner()
    text = mcp_server._week_text(p.plan(MONDAY))
    assert text.startswith("Week of 2026-11-09")
    assert text.count("\n- ") == 7


def test_demo_builds(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from meals import demo

    p = demo.build(tmp_path / "demo")
    assert p.week(p.week_for())["planned"]
    assert p.preferences()["favourites"]
