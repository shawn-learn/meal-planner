import datetime as dt

from meals import schedule
from tests.conftest import MONDAY, TZ, at, household

ICS = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:1
DTSTART;TZID=America/Edmonton:20261109T163000
DTEND;TZID=America/Edmonton:20261109T171500
SUMMARY:Hockey
RRULE:FREQ=WEEKLY;COUNT=4
END:VEVENT
BEGIN:VEVENT
UID:2
DTSTART;VALUE=DATE:20261110
SUMMARY:Grandma visiting
END:VEVENT
BEGIN:VEVENT
UID:3
DTSTART;TZID=America/Edmonton:20261111T170000
DTEND;TZID=America/Edmonton:20261111T173000
SUMMARY:Free-time reminder
TRANSP:TRANSPARENT
END:VEVENT
END:VCALENDAR
"""


def test_busy_from_ics_expands_repeats_and_skips_all_day_and_free() -> None:
    busy = schedule.busy_from_ics(ICS, MONDAY, MONDAY + dt.timedelta(days=6), TZ)
    assert [b[2] for b in busy] == ["Hockey"]
    assert busy[0][0] == at(MONDAY, "16:30")


def test_evening_free_after_last_event() -> None:
    h = household()
    ev = schedule.evening(
        "Alex", MONDAY, [(at(MONDAY, "09:00"), at(MONDAY, "17:15"), "Work")], h, TZ
    )
    assert ev.free_minutes == 45
    assert ev.because == "Work"


def test_evening_busy_at_dinner() -> None:
    h = household()
    ev = schedule.evening(
        "Sam", MONDAY, [(at(MONDAY, "16:30"), at(MONDAY, "19:00"), "Hockey")], h, TZ
    )
    assert ev.free_minutes == 0


def test_evening_no_events_whole_window() -> None:
    ev = schedule.evening("Sam", MONDAY, [], household(), TZ)
    assert ev.free_minutes == 120
