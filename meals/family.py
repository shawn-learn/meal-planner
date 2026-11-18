"""The family profile: who lives here and what each of them is allergic to.

An allergy is a hard rule, enforced in plain code: the planner never puts a dinner on the plan
that has an ingredient someone is allergic to, whoever is cooking. Allergies are stored in the
planner's database (added from the web page, the CLI or Claude), and can also be listed under a
member in ``planner.toml`` (``allergies = ["peanut"]``).

Common allergens (Health Canada's priority list, plus gluten) are known by the ingredients that
carry them, so "dairy" catches butter, parmesan and sour cream, "gluten" (or "wheat") catches
pasta and soy sauce, and "fish" catches fish sauce. Anything else ("kiwi", "mushrooms") is
matched by name.

Matching works on each ingredient's shopping name, word by word, so "egg" doesn't catch
"eggplant" and "milk" doesn't catch "coconut milk".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from meals import ingredients as ing
from meals.config import Household
from meals.db import DB


@dataclass(frozen=True)
class Allergen:
    name: str
    # Other ways people say it ("milk", "lactose" → dairy).
    aliases: tuple[str, ...]
    # Ingredient names that contain it. Every word has to be in the ingredient's name.
    terms: tuple[str, ...]
    # Ingredient names that look like it but aren't ("coconut milk" for dairy).
    except_: tuple[str, ...] = ()


_WHEAT = (
    "wheat", "flour", "bread", "breadcrumb", "panko", "crouton", "baguette", "bun", "roll",
    "naan", "pita", "tortilla", "wrap", "pasta", "spaghetti", "linguine", "fettuccine", "penne",
    "macaroni", "rigatoni", "fusilli", "lasagna", "lasagne", "orzo", "noodle", "noodles",
    "ramen", "udon", "couscous", "bulgur", "semolina", "farro", "pizza dough", "pie crust",
    "puff pastry", "pastry", "dumpling", "cracker", "pancake mix", "biscuit", "bagel",
    "english muffin", "seitan", "soy sauce", "teriyaki", "hoisin", "oyster sauce",
    "caesar salad kit", "beer", "barley", "rye", "malt",
)  # fmt: skip
_NOT_WHEAT = (
    "corn tortilla", "rice noodle", "rice noodles", "rice flour", "rice paper", "almond flour",
    "coconut flour", "corn flour", "chickpea flour", "gluten-free", "gluten free", "tamari",
    "lettuce wrap",
)  # fmt: skip

CATALOG: tuple[Allergen, ...] = (
    Allergen(
        "peanut",
        ("peanuts", "peanut butter", "groundnut"),
        ("peanut", "satay", "groundnut"),
    ),
    Allergen(
        "tree nuts",
        ("tree nut", "nuts", "nut"),
        (
            "almond",
            "walnut",
            "pecan",
            "cashew",
            "pistachio",
            "hazelnut",
            "macadamia",
            "pine nut",
            "brazil nut",
            "pesto",
            "praline",
            "marzipan",
            "nutella",
            "nut",
        ),  # fmt: skip
    ),
    Allergen(
        "dairy",
        ("milk", "lactose", "cow's milk", "dairy products"),
        (
            "milk",
            "butter",
            "buttermilk",
            "cream",
            "cheese",
            "cheddar",
            "mozzarella",
            "parmesan",
            "parmigiano",
            "feta",
            "ricotta",
            "mascarpone",
            "gouda",
            "brie",
            "swiss",
            "provolone",
            "monterey jack",
            "pepper jack",
            "colby",
            "halloumi",
            "paneer",
            "queso",
            "cotija",
            "goat cheese",
            "yogurt",
            "yoghurt",
            "kefir",
            "ghee",
            "whey",
            "casein",
            "half-and-half",
            "tzatziki",
            "alfredo",
            "caesar",
            "ranch",
        ),  # fmt: skip
        (
            "coconut milk",
            "coconut cream",
            "almond milk",
            "oat milk",
            "soy milk",
            "rice milk",
            "cashew milk",
            "peanut butter",
            "almond butter",
            "cashew butter",
            "apple butter",
            "cocoa butter",
            "cream tartar",
            "dairy-free",
            "dairy free",
            "vegan",
            "butter lettuce",
            "butter bean",
            "swiss chard",
        ),  # fmt: skip
    ),
    Allergen(
        "egg",
        ("eggs", "egg white", "egg yolk"),
        (
            "egg",
            "mayonnaise",
            "mayo",
            "aioli",
            "meringue",
            "caesar",
            "hollandaise",
            "custard",
        ),  # fmt: skip
        ("egg-free", "vegan"),
    ),
    # Wheat and the other gluten grains together: safer for both a wheat allergy and celiac.
    Allergen("gluten", ("wheat", "celiac", "coeliac", "wheat flour"), _WHEAT, _NOT_WHEAT),
    Allergen(
        "soy",
        ("soya", "soybean", "soybeans"),
        (
            "soy",
            "soya",
            "tofu",
            "edamame",
            "miso",
            "tempeh",
            "tamari",
            "teriyaki",
            "hoisin",
            "soybean",
        ),  # fmt: skip
    ),
    Allergen(
        "fish",
        ("finfish",),
        (
            "fish",
            "salmon",
            "cod",
            "tuna",
            "tilapia",
            "halibut",
            "haddock",
            "sole",
            "trout",
            "pollock",
            "mackerel",
            "sardine",
            "anchovy",
            "anchovies",
            "bass",
            "snapper",
            "catfish",
            "mahi",
            "basa",
            "pickerel",
            "walleye",
            "perch",
            "arctic char",
            "worcestershire",
            "caesar",
        ),  # fmt: skip
    ),
    Allergen(
        "shellfish",
        ("crustacean", "crustaceans", "seafood", "molluscs", "mollusks"),
        (
            "shellfish",
            "shrimp",
            "prawn",
            "crab",
            "lobster",
            "crawfish",
            "crayfish",
            "scallop",
            "clam",
            "mussel",
            "oyster",
            "squid",
            "calamari",
            "octopus",
        ),  # fmt: skip
    ),
    Allergen(
        "sesame",
        ("sesame seed", "sesame seeds"),
        ("sesame", "tahini", "hummus", "halva", "furikake", "everything bagel"),
    ),
    Allergen("mustard", ("mustard seed",), ("mustard", "dijon")),
)


def _stem(word: str) -> str:
    # Loose plural folding, applied the same way to both sides of a match.
    return word[:-1] if word.endswith("s") and len(word) > 3 else word


def _words(text: str) -> frozenset[str]:
    return frozenset(_stem(w) for w in ing.normalize(text).split())


def _key(text: str) -> str:
    return " ".join(ing.normalize(text).split()) or text.strip().lower()


_BY_NAME: dict[str, Allergen] = {}
for _a in CATALOG:
    for _n in (_a.name, *_a.aliases):
        _BY_NAME[_key(_n)] = _a


def canonical(allergen: str) -> str:
    """The name an allergy is stored under: "Peanuts" → "peanut", "milk" → "dairy"."""
    found = _BY_NAME.get(_key(allergen))
    return found.name if found else _key(allergen)


def known(allergen: str) -> bool:
    return _key(allergen) in _BY_NAME


@dataclass
class Rule:
    """One allergen and who it's for."""

    allergen: str
    who: list[str]
    terms: list[frozenset[str]] = field(default_factory=list)
    exceptions: list[frozenset[str]] = field(default_factory=list)

    def hit(self, item: str) -> bool:
        words = _words(item)
        if not words:
            return False
        if not any(t <= words for t in self.terms):
            return False
        return not any(e <= words for e in self.exceptions)


