import datetime as dt

from meals import keep, shopping
from meals.keep import ListItem
from tests.conftest import MONDAY


def test_list_adds_up_and_skips_pantry(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    week = p.plan(MONDAY)
    items = {i["item"]: i for i in week["shopping"]["items"]}
    assert "salt" not in items and "olive oil" not in items
    assert week["shopping"]["count"] == len(items)
    garlic = items.get("garlic")
    if garlic and len(garlic["for"]) > 1:
        assert "clove" in garlic["amount"]
    stores = [g["store"] for g in week["shopping"]["by_store"]]
    assert stores[-1] == "Anywhere"


def test_keep_text() -> None:
    row = {
        "item": "chicken thigh",
        "amount": "3 lb",
        "store": "Safeway",
        "deal": {"price_text": "$3.99/lb"},
    }
    assert shopping.keep_text(row, "🍽") == "Chicken thigh · 3 lb · Safeway $3.99/lb 🍽"


def test_keep_diff_only_touches_its_own_items() -> None:
    existing = [
        ListItem("1", "Milk", False),  # typed by a person
        ListItem("2", "chicken thighs", False),  # already there, typed by a person
        ListItem("3", "Old thing · 1 lb 🍽", False),  # from last week's plan
        ListItem("4", "Bought already 🍽", True),  # ticked: leave it
        ListItem("5", "Garlic · 3 clove 🍽", False),  # still wanted
    ]
    wanted = [
        ("chicken thigh", "Chicken thigh · 3 lb 🍽"),
        ("garlic", "Garlic · 3 clove 🍽"),
        ("lime", "Lime · 2 🍽"),
    ]
    plan = keep.diff(wanted, existing, "🍽")
    assert plan.add == ["Lime · 2 🍽"]
    assert [i.id for i in plan.remove] == ["3"]
    assert plan.already == ["chicken thigh"]


def test_sync_without_sign_in_explains() -> None:
    import pytest

    with pytest.raises(keep.KeepError, match="keep-auth"):
        keep.sync([], None, None, "Shopping list", "🍽", __import__("pathlib").Path("x"))


def _plan_with(make_planner):  # type: ignore[no-untyped-def]
    p = make_planner()
    week = p.plan(MONDAY)
    return p, week["shopping"]


def test_pantry_staples_are_listed_as_had(make_planner) -> None:  # type: ignore[no-untyped-def]
    _, sh = _plan_with(make_planner)
    had = {i["item"]: i for i in sh["have"]}
    assert had and all(i["staple"] and i["have"] for i in had.values())
    assert not any(i["have"] for i in sh["items"])
    assert sh["have_count"] == len(sh["have"])


def test_tick_off_an_item_you_have(make_planner) -> None:  # type: ignore[no-untyped-def]
    p, sh = _plan_with(make_planner)
    item = sh["items"][0]["item"]
    count = sh["count"]

    week = p.mark_have(item, True, MONDAY)
    assert week["marked"] == item
    assert item not in [i["item"] for i in week["shopping"]["items"]]
    assert item in [i["item"] for i in week["shopping"]["have"]]
    assert week["shopping"]["count"] == count - 1
    # Only that week: the next week doesn't inherit it.
    assert p._marks(MONDAY + dt.timedelta(days=7)) == {}

    week = p.mark_have(item, False, MONDAY)
    assert item in [i["item"] for i in week["shopping"]["items"]]


def test_have_matches_loose_names_and_always(make_planner) -> None:  # type: ignore[no-untyped-def]
    p, sh = _plan_with(make_planner)
    item = next(i["item"] for i in sh["items"] if len(i["item"].split()) == 1)
    week = p.mark_have(item.upper() + "S", True, MONDAY, always=True)
    assert week["marked"] == item
    assert p._marks(MONDAY + dt.timedelta(days=14)) == {item: True}


def test_out_of_a_staple_puts_it_on_the_list(make_planner) -> None:  # type: ignore[no-untyped-def]
    p, sh = _plan_with(make_planner)
    staple = sh["have"][0]["item"]
    week = p.mark_have(staple, False, MONDAY)
    row = next(i for i in week["shopping"]["items"] if i["item"] == staple)
    assert row["staple"] and not row["have"]


def test_every_store_with_a_sale_is_shown(make_planner) -> None:  # type: ignore[no-untyped-def]
    p, sh = _plan_with(make_planner)
    item = sh["items"][0]["item"]
    p.add_deal("Safeway", item.title(), 4.99, None, "")
    p.add_deal("Co-op", item.title() + " Value Pack", 3.49, None, "")
    p.add_deal("Co-op", item.title() + " Family Size", 3.99, None, "")
    row = next(i for i in p.week(MONDAY)["shopping"]["items"] if i["item"] == item)
    assert [s["store"] for s in row["sales"]] == ["Co-op", "Safeway"]
    assert row["store"] == "Co-op" and row["deal"]["price_text"] == "$3.49"
    text = shopping.keep_text(row, "🍽")
    assert "Co-op $3.49, also Safeway $4.99 🍽" in text


def test_keep_sync_leaves_off_what_you_have(make_planner, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    p, sh = _plan_with(make_planner)
    item = sh["items"][0]["item"]
    p.mark_have(item, True, MONDAY)
    seen: dict[str, list[tuple[str, str]]] = {}

    def fake_sync(wanted, *a, **k):  # type: ignore[no-untyped-def]
        seen["wanted"] = wanted
        return {"add": [], "remove": [], "already_on_list": [], "link": "x"}

    monkeypatch.setattr(keep, "sync", fake_sync)
    r = p.sync_keep(MONDAY, dry_run=True)
    assert item not in [w[0] for w in seen["wanted"]]
    assert r["have"] == [item]


def test_keep_diff_takes_off_an_item_once_you_have_it() -> None:
    existing = [ListItem("1", "Lime · 2 🍽", False), ListItem("2", "Garlic · 3 clove 🍽", False)]
    plan = keep.diff([("garlic", "Garlic · 3 clove 🍽")], existing, "🍽")
    assert [i.id for i in plan.remove] == ["1"] and plan.add == []


def test_have_item_tool_and_list_text(make_planner, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from meals import mcp_server

    p, sh = _plan_with(make_planner)
    monkeypatch.setattr(mcp_server, "_planner", p)
    monkeypatch.setattr(p, "upcoming_week", lambda: MONDAY)
    item = sh["items"][0]["item"]
    p.add_deal("Safeway", item.title(), 2.0, None, "")
    out = mcp_server.have_item(item)
    assert out.startswith(f"Off the list this week: {item}.")
    text = mcp_server.shopping_list(str(MONDAY))
    assert f"Already have (not on the list): {item}" in text
    out = mcp_server.have_item(item, have=False)
    assert "Back on the list" in out
    assert "(on sale: Safeway $2.00)" in mcp_server.shopping_list(str(MONDAY))


def test_api_have(make_planner) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from meals.api import create_app

    p, sh = _plan_with(make_planner)
    c = TestClient(create_app(planner=p, settings=p.settings))
    item = sh["items"][0]["item"]
    body = {"item": item, "week_start": str(MONDAY)}
    week = c.post("/api/shopping/have", json=body).json()
    assert item in [i["item"] for i in week["shopping"]["have"]]
    dash = c.get("/api/dashboard").json()
    assert "have" in dash["shopping"]
