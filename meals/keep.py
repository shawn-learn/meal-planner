"""Writing the shopping list to Google Keep (the same list Google Home adds to).

Keep has no official API for personal accounts, so this uses the unofficial ``gkeepapi`` with
the sign-in Daily Dashboard already saved (``uv run dash keep-auth``), so there's nothing new to
set up. The planner only ever touches the items it added, which end with a 🍽 marker: things you
or Google Home put on the list are left alone, ticked items are left alone, and an item you
already have on the list isn't added twice.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from meals import ingredients as ing


@dataclass
class ListItem:
    id: str
    text: str
    checked: bool


@dataclass
class SyncPlan:
    add: list[str] = field(default_factory=list)
    remove: list[ListItem] = field(default_factory=list)
    already: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "add": self.add,
            "remove": [i.text for i in self.remove],
            "already_on_list": self.already,
        }


def diff(wanted: list[tuple[str, str]], existing: list[ListItem], marker: str) -> SyncPlan:
    """`wanted` is (item name, Keep text). Decide what to add and what to take back."""
    plan = SyncPlan()
    mine = [i for i in existing if i.text.rstrip().endswith(marker)]
    theirs = [i for i in existing if not i.text.rstrip().endswith(marker) and not i.checked]
    wanted_texts = {text for _, text in wanted}
    mine_texts = {i.text.strip() for i in mine}
    their_names = [ing.tokens(i.text) for i in theirs]
    for item, text in wanted:
        if text in mine_texts:
            continue
        words = set(item.split())
        if any(words and words <= t for t in their_names):
            plan.already.append(item)
            continue
        plan.add.append(text)
    for i in mine:
        if not i.checked and i.text.strip() not in wanted_texts:
            plan.remove.append(i)
    return plan


class KeepError(Exception):
    pass


def _connect(email: str, master_token: str, state_path: Path) -> Any:
    import gkeepapi

    keep = gkeepapi.Keep()
    state = None
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError:
            state = None
    try:
        keep.authenticate(email, master_token, state=state, sync=True)
    except gkeepapi.exception.LoginException as exc:
        raise KeepError(
            "Google refused the Keep sign-in. Run `uv run dash keep-auth` in Daily Dashboard."
        ) from exc
    return keep


def _find_list(keep: Any, title: str) -> Any:
    import gkeepapi

    wanted = title.casefold()
    for n in keep.all():
        if (
            isinstance(n, gkeepapi.node.List)
            and not n.trashed
            and not n.archived
            and (n.title or "").strip().casefold() == wanted
        ):
            return n
    raise KeepError(f"No Keep list called “{title}”.")


def sync(
    wanted: list[tuple[str, str]],
    email: str | None,
    master_token: str | None,
    title: str,
    marker: str,
    state_path: Path,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not email or not master_token:
        raise KeepError(
            "Google Keep isn't connected. Set MEALS_KEEP_EMAIL, and run `uv run dash keep-auth` "
            "in Daily Dashboard (the planner reuses that sign-in)."
        )
    keep = _connect(email, master_token, state_path)
    glist = _find_list(keep, title)
    existing = [ListItem(i.id, i.text or "", bool(i.checked)) for i in glist.items]
    plan = diff(wanted, existing, marker)
    if not dry_run:
        for text in plan.add:
            glist.add(text, False)
        by_id = {i.id: i for i in glist.items}
        for item in plan.remove:
            node = by_id.get(item.id)
            if node is not None:
                node.delete()
        keep.sync()
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(keep.dump()), encoding="utf-8")
    link = f"https://keep.google.com/#LIST/{glist.server_id or glist.id}"
    return {**plan.as_dict(), "dry_run": dry_run, "link": link}