def rule_for(allergen: str, who: list[str]) -> Rule:
    name = canonical(allergen)
    found = _BY_NAME.get(_key(name))
    terms = found.terms if found else (name,)
    exceptions = found.except_ if found else ()
    return Rule(
        allergen=name,
        who=who,
        terms=[w for w in (_words(t) for t in terms) if w],
        exceptions=[w for w in (_words(e) for e in exceptions) if w],
    )


@dataclass
class Conflict:
    allergen: str
    who: list[str]
    item: str

    def as_dict(self) -> dict[str, Any]:
        return {"allergen": self.allergen, "who": self.who, "item": self.item}

    @property
    def text(self) -> str:
        return f"{self.item} ({self.allergen}: {', '.join(self.who)})"


def conflicts(recipe: dict[str, Any], rules: list[Rule]) -> list[Conflict]:
    """Every allergen in this recipe, with the ingredient that carries it."""
    out: list[Conflict] = []
    for rule in rules:
        for i in recipe["ingredients"]:
            if rule.hit(i["item"]):
                out.append(Conflict(rule.allergen, rule.who, i["item"]))
                break
    return out


# ── Storage ─────────────────────────────────────────────────────────────────────


def _member_id(db: DB, name: str) -> int | None:
    row = db.one("SELECT id FROM family_members WHERE name = ?", name.strip())
    return int(row["id"]) if row else None


