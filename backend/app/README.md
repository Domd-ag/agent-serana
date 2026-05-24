# Backend App Module

This directory contains the main application code for the Serana backend.

## Structure

```text
app/
+-- __init__.py
+-- main.py
+-- api/
+-- agents/
+-- core/
+-- memory/
+-- skills/
```

## Responsibilities

### `main.py`

- creates the FastAPI application
- configures middleware and logging
- registers routers and exception handlers
- initializes the database on startup

### `api/`

Contains route handlers for the public HTTP surface. See [api/README.md](api/README.md).

### `agents/`

Contains the runtime for `Serana`, `Aide`, and `Forge`, including pooling rules and orchestration logic. See [agents/README.md](agents/README.md).

### `core/`

Contains shared infrastructure such as configuration, models, schemas, database access, security helpers, logging, and audit utilities. See [core/README.md](core/README.md).

### `memory/`

Contains memory storage, retrieval, and prompt injection utilities used by chat and goal planning.

### `skills/`

Contains skill-package models, loading, validation, and runtime management.

## Main Runtime Flows

### Chat

1. receive a user message
2. load or create a chat session
3. inject memory context
4. route through `Serana`
5. persist the response and traces
6. expose audit and debug views

### Goals

1. create a goal
2. plan subtasks through `Serana`
3. store planning summary and trace data
4. start and update subtask execution state
5. record events and audit records

## Conventions

- API routes live under `/api/v1`
- shared request and response models live in `core/schemas.py`
- ORM models live in `core/models.py`
- route modules should stay thin and push orchestration into shared services or agent modules

## Related Docs

- [Backend Guide](../README.md)
- [API Module Guide](api/README.md)
- [Core Module Guide](core/README.md)
- [Agent System Guide](agents/README.md)
