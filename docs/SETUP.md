# Setup

Everything runs on Prime next to Daily Dashboard. Needs Python 3.12+ and
[uv](https://docs.astral.sh/uv/).

## 1. The household

```powershell
copy planner.example.toml planner.toml
```

Edit `planner.toml`:

- **members**: everyone who might cook, with `max_minutes` for a weeknight.
- **dinner**: when dinner is on the table and the earliest anyone starts cooking.
- **deals.postal_code**: your postal code, so the flyers are your local stores'.
- **deals.stores**: Flipp merchant names, matched loosely. Run `uv run meals deals` and look at
  the Deals tab to check the names match (for example "Calgary Co-op").
- **kitchen.pantry** and **kitchen.avoid**.

## 2. Calendars

For each person, in Google Calendar on the web: Settings → the calendar → **Integrate calendar**
→ copy **Secret address in iCal format**, and add it to that person's `calendars` list. Add
every calendar that matters (work, kids' activities, a shared family calendar). No Google
sign-in is needed, and the last copy is kept so planning still works offline.

All-day events and events marked "Free" don't block cooking.

## 3. Deals

`uv run meals deals` searches Flipp for every ingredient your recipes use (and the `watch` list),
keeps what's on sale at your stores, and drops expired deals. It takes about a minute and
runs as part of `meals weekly`.

Flipp is the app the flyers are published to; its search isn't an official API. If it changes,
planning carries on without deals, and you can still add deals by hand on the Deals tab or with
`uv run meals add-deal Costco "Kirkland chicken thighs" --price 12.99 --until 2026-11-30`.

Costco often puts its warehouse savings in a monthly coupon book that isn't in Flipp. Adding the
few items you care about by hand works well.

## 4. Google Keep

The planner uses the Keep sign-in Daily Dashboard already saved (`uv run dash keep-auth` in
Daily Dashboard), so there is nothing new to set up as long as Daily Dashboard's Keep card works.
If Daily Dashboard reads the email from `.env` rather than Credential Manager, put the same
address in this repo's `.env`:

```
MEALS_KEEP_EMAIL=you@gmail.com
```

It writes to the list named in `keep.list_title` (the one Google Home adds to). Every item it
adds ends in 🍽, and it only ever changes 🍽 items that aren't ticked. Your own items and Google
Home's are never touched, and something already on the list isn't added twice.

Try `uv run meals keep-sync --dry-run` first to see what it would do.

## 5. Weekly run and starting with Windows

```powershell
$repo = (Get-Location).Path
schtasks /Create /TN "Meal Planner" /SC ONLOGON /RL LIMITED /F `
  /TR "`"$repo\start.bat`" --no-browser"
schtasks /Create /TN "Meal Planner weekly" /SC WEEKLY /D SAT /ST 08:00 /F `
  /TR "cmd /c cd /d `"$repo`" && uv run meals weekly"
```

Saturday morning it checks the flyers (most change on Thursday or Friday), plans Monday to
Sunday, and puts the list on Keep. Re-plan any time from the page; kept dinners stay.

## 6. Claude

The MCP server gives Claude about a dozen small tools (`get_week`, `plan_week`, `swap_dinner`,
`rate_dinner`, `find_recipes`, `deals`, `send_list_to_keep`, …). The planner does the work, so
a chat stays short and on topic.

**Claude Code or Cowork:** install the plugin in `plugin/` (it starts the MCP server and adds a
skill with the house rules):

```powershell
claude plugin install .\plugin
```

**Claude Desktop:** Settings → Developer → Edit config, and add:

```json
{
  "mcpServers": {
    "meal-planner": {
      "command": "uv",
      "args": ["--directory", "C:\\path\\to\\meal-planner", "run", "meals", "mcp"]
    }
  }
}
```

## 7. Daily Dashboard

Daily Dashboard's **Meals** card reads `GET http://127.0.0.1:8200/api/dashboard`: tonight's
dinner, who's cooking and when to start, tomorrow, the week, the list size and savings, and
dinners waiting for a rating. Set `DASH_MEALS_URL` in Daily Dashboard's `.env` if the planner
runs somewhere other than `http://127.0.0.1:8200`.

## 8. Your phone

Same as Daily Dashboard: with Tailscale, serve port 8200 too
(`tailscale serve --bg --https=8443 http://127.0.0.1:8200`). The page is built phone-first.
