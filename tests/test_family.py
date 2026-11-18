"""The family profile and its allergies: never planned, whatever else the planner likes."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from meals import family
from meals.api import create_app
from meals.config import Member, load_household
from tests.conftest import MONDAY


def _hit(allergen: str, item: str) -> bool:
    return family.rule_for(allergen, ["X"]).hit(item)


@pytest.mark.parametrize(
    ("allergen", "item"),
    [
        ("dairy", "parmesan"),
        ("milk", "sour cream"),
        ("Lactose", "butter"),
        ("dairy", "caesar dressing"),
        ("egg", "mayonnaise"),
        ("eggs", "egg noodles"),
        ("gluten", "spaghetti"),
        ("wheat", "soy sauce"),
        ("gluten", "flour tortilla"),
        ("peanuts", "peanut butter"),
        ("tree nuts", "pine nuts"),
        ("tree nut", "cashew"),
        ("fish", "fish sauce"),
        ("fish", "salmon fillet"),
        ("shellfish", "shrimp"),
        ("shellfish", "oyster sauce"),
        ("sesame", "sesame oil"),
        ("sesame", "tahini"),
        ("soy", "tofu"),
        ("mustard", "dijon mustard"),
        ("mushrooms", "cremini mushroom"),
    ],
)
def test_allergen_is_found_in_ingredient(allergen: str, item: str) -> None:
    assert _hit(allergen, item)


@pytest.mark.parametrize(
    ("allergen", "item"),
    [
        ("dairy", "coconut milk"),
        ("dairy", "peanut butter"),
        ("dairy", "cream of tartar"),
        ("dairy", "swiss chard"),
        ("egg", "eggplant"),
        ("gluten", "corn tortilla"),
        ("gluten", "rice noodles"),
        ("gluten", "buckwheat"),
        ("peanut", "chicken thigh"),
        ("tree nuts", "nutmeg"),
        ("tree nuts", "coconut"),
        ("fish", "shellfish"),
        ("soy", "chickpea"),
    ],
)
def test_lookalikes_are_not_allergens(allergen: str, item: str) -> None:
    assert not _hit(allergen, item)


def test_names_are_canonical() -> None:
    assert family.canonical("Peanuts") == "peanut"
    assert family.canonical("milk") == "dairy"
    assert family.canonical("wheat") == "gluten"
    assert family.canonical("Kiwis") == "kiwi"
    assert family.known("shellfish") and not family.known("kiwi")


def _dairy_free(p, week) -> None:  # type: ignore[no-untyped-def]
    rule = family.rule_for("dairy", ["Riley"])
    for m in week["meals"]:
        if m["recipe"]:
            r = p.recipe(m["recipe"]["id"])
            assert not family.conflicts(r, [rule]), r["name"]


def test_plan_never_has_an_allergen(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    p.add_allergy("Riley", "dairy")
    week = p.plan(MONDAY)
    assert all(m["kind"] == "cook" for m in week["meals"])
    _dairy_free(p, week)
    # Ten more weeks, with a strong liking for a cheesy dish, still never plan one.
    lasagna = p.db.one("SELECT id FROM recipes WHERE name LIKE '%Lasagna%'")
    if lasagna:
        for _ in range(3):
            p.rate(lasagna["id"], 5)
    for i in range(1, 11):
        _dairy_free(p, p.plan(MONDAY + dt.timedelta(days=7 * i)))


def test_adding_an_allergy_replaces_planned_dinners(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    before = p.plan(MONDAY)
    rule = family.rule_for("gluten", ["Sam"])
    had = [
        m["day"] for m in before["meals"] if family.conflicts(p.recipe(m["recipe"]["id"]), [rule])
    ]
    assert had  # the starter set has plenty of pasta and bread
    # Keep one of them: an allergy still wins over "keep".
    p.lock(dt.date.fromisoformat(had[0]), True)
    out = p.add_allergy("Sam", "wheat")
    assert out["allergen"] == "gluten" and out["known"]
    assert out["blocked"]
    # Today is Tue Nov 10 in the tests, so Monday's dinner (already eaten) stays.
    assert set(out["replaced_days"]) == {d for d in had if d >= "2026-11-10"}
    after = p.week(MONDAY)
    for m in after["meals"]:
        if m["day"] >= "2026-11-10":
            assert not family.conflicts(p.recipe(m["recipe"]["id"]), [rule])
            assert not m["allergens"]
    for m in after["meals"]:
        if m["day"] in out["replaced_days"]:
            assert m["reasons"][0]["text"].startswith("Replaced")


def test_cant_pick_an_allergen_by_hand(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    p.plan(MONDAY)
    p.add_allergy("Riley", "shellfish")
    shrimp = p.db.one(
        "SELECT r.id FROM recipes r JOIN recipe_ingredients i ON i.recipe_id = r.id "
        "WHERE i.item = 'shrimp' LIMIT 1"
    )
    with pytest.raises(ValueError, match="shellfish"):
        p.swap(MONDAY + dt.timedelta(days=2), shrimp["id"])
    flagged = p.recipe(shrimp["id"])
    assert flagged["allergens"][0]["who"] == ["Riley"]


def test_nothing_safe_means_a_night_off_not_an_allergen(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    for a in ("dairy", "gluten", "egg", "fish", "shellfish", "soy", "sesame", "garlic", "onion"):
        p.add_allergy("Riley", a)
    week = p.plan(MONDAY)
    rules = family.rules(p.db, p.household)
    for m in week["meals"]:
        if m["recipe"]:
            assert not family.conflicts(p.recipe(m["recipe"]["id"]), rules)
        else:
            assert m["kind"] == "skip"


def test_profile_add_remove(make_planner) -> None:  # type: ignore[no-untyped-def]
    p = make_planner()
    names = [m["name"] for m in p.family()["members"]]
    assert names == ["Alex", "Sam"]  # the cooks from planner.toml are always listed
    p.add_family_member("Riley")
    p.add_allergy("riley", "Peanuts")  # any case finds the same person
    p.add_allergy("Riley", "peanut")  # and the same allergy isn't added twice
    riley = next(m for m in p.family()["members"] if m["name"] == "Riley")
    assert riley["allergies"] == ["peanut"] and not riley["in_planner_toml"]
    p.remove_allergy("Riley", "peanuts")
    with pytest.raises(ValueError):
        p.remove_allergy("Riley", "peanut")
    p.remove_family_member("Riley")
    assert "Riley" not in [m["name"] for m in p.family()["members"]]
    with pytest.raises(ValueError):
        p.remove_family_member("Riley")


def test_allergies_in_planner_toml(make_planner, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    toml = tmp_path / "planner.toml"
    toml.write_text('[[members]]\nname = "Alex"\nallergies = ["Shrimp", "milk"]\n', "utf-8")
    assert load_household(toml).members[0].allergies == ["Shrimp", "milk"]
    p = make_planner(members=[Member("Alex", allergies=["shrimp", "milk"]), Member("Sam")])
    alex = p.family()["members"][0]
    assert alex["allergies"] == ["dairy", "shrimp"]
    week = p.plan(MONDAY)
    rules = family.rules(p.db, p.household)
    assert all(not family.conflicts(p.recipe(m["recipe"]["id"]), rules) for m in week["meals"])
    with pytest.raises(ValueError, match="planner.toml"):
        p.remove_allergy("Alex", "dairy")


def test_api_and_mcp(make_planner, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from meals import mcp_server

    p = make_planner()
    c = TestClient(create_app(planner=p, settings=p.settings))
    assert c.post("/api/family/members", json={"name": "Riley"}).status_code == 200
    r = c.post("/api/family/members/Riley/allergies", json={"allergen": "tree nuts"}).json()
    assert r["allergen"] == "tree nuts"
    assert any(k["name"] == "dairy" for k in c.get("/api/family").json()["known_allergens"])
    assert c.delete("/api/family/members/Riley/allergies/tree%20nuts").status_code == 200
    assert c.delete("/api/family/members/Riley/allergies/tree%20nuts").status_code == 404
    assert c.delete("/api/family/members/Riley").status_code == 200
    assert c.post("/api/family/members", json={"name": "  "}).status_code == 400
    assert "allergens" in c.get("/api/recipes").json()[0]

    monkeypatch.setattr(mcp_server, "_planner", p)
    assert "Alex: no allergies" in mcp_server.family()
    text = mcp_server.family(person="Sam", add_allergy="sesame")
    assert text.startswith("Saved: Sam is allergic to sesame.")
    assert "Sam: sesame" in mcp_server.family()
    assert "⚠ not planned: sesame for Sam" in mcp_server.find_recipes("sesame")
    assert "Sam: no allergies" in mcp_server.family(person="Sam", remove_allergy="sesame")
    assert mcp_server.family(add_allergy="egg") == "Whose allergy? Pass person."


def test_cli(tmp_path: Path) -> None:
    env = {**os.environ, "MEALS_DATA_DIR": str(tmp_path)}
    env["MEALS_HOUSEHOLD_FILE"] = str(tmp_path / "none.toml")

    def meals(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "meals.cli", *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    out = meals("allergy", "Riley", "peanuts")
    assert out.returncode == 0, out.stderr
    assert "Riley: peanut" in out.stdout
    assert "Riley: peanut" in meals("family").stdout
    assert meals("allergy", "Riley", "egg", "--remove").returncode == 1
    assert "Riley: no allergies" in meals("allergy", "Riley", "peanut", "--remove").stdout
