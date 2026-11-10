---
name: meal-planner
description: Use for anything about this household's dinners, recipes, grocery deals at Costco, Safeway or Calgary Co-op, or the Google Keep shopping list. Plans and edits the week with the meal-planner tools instead of reasoning it out in chat.
---

# Meal planner

The `meal-planner` MCP tools do the work. The planner already knows the calendars, this week's
deals, the pantry and what the household likes, so let it decide and keep chat short.

## Common asks

- "What's for dinner?" / "What's the plan?" → `get_week`. Mention tonight's cook and start time.
- "Plan next week" → `plan_week`. Kept dinners stay. Then offer `send_list_to_keep`.
- "Not salmon on Tuesday" → `swap_dinner` with that date. With a dish in mind, `find_recipes`
  first and pass its `recipe_id`.
- "We loved the curry" / "never again" → `rate_dinner` (5 = loved, 1 = never again). This is how
  it learns; encourage a quick rating after dinners.
- "Add this recipe" + a link → `add_recipe_from_link`.
- "Any deals on chicken?" → `deals` with a query; `check_flyers` only if nothing is saved this week.
- "Put it on the list" → `send_list_to_keep`. Use `dry_run` first if the person is unsure.

## Rules

- Don't invent recipes, prices, store hours or anyone's schedule. If the tools don't know, say so.
- Explain choices with the reasons the planner gives (deal, liked, who's free), briefly.
- One or two tool calls per ask is normal. Don't loop over days or recipes in chat.
