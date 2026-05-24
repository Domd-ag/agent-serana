# Time Manager

Use this package when the user needs local time, weekday, date, duration, or timezone conversion information.

## Tools

- `get_current_time`
- `convert_timezone`
- `calculate_duration`
- `get_day_info`

## Guidance

- Prefer this package over free-form model answers for concrete time and date questions.
- Default to `Asia/Shanghai` when the user is asking about the current local time unless they specify another timezone.
- Be explicit about the timezone in the final answer whenever it matters.
