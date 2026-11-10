"""Who is free to cook, from each person's calendar.

Each person's Google Calendar has a "Secret address in iCal format"; the planner reads that
(no Google sign-in needed) and keeps a copy so a network blip doesn't stop planning.

For each evening it works out how long each cook has before dinner: from the end of their last
event before dinner (or the earliest cooking time) up to dinner. Anyone busy at dinner time
isn't cooking that night.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from meals.config import Household, Member

Busy = tuple[_dt.datetime, _dt.datetime, str]


@dataclass
class Evening:
    day: _dt.date
    member: str
    free_minutes: int
    free_from: _dt.time | None
    # What's keeping them busy before dinner, for the explanation ("Hockey until 5:15").
    because: str | None


def _cache_path(cache_dir: Path, url: str) -> Path:
    return cache_dir / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".ics")


def fetch_calendar(url: str, cache_dir: Path, timeout_s: float = 15.0) -> str | None:
    """The calendar's text, refreshed if possible, else the last copy, else None."""
    path = _cache_path(cache_dir, url)
    try:
        resp = httpx.get(url.replace("webcal://", "https://"), timeout=timeout_s)
        resp.raise_for_status()
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.text, encoding="utf-8")
        return resp.text
    except httpx.HTTPError:
        return path.read_text(encoding="utf-8") if path.exists() else None


def busy_from_ics(text: str, start: _dt.date, end: _dt.date, tz: ZoneInfo) -> list[Busy]:
    import icalendar
    import recurring_ical_events

    cal = icalendar.Calendar.from_ical(text)
    out: list[Busy] = []
    for ev in recurring_ical_events.of(cal).between(start, end + _dt.timedelta(days=1)):
        s = ev.get("DTSTART").dt
        e = ev.get("DTEND").dt if ev.get("DTEND") else None
        if not isinstance(s, _dt.datetime):
            continue  # all-day events (birthdays, "Mom visiting") don't block cooking
        if str(ev.get("TRANSP", "OPAQUE")).upper() == "TRANSPARENT":
            continue  # marked "free" in Google Calendar
        if e is None or not isinstance(e, _dt.datetime):
            e = s + _dt.timedelta(hours=1)
        s = s.astimezone(tz) if s.tzinfo else s.replace(tzinfo=tz)
        e = e.astimezone(tz) if e.tzinfo else e.replace(tzinfo=tz)
        out.append((s, e, str(ev.get("SUMMARY", "Busy"))))
    return out


def evening(
    member: str, day: _dt.date, busy: list[Busy], household: Household, tz: ZoneInfo
) -> Evening:
    window_start = _dt.datetime.combine(day, household.cook_from, tz)
    dinner = _dt.datetime.combine(day, household.dinner_time, tz)
    free_from = window_start
    because: str | None = None
    for s, e, title in sorted(busy):
        if s < dinner and e > dinner - _dt.timedelta(minutes=10):
            # Busy at dinner: not cooking tonight.
            return Evening(day, member, 0, None, title)
        if s < dinner and e > free_from:
            free_from = e
            because = title
    minutes = max(0, int((dinner - free_from).total_seconds() // 60))
    return Evening(day, member, minutes, free_from.timetz().replace(tzinfo=None), because)


def week_evenings(
    household: Household,
    start: _dt.date,
    days: int,
    cache_dir: Path,
    loader: Any = None,
) -> dict[_dt.date, list[Evening]]:
    """day -> one Evening per cook. `loader(member)` returns that member's busy list; it is
    replaceable so tests don't need calendars."""
    tz = ZoneInfo(household.timezone)
    end = start + _dt.timedelta(days=days - 1)

    def default_loader(m: Member) -> list[Busy]:
        busy: list[Busy] = []
        for url in m.calendars:
            text = fetch_calendar(url, cache_dir)
            if text:
                busy.extend(busy_from_ics(text, start, end, tz))
        return busy

    load = loader or default_loader
    by_member = {m.name: load(m) for m in household.cooks()}
    out: dict[_dt.date, list[Evening]] = {}
    for i in range(days):
        day = start + _dt.timedelta(days=i)
        out[day] = [
            evening(name, day, [b for b in busy if b[0].date() == day], household, tz)
            for name, busy in by_member.items()
        ]
    return out
