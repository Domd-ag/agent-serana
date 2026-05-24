# Serana Agent System

This module implements the three-layer agent runtime used by the backend:

- `Serana`: chief agent
- `Aide`: team lead agent
- `Forge`: worker agent

## Directory Layout

```text
agents/
+-- __init__.py
+-- base.py
+-- agent_limits.json
+-- README.md
+-- serana/
|   +-- __init__.py
|   +-- graph.py
|   +-- nodes.py
|   +-- serana.py
+-- aide/
|   +-- __init__.py
|   +-- aide.py
|   +-- manifest.json
+-- forge/
    +-- __init__.py
    +-- forge.py
    +-- manifest.json
```

## Agent Roles

### Serana

- Path: `serana/`
- Responsibility: analyze requests, decide direct vs delegated execution, coordinate planning, and summarize results
- Implementation: singleton
- Effective instance limit: `1`

### Aide

- Path: `aide/`
- Responsibility: classify delegated work, plan batches, coordinate retries, and hand work to `Forge`
- Effective instance limit: `3`

### Forge

- Path: `forge/`
- Responsibility: execute concrete delegated tasks and choose execution strategy by task type
- Effective instance limit: `5`

## Runtime Behavior

### Complexity Routing

`Serana` decides whether a request should stay local or be delegated.

- `direct`: `Serana` handles the request itself
- `delegated`: `Serana` decomposes the request and hands work to `Aide` and `Forge`

This routing is shared by both chat execution and goal planning flows.

### Delegation Flow

The delegated path follows this structure:

1. `Serana` analyzes the request
2. `Serana` creates subtasks
3. `Serana` builds a delegation plan
4. `Aide` instances coordinate batches of delegated work
5. `Forge` instances execute concrete task batches
6. `Serana` summarizes the result

### Parallel Execution

Delegated subtasks are not handled purely one by one anymore. The current runtime supports:

- dynamic delegation planning
- pooled `Aide` reuse
- pooled `Forge` reuse
- parallel subtask dispatch with slot limits

The effective concurrency is shaped by:

- task complexity
- inferred task type
- number of subtasks
- configured `Aide` and `Forge` limits

### Task-Type Behavior

`Aide` and `Forge` now have distinct responsibilities:

- `Aide` handles classification, batching, and retry coordination
- `Forge` handles task-type strategy selection and concrete execution

Common task-type families include:

- `research`
- `planning`
- `analysis`
- `build`
- `question`
- `general`

## Instance Limits

Agent instance limits are centrally configured in [agent_limits.json](/D:/agent-serana/backend/app/agents/agent_limits.json:1):

```json
{
  "serana": 1,
  "aide": 3,
  "forge": 5
}
```

Notes:

- `Serana` is enforced as a singleton in code, so its effective limit is always `1`.
- `Aide` and `Forge` still keep `max_instances` in their `manifest.json` files, but runtime loading overrides those values with `agent_limits.json`.

## Manifest Files

`Aide` and `Forge` each have a `manifest.json` file for descriptive metadata, skills, and tools.

Example shape:

```json
{
  "name": "Aide",
  "display_name": "Aide",
  "description": "Team lead agent",
  "version": "1.0.0",
  "agent_type": "team_lead",
  "max_instances": 3,
  "skills": [],
  "tools": []
}
```

At runtime, `base.py` loads the manifest and then applies any matching override from `agent_limits.json`.

## How AgentManager Works

`AgentManager` is responsible for:

- loading agent manifests
- applying configured instance limits
- creating `Aide` and `Forge` instances on demand
- reserving idle pooled agents before reuse in concurrent flows
- reusing idle pooled instances when available
- returning the singleton `Serana` instance

In practice:

- `Serana` remains a singleton
- `Aide` instances are pooled and return to `idle` after work finishes
- `Forge` instances are pooled and return to `idle` after work finishes

## Audit and Debug Integration

Agent execution is reflected in the unified backend audit model.

Current traces include:

- `serana_analyze`
- `serana_decompose`
- `serana_delegate`
- `serana_summarize`
- `aide_execute`
- `forge_execute`

These records feed:

- entity audit endpoints
- timeline aggregation
- debug-summary views
- goal and chat debug endpoints

## Configuration Changes

When changing agent counts:

1. Update `agent_limits.json`
2. Keep manifest values aligned for readability
3. Do not increase `serana` above `1` unless the singleton implementation is changed

When changing skills or tools:

1. Update the corresponding `manifest.json`
2. Update the agent implementation if behavior also changes
