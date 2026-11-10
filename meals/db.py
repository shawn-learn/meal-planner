"""SQLite storage. One file (``data/planner.db``), no server, easy to back up.

Everything the planner knows lives here rather than in a chat: recipes, what you thought of
them, the deals it found, the plans it made and what it put on the Keep list. That is what lets
it remember from week to week without anyone re-explaining.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS recipes (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    source_url TEXT,
    image_url TEXT,
    servings INTEGER NOT NULL DEFAULT 4,
    prep_minutes INTEGER NOT NULL DEFAULT 15,
    cook_minutes INTEGER NOT NULL DEFAULT 20,
    hands_on_minutes INTEGER,
    tags TEXT NOT NULL DEFAULT '[]',
    protein TEXT,
    instructions TEXT NOT NULL DEFAULT '',
    makes_leftovers INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS recipes_name ON recipes(name);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    line TEXT NOT NULL,
    quantity REAL,
    unit TEXT,
    item TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ri_recipe ON recipe_ingredients(recipe_id);

CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY,
    recipe_id INTEGER NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    who TEXT,
    note TEXT,
    served_on TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- What the planner has learned you like (+) or not (-): "tag:mexican", "item:salmon",
-- "recipe:12". Updated from ratings and swaps.
CREATE TABLE IF NOT EXISTS preferences (
    key TEXT PRIMARY KEY,
    weight REAL NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS deals (
    id INTEGER PRIMARY KEY,
    store TEXT NOT NULL,
    name TEXT NOT NULL,
    price REAL,
    price_text TEXT,
    regular_price REAL,
    unit TEXT,
    valid_from TEXT,
    valid_to TEXT,
    image_url TEXT,
    link TEXT,
    query TEXT,
    source TEXT NOT NULL DEFAULT 'flipp',
    fetched_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS deals_unique ON deals(store, name, valid_to);

CREATE TABLE IF NOT EXISTS plans (
    week_start TEXT PRIMARY KEY,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_meals (
    week_start TEXT NOT NULL REFERENCES plans(week_start) ON DELETE CASCADE,
    day TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'cook',  -- cook | leftovers | skip
    recipe_id INTEGER REFERENCES recipes(id) ON DELETE SET NULL,
    cook TEXT,
    start_by TEXT,
    free_minutes INTEGER,
    reasons TEXT NOT NULL DEFAULT '[]',
    locked INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (week_start, day)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL DEFAULT (datetime('now')),
    kind TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}'
);
"""


class DB:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.conn
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def all(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, *args: Any) -> dict[str, Any] | None:
        row = self.conn.execute(sql, args).fetchone()
        return dict(row) if row else None

    def log(self, kind: str, **detail: Any) -> None:
        with self.tx() as c:
            c.execute("INSERT INTO events (kind, detail) VALUES (?, ?)", (kind, json.dumps(detail)))
