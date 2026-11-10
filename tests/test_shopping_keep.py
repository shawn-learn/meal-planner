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
