import pytest

from meals import ingredients as ing


@pytest.mark.parametrize(
    ("line", "qty", "unit", "item"),
    [
        ("2 lb boneless skinless chicken thighs, trimmed", 2, "lb", "chicken thigh"),
        ("1 (28 oz) can crushed tomatoes", 1, "can", "tomato"),
        ("2-3 cloves garlic, minced", 3, "clove", "garlic"),
        ("½ cup sour cream", 0.5, "cup", "sour cream"),
        ("1 1/2 lb lean ground beef", 1.5, "lb", "ground beef"),
        ("3 large eggs", 3, None, "egg"),
        ("1 bunch green onions", 1, "bunch", "green onion"),
        ("Salt and pepper to taste", None, None, "salt pepper"),
    ],
)
def test_parse(line: str, qty: float | None, unit: str | None, item: str) -> None:
    p = ing.parse(line)
    assert (p.quantity, p.unit, p.item) == (qty, unit, item)


def test_matches_whole_words_only() -> None:
    assert ing.matches("chicken thigh", "Maple Leaf Prime Chicken Thighs Value Pack")
    assert not ing.matches("chicken breast", "Chicken Thighs")
    assert not ing.matches("pepper", "Pepperoni Pizza")
    assert ing.matches("ground beef", "Kirkland Extra Lean Ground Beef")


def test_pantry() -> None:
    pantry = ["salt", "pepper", "olive oil", "chicken broth"]
    assert ing.is_pantry("salt pepper", pantry)
    assert ing.is_pantry("olive oil", pantry)
    assert not ing.is_pantry("chicken", pantry)
    assert not ing.is_pantry("red bell pepper", pantry)


def test_format_quantity() -> None:
    assert ing.format_quantity(1.5, "lb") == "1 1/2 lb"
    assert ing.format_quantity(0.25, "cup") == "1/4 cup"
    assert ing.format_quantity(3, None) == "3"
    assert ing.format_quantity(None, "cup") == ""


def test_matches_rejects_blends_and_prepared_food() -> None:
    assert not ing.matches("ground beef", "Ground Beef & Pork Blend")
    assert not ing.matches("chicken", "Campbell's Chicken Noodle Soup")
    assert not ing.matches("salmon", "Salmon Flavour Cat Treats")
    assert not ing.matches("chicken", "Don Miguel Mini Chicken Tacos")
    assert ing.matches("pork chop", "Fresh Pork Loin Chops")
    assert ing.matches("chicken breast", "COMPLIMENTS Fresh AIR-CHILLED Chicken Breast Halves")
