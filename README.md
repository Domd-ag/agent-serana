# Serana

Serana is a personal AI assistant system built for self-hosted use. It combines a FastAPI backend, a three-layer agent runtime, persistent memory, audit trails, and an Android client prototype.

## Project Status

The backend is in a usable prototype-to-product transition state:

- core chat and goal flows are implemented
- `Serana -> Aide -> Forge` orchestration is active
- complexity routing, delegation, batching, retries, and audit tracing are implemented
- debug and audit APIs are available
- the Android client is partially integrated and still evolving

This repository is optimized for personal deployment rather than multi-user or commercial use.

## Repository Layout

```text
.
+-- backend/
|   +-- app/
|   |   +-- api/
|   |   +-- agents/
|   |   +-- core/
|   |   +-- memory/
|   |   +-- skills/
|   |   +-- main.py
|   +-- skills_store/
|   +-- test_api_flows.py
|   +-- requirements.txt
|   +-- README.md
+-- docs/
|   +-- PRD.md
|   +-- Architecture.md
|   +-- DEVELOPMENT_PLAN.md
|   +-- PHASE1_AGENT_SYSTEM.md
|   +-- PHASE2_SKILL_SYSTEM.md
|   +-- PHASE3_BROWSER_TOOLS.md
|   +-- PHASE4_MEMORY_SYSTEM.md
|   +-- PROJECT_SUMMARY.md
+-- frontend-android/
|   +-- app/
|   +-- README.md
+-- PROJECT_SUMMARY.md
```

## Core Capabilities

- Goal-oriented agent orchestration
- Three-layer agent model with pooled workers
- Chat sessions, stored messages, and debug views
- Goal planning, subtasks, progress tracking, and audit history
- Persistent memory injection for chat and planning
- Skill package loading from the local skill store
- Unified audit records, timelines, and debug summaries

## Quick Start

### Backend

See [backend/README.md](backend/README.md) for the detailed backend guide.

```bash
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open:

- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

### Android

See [frontend-android/README.md](frontend-android/README.md). The Android client is currently managed through Android Studio rather than a checked-in Gradle wrapper.

## Documentation Map

- [Product Requirements](docs/PRD.md)
- [Architecture](docs/Architecture.md)
- [Development Plan](docs/DEVELOPMENT_PLAN.md)
- [Project Summary](docs/PROJECT_SUMMARY.md)
- [Backend Guide](backend/README.md)
- [Backend App Module](backend/app/README.md)
- [Backend API Module](backend/app/api/README.md)
- [Backend Core Module](backend/app/core/README.md)
- [Agent System](backend/app/agents/README.md)
- [Android Client](frontend-android/README.md)

## Current Priorities

- continue polishing failure-path behavior and tests
- improve Android integration and streaming UI
- keep documentation aligned with the implemented backend behavior

## License

MIT
