"""`uv run meals …`"""

from __future__ import annotations

import argparse
import asyncio
import datetime as _dt
import json
import os
import signal
import sys
from typing import Any


def _planner() -> Any:
    from meals.config import get_settings
    from meals.service import Planner

    return Planner(get_settings())


def _date(s: str | None) -> _dt.date | None:
    return _dt.date.fromisoformat(s) if s else None


def main(argv: list[str] | None = None) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="meals", description="Plan the week's dinners.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="Run the web page and API")
    s.add_argument("--host")
    s.add_argument("--port", type=int)

    w = sub.add_parser("weekly", help="Check deals, plan the upcoming week, update Keep")
    w.add_argument("--no-keep", action="store_true", help="Don't touch Google Keep")

    p = sub.add_parser("plan", help="Plan a week (default: the upcoming one)")
    p.add_argument("--week", help="Any date in the week, YYYY-MM-DD")
    p.add_argument("--fresh", action="store_true", help="Also replace kept dinners")

    sub.add_parser("show", help="Print the upcoming week").add_argument("--week")
    sub.add_parser("deals", help="Check the flyers now")

    d = sub.add_parser("add-deal", help="Save a deal you saw (e.g. Costco coupon book)")
    d.add_argument("store")
    d.add_argument("name")
    d.add_argument("--price", type=float)
    d.add_argument("--until", help="YYYY-MM-DD")
    d.add_argument("--note", default="")

    i = sub.add_parser("import", help="Add a recipe from a link")
    i.add_argument("url")

    r = sub.add_parser("rate", help="Rate a recipe 1-5")
    r.add_argument("recipe_id", type=int)
    r.add_argument("stars", type=int)
    r.add_argument("--note")

    k = sub.add_parser("keep-sync", help="Put the list on Google Keep")
    k.add_argument("--week")
    k.add_argument("--dry-run", action="store_true")

    sub.add_parser("stop", help="Stop a running `meals serve`")
    sub.add_parser("mcp", help="Run the MCP server on stdio (for Claude)")
    sub.add_parser("demo", help="Try it with a made-up household on port 8201")

    a = ap.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn

        from meals.api import create_app
        from meals.config import get_settings

        st = get_settings()
        st.data_dir.mkdir(parents=True, exist_ok=True)
        (st.data_dir / "meals.pid").write_text(str(os.getpid()), encoding="utf-8")
        if sys.stdout is None or sys.stderr is None:  # pythonw (start.bat): log to a file
            log = open(st.data_dir / "meals.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
            sys.stdout = sys.stderr = log
        uvicorn.run(create_app(settings=st), host=a.host or st.host, port=a.port or st.port)
        return
    if a.cmd == "stop":
        from meals.config import get_settings

        pid_file = get_settings().data_dir / "meals.pid"
        if not pid_file.exists():
            print("Not running.")
            return
        try:
            os.kill(int(pid_file.read_text(encoding="utf-8")), signal.SIGTERM)
            print("Stopped.")
        except (OSError, ValueError):
            print("Wasn't running.")
        pid_file.unlink(missing_ok=True)
        return
    if a.cmd == "demo":
        import uvicorn

        from meals import demo
        from meals.api import create_app

        dp = demo.build()
        print("Demo household at http://127.0.0.1:8201 (data in data-demo/)")
        uvicorn.run(create_app(planner=dp, settings=dp.settings), host="127.0.0.1", port=8201)
        return
    if a.cmd == "mcp":
        from meals.mcp_server import run

        run()
        return

    from meals.mcp_server import _week_text

    pl = _planner()
    if a.cmd == "weekly":
        out = asyncio.run(pl.weekly(sync=not a.no_keep))
        print(json.dumps(out["deals"]))
        print(_week_text(out["week"]))
        if "keep" in out:
            print("Keep:", json.dumps(out["keep"], ensure_ascii=False))
    elif a.cmd == "plan":
        week = _date(a.week)
        print(_week_text(pl.plan(pl.week_for(week) if week else None, not a.fresh)))
    elif a.cmd == "show":
        week = _date(a.week)
        print(_week_text(pl.week(pl.week_for(week) if week else None)))
    elif a.cmd == "deals":
        print(json.dumps(asyncio.run(pl.refresh_deals()), indent=1))
    elif a.cmd == "add-deal":
        pl.add_deal(a.store, a.name, a.price, _date(a.until), a.note)
        print("Saved.")
    elif a.cmd == "import":
        rec = pl.import_recipe(a.url)
        print(f"Added [{rec['id']}] {rec['name']} ({len(rec['ingredients'])} ingredients)")
    elif a.cmd == "rate":
        rec = pl.rate(a.recipe_id, a.stars, note=a.note)
        print(f"{rec['name']}: {rec['ratings']['average']:.1f}★")
    elif a.cmd == "keep-sync":
        week = _date(a.week)
        print(
            json.dumps(
                pl.sync_keep(pl.week_for(week) if week else None, a.dry_run),
                indent=1,
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
