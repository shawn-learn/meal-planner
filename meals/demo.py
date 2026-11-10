"""A demo household with made-up deals and a busy week, so the page can be tried before any
calendars or flyers are set up. It uses its own folder (``data-demo``) and never touches Keep.

    uv run meals demo        # then open http://127.0.0.1:8201
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from zoneinfo import ZoneInfo

from meals import deals as deal_mod
from meals.config import DEFAULT_PANTRY, Household, Member, Settings
from meals.db import DB
from meals.planner import week_start
from meals.schedule import Busy, Evening, evening
from meals.service import Planner
from meals.sources.flipp import Deal

TZ = ZoneInfo("America/Edmonton")

# (weekday, member, start, end, title)
BUSY = [
    (0, "Alex", "09:00", "17:15", "Work"),
    (1, "Sam", "16:30", "19:00", "Hockey practice"),
    (1, "Alex", "09:00", "17:40", "Work"),
    (2, "Alex", "09:00", "17:15", "Work"),
    (3, "Sam", "15:30", "17:00", "Dentist"),
    (3, "Alex", "09:00", "18:30", "Late meeting"),
    (4, "Alex", "09:00", "16:30", "Work"),
]

DEALS = [
    ("Safeway", "Maple Leaf Prime Chicken Thighs Value Pack", 3.99, "$3.99/lb", 6.49),
    ("Calgary Co-op", "Atlantic Salmon Fillets", 9.99, "$9.99", 14.99),
    ("Costco", "Kirkland Signature Lean Ground Beef", 5.49, "$5.49/lb", 6.99),
    ("Safeway", "Green Giant Broccoli Florets", 2.50, "$2.50", 3.99),
    ("Calgary Co-op", "Sweet Bell Peppers", 1.25, "$1.25 ea", 1.99),
    ("Costco", "Kirkland Shrimp Raw Peeled", 16.99, "$16.99", 21.99),
    ("Safeway", "Old El Paso Flour Tortillas", 2.99, "$2.99", 4.49),
    ("Calgary Co-op", "Baby Spinach Clamshell", 3.49, "$3.49", 4.99),
]


def _busy(start: _dt.date) -> dict[str, list[Busy]]:
    out: dict[str, list[Busy]] = {"Alex": [], "Sam": []}
    for wd, who, s, e, title in BUSY:
        d = start + _dt.timedelta(days=wd)
        out[who].append(
            (
                _dt.datetime.combine(d, _dt.time.fromisoformat(s), TZ),
                _dt.datetime.combine(d, _dt.time.fromisoformat(e), TZ),
                title,
            )
        )
    return out


def evenings(household: Household, start: _dt.date) -> dict[_dt.date, list[Evening]]:
    busy = _busy(start)
    out: dict[_dt.date, list[Evening]] = {}
    for i in range(7):
        d = start + _dt.timedelta(days=i)
        out[d] = [
            evening(m.name, d, [b for b in busy[m.name] if b[0].date() == d], household, TZ)
            for m in household.cooks()
        ]
    return out


def household() -> Household:
    return Household(
        members=[Member("Alex", max_minutes=60), Member("Sam", max_minutes=45)],
        pantry=list(DEFAULT_PANTRY) + ["brown sugar", "italian seasoning", "smoked paprika"],
        postal_code="",
    )


def build(data_dir: Path = Path("data-demo")) -> Planner:
    settings = Settings(data_dir=data_dir, port=8201, household_file=Path("does-not-exist"))
    db = DB(settings.db_path)
    p = Planner(settings, db=db, household=household(), evenings_loader=evenings)
    today = p.today()
    start = week_start(today)
    if not db.one("SELECT 1 AS x FROM deals LIMIT 1"):
        valid_to = (start + _dt.timedelta(days=13)).isoformat()
        deal_mod.store_deals(
            db,
            [
                Deal(
                    store, name, price, text, reg, None, start.isoformat(), valid_to, None, None, ""
                )
                for store, name, price, text, reg in DEALS
            ],
            source="demo",
        )
        # A little history so the taste features have something to show.
        for name, stars in [
            ("Chicken Fajitas", 5),
            ("Weeknight Spaghetti Bolognese", 5),
            ("Thai Red Curry with Chicken", 4),
            ("Baked Cod with Roasted Vegetables", 2),
            ("Lentil and Sweet Potato Curry", 3),
            ("Teriyaki Chicken Rice Bowls", 4),
        ]:
            row = db.one("SELECT id FROM recipes WHERE name = ?", name)
            if row:
                p.rate(row["id"], stars, who="demo")
        p.plan(start)
    return p
