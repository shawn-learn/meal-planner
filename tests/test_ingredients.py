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


def test_product_has_to_be_the_item() -> None:
    # Seen in real Calgary flyers.
    wrong = [
        ("butter", "Delici Cookie Butter Mousse 6 X 76 G"),
        ("garlic", "Hampton House Dry Garlic Ribs 1.36 Kg"),
        ("bacon", "Urban Factory Beef Bacon Jam Crispy Mini Rolls"),
        ("dill pickle", "Ruffles Creamy Dill Pickle 612 G"),
        ("chicken", "Pinty's Oven Roasted Chicken Strips 2 X 500 G"),
        ("chicken", "Hampton House Chicken Parmesan 1.2 Kg"),
        ("apple", "Oasis Apple Juice 24 × 300 ml"),
        ("apple", "Apple, Apple Crumble or Pumpkin Pies"),
        ("apple", "COMPLIMENTS Apple Sauce"),
        ("apple", "Red Bull The Apple Edition 250 mL 24-pack"),
    ]
    right = [
        ("apple", "Organic Fuji/Gala/Granny Smith/Pink Lady Apples"),
        ("avocado", "Bulk Avocados"),
        ("cheddar", "Balderson Double Smoked Cheddar 500 G"),
        ("salmon", "One Ocean Smoked Sockeye Salmon 454 G"),
        ("egg", "Large Eggs 12 Pack"),
        ("shrimp", "Kirkland Shrimp Raw Peeled"),
        ("chicken thigh", "Kirkland Signature Chicken Thighs Boneless 2 Kg"),
    ]
    assert [p for i, p in wrong if ing.matches(i, p)] == []
    assert [p for i, p in right if not ing.matches(i, p)] == []


def test_prepared_and_flavoured_products_dont_match() -> None:
    wrong = [
        ("parmesan", "Hampton House Chicken Parmesan 1.2 Kg"),
        ("shrimp", "Royal Asia Honey Walnut Shrimp 907 G"),
        ("lime", "Maison Perrier Lime 24 X 330 Ml"),
        ("milk", "Carnation Evaporated Milk"),
        ("chicken", "Ready For You Crispy Chicken"),
        ("cod fillet", "Breaded Cod Fillets"),
    ]
    assert [p for i, p in wrong if ing.matches(i, p)] == []
    assert ing.matches("chicken breast", "Yorkshire Valley Farms Organic Chicken Breast 2 Kg")
    assert ing.matches("salmon fillet", "Marinated Atlantic Salmon Fillets")