def add_member(db: DB, name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise ValueError("Who? Give a name.")
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO family_members (name) VALUES (?)", (name,))
    row = db.one("SELECT name FROM family_members WHERE name = ?", name)
    assert row is not None
    return str(row["name"])


def remove_member(db: DB, name: str) -> bool:
    with db.tx() as c:
        cur = c.execute("DELETE FROM family_members WHERE name = ?", (name.strip(),))
    return cur.rowcount > 0


def add_allergy(db: DB, name: str, allergen: str) -> tuple[str, str]:
    """Returns (member's name as stored, allergen as stored)."""
    stored = canonical(allergen)
    if not stored:
        raise ValueError("Which allergy?")
    who = add_member(db, name)
    mid = _member_id(db, who)
    with db.tx() as c:
        c.execute(
            "INSERT OR IGNORE INTO family_allergies (member_id, allergen) VALUES (?, ?)",
            (mid, stored),
        )
    return who, stored


def remove_allergy(db: DB, name: str, allergen: str) -> bool:
    mid = _member_id(db, name)
    if mid is None:
        return False
    with db.tx() as c:
        cur = c.execute(
            "DELETE FROM family_allergies WHERE member_id = ? AND allergen IN (?, ?)",
            (mid, canonical(allergen), _key(allergen)),
        )
    return cur.rowcount > 0


def members(db: DB, household: Household) -> list[dict[str, Any]]:
    """Everyone: people added to the profile, and the cooks from planner.toml."""
    rows = db.all(
        "SELECT m.name, a.allergen FROM family_members m "
        "LEFT JOIN family_allergies a ON a.member_id = m.id ORDER BY m.id, a.allergen"
    )
    people: dict[str, dict[str, Any]] = {}

    def person(name: str) -> dict[str, Any]:
        k = name.lower()
        if k not in people:
            people[k] = {
                "name": name,
                "allergies": [],
                "in_planner_toml": False,
                "cooks": False,
            }
        return people[k]

    for m in household.members:
        p = person(m.name)
        p["in_planner_toml"] = True
        p["cooks"] = m.cooks
        for a in m.allergies:
            if canonical(a) not in p["allergies"]:
                p["allergies"].append(canonical(a))
    for r in rows:
        p = person(r["name"])
        if r["allergen"] and r["allergen"] not in p["allergies"]:
            p["allergies"].append(r["allergen"])
    for p in people.values():
        p["allergies"].sort()
    return list(people.values())


def rules(db: DB, household: Household) -> list[Rule]:
    """One rule per allergen anyone in the house has."""
    who: dict[str, list[str]] = {}
    for p in members(db, household):
        for a in p["allergies"]:
            who.setdefault(a, []).append(p["name"])
    return [rule_for(a, names) for a, names in sorted(who.items())]


def catalog() -> list[dict[str, Any]]:
    """The allergens the planner knows the ingredients of, for pickers and help text."""
    return [{"name": a.name, "also": list(a.aliases)} for a in CATALOG]
