# Note Manager

Use this package when the user wants to store, retrieve, search, update, or delete lightweight local notes.

## Tools

- `create_note`
- `get_note`
- `search_notes`
- `update_note`
- `delete_note`
- `list_notes`

## Guidance

- Treat this package as a local memory helper, not a durable cloud notebook.
- When creating notes, preserve the user’s wording when it matters.
- When searching, summarize the matching notes instead of dumping raw internal structures.
