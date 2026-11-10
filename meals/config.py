"""Settings.

Two places, on purpose:

* Process settings (where data lives, the port, secrets) come from the environment (prefix
  ``MEALS_``) or a ``.env`` file. Secrets can also live in the OS keyring (Windows Credential
  Manager on Prime), and the Google Keep sign-in is shared with Daily Dashboard's.
* The household (who lives here, their calendars, when dinner is, which stores, the pantry) is
  in ``planner.toml``, which is meant to be edited by hand. ``planner.example.toml`` documents it.
"""

from __future__ import annotations

import datetime as _dt
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

KEYRING_SERVICE = "meal-planner"
# Daily Dashboard already signs in to Google Keep; reuse its token instead of a second sign-in.
DASHBOARD_KEYRING_SERVICE = "daily-dashboard"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEALS_", env_file=".env", extra="ignore", env_ignore_empty=True
    )

    data_dir: Path = Path("data")
    household_file: Path = Path("planner.toml")
    host: str = "127.0.0.1"
    port: int = 8200
    web_dir: Path = Path("web")

    keep_email: str | None = None
    keep_master_token: str | None = None
    keep_state: Path = Path("data/keep_state.json")

    http_timeout_s: float = 15.0

    @property
    def db_path(self) -> Path:
        return self.data_dir / "planner.db"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def secret(value: str | None, user: str) -> str | None:
    """The configured value, else this app's keyring entry, else Daily Dashboard's."""
    if value:
        return value
    try:
        import keyring

        for service in (KEYRING_SERVICE, DASHBOARD_KEYRING_SERVICE):
            found: str | None = keyring.get_password(service, user)
            if found:
                return found
    except Exception:  # no keyring backend (CI, containers)
        return None
    return None


# ── Household ──────────────────────────────────────────────────────────────────


@dataclass
class Member:
    name: str
    cooks: bool = True
    # Secret iCal address of this person's calendar (Google Calendar → Settings → "Secret
    # address in iCal format"). Several are fine. Empty means "always free".
    calendars: list[str] = field(default_factory=list)
    # The most hands-on minutes this person wants to spend cooking on a weeknight.
    max_minutes: int = 60


@dataclass
class Household:
    timezone: str = "America/Edmonton"
    members: list[Member] = field(default_factory=lambda: [Member("Me")])
    servings: int = 4
    dinner_time: _dt.time = _dt.time(18, 0)
    # Cooking can start no earlier than this.
    cook_from: _dt.time = _dt.time(16, 0)
    # The planner leaves this weekday free (e.g. "fri" for pizza night out). Lowercase 3 letters.
    skip_days: list[str] = field(default_factory=list)
    # Nights that are leftovers by design, when the night before made plenty.
    leftovers_ok: bool = True

    postal_code: str = ""
    # Flipp merchant names to watch, matched case-insensitively as substrings.
    stores: list[str] = field(default_factory=lambda: ["Costco", "Safeway", "Co-op"])
    # Extra things to watch for deals even when no recipe needs them yet.
    watch: list[str] = field(default_factory=list)

    # Always in the house; never put on the list.
    pantry: list[str] = field(default_factory=list)
    # Never plan a recipe that uses any of these (allergies, hard no's).
    avoid: list[str] = field(default_factory=list)

    keep_list_title: str = "Shopping list"
    # Suffix on each item the planner adds, so it never touches items you typed yourself.
    keep_marker: str = "🍽"

    def cooks(self) -> list[Member]:
        return [m for m in self.members if m.cooks] or self.members[:1]


DEFAULT_PANTRY = [
    "salt",
    "pepper",
    "black pepper",
    "olive oil",
    "vegetable oil",
    "canola oil",
    "water",
    "sugar",
    "flour",
    "all-purpose flour",
    "baking powder",
    "baking soda",
    "soy sauce",
    "garlic powder",
    "onion powder",
    "paprika",
    "chili powder",
    "cumin",
    "dried oregano",
    "dried thyme",
    "red pepper flakes",
    "vinegar",
    "honey",
    "dijon mustard",
    "ketchup",
    "cornstarch",
    "chicken broth",
    "rice",
]


def _time(value: Any, default: _dt.time) -> _dt.time:
    if value is None:
        return default
    if isinstance(value, _dt.time):
        return value
    return _dt.time.fromisoformat(str(value))


def load_household(path: Path) -> Household:
    if not path.exists():
        return Household(pantry=list(DEFAULT_PANTRY))
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    members = [
        Member(
            name=str(m["name"]),
            cooks=bool(m.get("cooks", True)),
            calendars=[str(c) for c in m.get("calendars", [])],
            max_minutes=int(m.get("max_minutes", 60)),
        )
        for m in raw.get("members", [])
    ] or [Member("Me")]
    dinner = raw.get("dinner", {})
    deals = raw.get("deals", {})
    kitchen = raw.get("kitchen", {})
    keep = raw.get("keep", {})
    return Household(
        timezone=str(raw.get("timezone", "America/Edmonton")),
        members=members,
        servings=int(dinner.get("servings", 4)),
        dinner_time=_time(dinner.get("time"), _dt.time(18, 0)),
        cook_from=_time(dinner.get("cook_from"), _dt.time(16, 0)),
        skip_days=[str(d).lower()[:3] for d in dinner.get("skip_days", [])],
        leftovers_ok=bool(dinner.get("leftovers_ok", True)),
        postal_code=str(deals.get("postal_code", "")).replace(" ", "").upper(),
        stores=[str(s) for s in deals.get("stores", ["Costco", "Safeway", "Co-op"])],
        watch=[str(s) for s in deals.get("watch", [])],
        pantry=[str(s).lower() for s in kitchen.get("pantry", DEFAULT_PANTRY)],
        avoid=[str(s).lower() for s in kitchen.get("avoid", [])],
        keep_list_title=str(keep.get("list_title", "Shopping list")),
        keep_marker=str(keep.get("marker", "🍽")),
    )
