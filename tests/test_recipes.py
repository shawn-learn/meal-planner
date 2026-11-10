import json

import pytest

from meals import recipes
from meals.db import DB

PAGE = """<html><head>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
 {"@type":"WebPage","name":"x"},
 {"@type":["Recipe","NewsArticle"],"name":"Smoky Chili &amp; Cornbread","recipeYield":["6","6 bowls"],
  "prepTime":"PT20M","cookTime":"PT1H","image":{"url":"https://e.x/c.jpg"},
  "recipeCuisine":"American","keywords":"comfort, make-ahead",
  "recipeIngredient":["2 lb ground beef","1 onion, diced","2 cans kidney beans"],
  "recipeInstructions":[{"@type":"HowToSection","itemListElement":[
     {"@type":"HowToStep","text":"Brown the beef."},{"@type":"HowToStep","text":"Simmer it all."}]}]}
]}</script></head></html>"""


def test_from_html_reads_schema_org_recipe() -> None:
    r = recipes.from_html(PAGE, "https://e.x/chili")
    assert r.name == "Smoky Chili & Cornbread"
    assert r.servings == 6
    assert (r.prep_minutes, r.cook_minutes) == (20, 60)
    assert r.image_url == "https://e.x/c.jpg"
    assert r.ingredients[0] == "2 lb ground beef"
    assert r.instructions == "1. Brown the beef.\n2. Simmer it all."
    assert "comfort" in r.tags and "american" in r.tags


def test_from_html_without_recipe_raises() -> None:
    with pytest.raises(ValueError):
        recipes.from_html("<html></html>")


def test_minutes() -> None:
    assert recipes.minutes("PT1H15M") == 75
    assert recipes.minutes("P0DT0H45M") == 45
    assert recipes.minutes("nonsense") is None


def test_seed_and_save_roundtrip() -> None:
    db = DB(":memory:")
    n = recipes.seed(db)
    assert n >= 25
    assert recipes.seed(db) == 0  # only once
    rid = recipes.save(
        db, recipes.Recipe(name="Test Tacos", ingredients=["1 lb ground turkey"], tags=["Mexican"])
    )
    r = recipes.get(db, rid)
    assert r is not None
    assert r["protein"] == "turkey"
    assert r["tags"] == ["mexican"]
    assert r["ingredients"][0]["item"] == "ground turkey"


def test_starter_recipes_are_valid() -> None:
    from importlib import resources as res

    data = json.loads(res.files("meals").joinpath("starter_recipes.json").read_text("utf-8"))
    names = [r["name"] for r in data]
    assert len(names) == len(set(names))
    for r in data:
        assert r["ingredients"] and r["instructions"]
