# Backend Core Module

This directory contains shared infrastructure used across the backend.

## Structure

```text
core/
+-- __init__.py
+-- audit.py
+-- config.py
+-- database.py
+-- deps.py
+-- exceptions.py
+-- init_db.py
+-- llm_gateway.py
+-- logger.py
+-- models.py
+-- schemas.py
+-- security.py
```

## Module Responsibilities

### `config.py`

Application settings and environment-driven configuration.

### `database.py`

Async SQLAlchemy engine, session factory, and database helpers.

### `models.py`

ORM models for:

- chat sessions and messages
- goals, subtasks, and goal events
- memory facts
- agent sessions
- skill packages
- user LLM configuration
- audit records

### `schemas.py`

Pydantic request and response models for the API surface, audit views, debug views, and internal transport structures.

### `deps.py`

FastAPI dependency helpers, including the default local user context and active LLM configuration lookup.

### `init_db.py`

Database initialization and lightweight startup migrations for local development.

### `llm_gateway.py`

Provider abstraction and configuration handling for LLM access.

### `security.py`

Encryption and decryption helpers for sensitive configuration data.

### `logger.py`

Central logging configuration for the application.

### `audit.py`

Helpers for writing, filtering, summarizing, and aggregating audit records.

### `exceptions.py`

Custom exception types and global exception handlers.

## Design Notes

- the backend is optimized for personal deployment
- shared models and schemas should stay stable because they anchor both APIs and debug tooling
- new cross-cutting behavior should usually land here before being reused elsewhere

## Related Docs

- [Backend Guide](../../README.md)
- [Backend App Module](../README.md)
- [Backend API Module](../api/README.md)
- [Architecture](../../../docs/Architecture.md)
