from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from meals.config import DEFAULT_PANTRY, Household, Member, Settings
from meals.db import DB
from meals.schedule import Busy, Evening, evening
from meals.service import Planner

TZ = ZoneInfo("America/Edmonton")
MONDAY = dt.date(2026, 11, 9)


def at(day: dt.date, hhmm: str) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.fromisoformat(hhmm), TZ)


def household(**kw: object) -> Household:
    base: dict[str, object] = {
        "members": [Member("Alex"), Member("Sam")],
        "pantry": list(DEFAULT_PANTRY),
        "postal_code": "T3A0A0",
    }
    base.update(kw)
    return Household(**base)  # type: ignore[arg-type]


def loader_for(busy: dict[str, list[Busy]]):  # type: ignore[no-untyped-def]
    def load(h: Household, start: dt.date) -> dict[dt.date, list[Evening]]:
        out: dict[dt.date, list[Evening]] = {}
        for i in range(7):
            d = start + dt.timedelta(days=i)
            out[d] = [
                evening(m.name, d, [b for b in busy.get(m.name, []) if b[0].date() == d], h, TZ)
                for m in h.cooks()
            ]
        return out

    return load


@pytest.fixture
def make_planner(tmp_path):  # type: ignore[no-untyped-def]
    def make(busy: dict[str, list[Busy]] | None = None, **hh: object) -> Planner:
        settings = Settings(data_dir=tmp_path, household_file=tmp_path / "none.toml")
        return Planner(
            settings,
            db=DB(":memory:"),
            household=household(**hh),
            evenings_loader=loader_for(busy or {}),
            clock=lambda: dt.datetime(2026, 11, 10, 9, 0, tzinfo=TZ),
        )

    return make
