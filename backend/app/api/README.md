# Backend API Module

This directory contains the FastAPI route modules for the Serana backend.

## Structure

```text
api/
+-- __init__.py
+-- agents.py
+-- audit.py
+-- chat.py
+-- goals.py
+-- llm.py
+-- memory.py
+-- skills.py
```

## Router Overview

### `llm.py`

Manages LLM configuration and active mode selection.

Typical endpoints:

- `GET /api/v1/llm/config`
- `POST /api/v1/llm/config`
- `DELETE /api/v1/llm/config`
- `GET /api/v1/llm/mode`
- `POST /api/v1/llm/mode`

### `chat.py`

Handles chat sessions, message generation, history retrieval, audit access, and debug views.

Typical endpoints:

- `POST /api/v1/chat/message`
- `GET /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{session_id}/messages`
- `GET /api/v1/chat/sessions/{session_id}/audit`
- `GET /api/v1/chat/sessions/{session_id}/debug`

### `memory.py`

Manages profile facts and memory search.

Typical endpoints:

- `GET /api/v1/memory/facts`
- `POST /api/v1/memory/facts`
- `DELETE /api/v1/memory/facts/{fact_id}`
- `POST /api/v1/memory/search`

### `goals.py`

Handles goal planning, progress updates, events, audit access, and debug views.

Typical endpoints:

- `POST /api/v1/goals`
- `GET /api/v1/goals`
- `GET /api/v1/goals/{goal_id}`
- `POST /api/v1/goals/{goal_id}/start`
- `POST /api/v1/goals/{goal_id}/subtasks/{subtask_id}`
- `GET /api/v1/goals/{goal_id}/events`
- `GET /api/v1/goals/{goal_id}/audit`
- `GET /api/v1/goals/{goal_id}/debug`

### `agents.py`

Exposes current agent status and session history.

### `skills.py`

Exposes skill-package management operations.

### `audit.py`

Provides cross-entity audit filtering, timelines, and summarized debug insights.

## Guidelines

- keep route handlers focused on HTTP concerns
- validate payloads through `core/schemas.py`
- store shared business logic in the agent, memory, skill, or core modules
- keep responses compatible with the current Android and debug tooling needs

## Related Docs

- [Backend App Module](../README.md)
- [Backend Core Module](../core/README.md)
- [Architecture](../../../docs/Architecture.md)
