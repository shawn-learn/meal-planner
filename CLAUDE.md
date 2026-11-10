# Meal Planner

Plans a household's week of dinners from calendars, Flipp flyer deals (Costco, Safeway, Calgary
Co-op) and learned tastes, and syncs the shopping list to Google Keep. Runs on Shawn's Windows
PC ("Prime") beside Daily Dashboard, which reads `GET /api/dashboard`.

- The app does the work in plain code: no LLM calls anywhere in `meals/`. Keep it that way.
  Claude talks to it only through the small MCP tools in `meals/mcp_server.py`.
- `meals/service.py` is the one place use cases live; the API, CLI and MCP all call it.
- Keep only ever changes items ending in the marker (🍽) that aren't ticked.
- Google Keep reuses Daily Dashboard's keyring entries (`daily-dashboard` / `keep`, `keep-email`).
- `GET /api/dashboard` is a contract with Daily Dashboard (`dash/sources/meals.py` there): add
  fields freely, don't rename or remove them.
- Checks: `uv run pytest`, `uv run ruff check meals tests`, `uv run ruff format --check meals tests`,
  `uv run mypy`.
