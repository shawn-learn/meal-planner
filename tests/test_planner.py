import datetime as dt

from meals import deals, recipes
from meals.sources.flipp import Deal
from tests.conftest import MONDAY, at


def _deal(store: str, name: str, price: float, query: str) -> Deal:
    return Deal(
        store,
        name,
        price,
        f"${price}",
        price + 2,
        None,
        "2026-11-06",
        "2026-11-20",
        None,
        None,
        query,
    )


def test_plans_seven_dinners_with_reasons(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    week = p.plan(MONDAY)
    assert len(week["meals"]) == 7
    assert all(m["kind"] == "cook" for m in week["meals"])
    names = [m["recipe"]["name"] for m in week["meals"]]
    assert len(set(names)) == 7
    assert all(any(r["kind"] == "cook" for r in m["reasons"]) for m in week["meals"])
    # Nobody cooks every night.
    assert {c["name"] for c in week["cooks"]} == {"Alex", "Sam"}


def test_same_inputs_same_plan(make_planner) -> None:  # type: ignore[no-untyped-def]
    a = [m["recipe"]["name"] for m in make_planner().plan(MONDAY)["meals"]]
    b = [m["recipe"]["name"] for m in make_planner().plan(MONDAY)["meals"]]
    assert a == b


def test_busy_night_gets_a_quick_dinner(make_planner) -> None:  # type: ignore[no-untyped-def]
    tue = MONDAY + dt.timedelta(days=1)
    busy = {
        "Alex": [(at(tue, "08:00"), at(tue, "17:30"), "Work")],
        "Sam": [(at(tue, "16:00"), at(tue, "19:00"), "Hockey")],
    }
    week = make_planner(busy).plan(MONDAY)
    tuesday = week["meals"][1]
    assert tuesday["cook"] == "Alex"
    assert tuesday["recipe"]["hands_on"] <= 30
    assert any("Work" in r["text"] for r in tuesday["reasons"])


def test_deals_pull_recipes_in(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    deals.store_deals(
        p.db, [_deal("Calgary Co-op", "Atlantic Salmon Fillets", 7.99, "salmon fillet")]
    )
    week = p.plan(MONDAY)
    salmon = [m for m in week["meals"] if m["recipe"]["protein"] == "salmon"]
    assert salmon
    assert any(r["kind"] == "deal" and "Co-op" in r["text"] for r in salmon[0]["reasons"])
    row = next(i for i in week["shopping"]["items"] if i["item"] == "salmon fillet")
    assert row["store"] == "Calgary Co-op"


def test_avoid_list_is_respected(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner(avoid=["shrimp", "salmon"])
    for m in p.plan(MONDAY)["meals"]:
        r = recipes.get(p.db, m["recipe"]["id"])
        assert r is not None
        words = " ".join(i["item"] for i in r["ingredients"]).split()
        assert "shrimp" not in words and "salmon" not in words


def test_skip_days(make_planner) -> None:  # type: ignore[no-untyped-def]
    week = make_planner(skip_days=["fri"]).plan(MONDAY)
    assert week["meals"][4]["kind"] == "skip"


def test_leftovers_after_big_batch_on_a_tight_night(make_planner) -> None:  # type: ignore[no-untyped-def]
    wed = MONDAY + dt.timedelta(days=2)
    busy = {
        "Alex": [(at(wed, "08:00"), at(wed, "19:00"), "Conference")],
        "Sam": [(at(wed, "15:00"), at(wed, "19:00"), "Tournament")],
    }
    p = make_planner(busy)
    tue = MONDAY + dt.timedelta(days=1)
    chili = p.db.one("SELECT id FROM recipes WHERE name = 'Classic Beef Chili'")
    p.plan(MONDAY)
    p.swap(tue, chili["id"])
    week = p.plan(MONDAY)
    assert week["meals"][1]["recipe"]["name"] == "Classic Beef Chili"
    assert week["meals"][2]["kind"] == "leftovers"


def test_locked_dinners_survive_replanning(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    first = p.plan(MONDAY)
    thu = MONDAY + dt.timedelta(days=3)
    p.lock(thu, True)
    kept = first["meals"][3]["recipe"]["name"]
    p.rate(first["meals"][3]["recipe"]["id"], 1)  # even a bad rating doesn't move a kept one
    again = p.plan(MONDAY)
    assert again["meals"][3]["recipe"]["name"] == kept
    assert again["meals"][3]["locked"]


def test_swap_picks_something_else(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    week = p.plan(MONDAY)
    before = week["meals"][0]["recipe"]["name"]
    after = p.swap(MONDAY)["meals"][0]["recipe"]["name"]
    assert after != before
    assert after not in [m["recipe"]["name"] for m in week["meals"][1:]]


def test_ratings_steer_future_plans(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    fajitas = p.db.one("SELECT id FROM recipes WHERE name = 'Chicken Fajitas'")["id"]
    for _ in range(3):
        p.rate(fajitas, 5)
    week = p.plan(MONDAY + dt.timedelta(days=21))
    assert "Chicken Fajitas" in [m["recipe"]["name"] for m in week["meals"]]
    prefs = p.preferences()
    assert any(f["name"] == "Chicken Fajitas" for f in prefs["favourites"])


def test_recently_served_is_held_back(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    one = {m["recipe"]["name"] for m in p.plan(MONDAY)["meals"]}
    two = {m["recipe"]["name"] for m in p.plan(MONDAY + dt.timedelta(days=7))["meals"]}
    assert len(one & two) <= 1


def test_start_time_formats_on_every_platform() -> None:
    from meals.planner import _fmt

    assert _fmt(dt.time(16, 0)) == "4:00 pm"
    assert _fmt(dt.time(17, 30)) == "5:30 pm"
