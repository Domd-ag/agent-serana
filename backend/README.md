# Serana Backend

This directory contains the FastAPI backend for Serana. It is the primary runtime for chat, goals, memory, agents, skills, and audit/debug tooling.

## Scope

The backend currently provides:

- chat sessions and message persistence
- goal planning and subtask lifecycle management
- `Serana -> Aide -> Forge` orchestration
- memory retrieval and injection
- local skill package loading
- audit records, timelines, and debug summaries

## Quick Start

### 1. Create a virtual environment

```bash
cd backend
python -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

Create a local `.env` file if you need custom settings. The backend can run with defaults for local development, but LLM-backed behavior requires valid model configuration.

### 4. Run the server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open:

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

## Important Endpoints

### System

- `GET /health`
- `GET /`

### Chat

- `POST /api/v1/chat/message`
- `GET /api/v1/chat/sessions`
- `GET /api/v1/chat/sessions/{session_id}/messages`
- `GET /api/v1/chat/sessions/{session_id}/audit`
- `GET /api/v1/chat/sessions/{session_id}/debug`

### Goals

- `POST /api/v1/goals`
- `GET /api/v1/goals`
- `GET /api/v1/goals/{goal_id}`
- `POST /api/v1/goals/{goal_id}/start`
- `POST /api/v1/goals/{goal_id}/subtasks/{subtask_id}`
- `GET /api/v1/goals/{goal_id}/events`
- `GET /api/v1/goals/{goal_id}/audit`
- `GET /api/v1/goals/{goal_id}/debug`

### Memory

- `GET /api/v1/memory/facts`
- `POST /api/v1/memory/facts`
- `DELETE /api/v1/memory/facts/{fact_id}`
- `POST /api/v1/memory/search`

### LLM

- `GET /api/v1/llm/config`
- `POST /api/v1/llm/config`
- `DELETE /api/v1/llm/config`
- `GET /api/v1/llm/mode`
- `POST /api/v1/llm/mode`

### Audit

- `GET /api/v1/audit`
- `GET /api/v1/audit/timeline`
- `GET /api/v1/audit/debug-summary`

## Project Layout

```text
backend/
+-- app/
|   +-- api/
|   +-- agents/
|   +-- core/
|   +-- memory/
|   +-- skills/
|   +-- main.py
+-- skills_store/
+-- test_api_flows.py
+-- requirements.txt
+-- README.md
```

## Testing

Run the current backend regression suite with:

```bash
python -m unittest test_api_flows
```

## Notes

- The backend is designed for personal deployment and uses a default local user context.
- SQLite is the default local database.
- Several tables use lightweight startup migrations rather than a full external migration framework.

## Related Docs

- [App Module Guide](app/README.md)
- [API Module Guide](app/api/README.md)
- [Core Module Guide](app/core/README.md)
- [Agent System Guide](app/agents/README.md)
- [Architecture](../docs/Architecture.md)
