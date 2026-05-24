# Weather

Imported from the public ClawHub listing at:

- https://clawhub.ai/steipete/weather

This package is adapted for Serana so the skill can be executed as a local Python runtime package instead of only living as instruction text.

## Runtime intent

The original ClawHub skill documents two free weather sources with no API key:

- `wttr.in` as the primary source
- `Open-Meteo` as a fallback

## Tools

- `get_current_weather`
- `get_forecast`

## Guidance

- Prefer `wttr.in` first because it is lightweight and works well for city-level weather lookups.
- Fall back to `Open-Meteo` if the primary source fails or returns incomplete data.
- Be explicit about location and units in the final answer.
- Keep the response short and practical unless the user asks for more detail.
