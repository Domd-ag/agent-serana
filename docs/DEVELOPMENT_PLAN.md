# Serana Development Plan

## Planning Principle

This project should keep prioritizing reliable personal use over broad platform ambitions. The backend already carries most of the implementation weight, so future work should preserve that momentum and keep the documentation aligned with reality.

## Completed Foundation

- backend API surface for chat, goals, memory, skills, audit, and LLM configuration
- chief-worker agent runtime
- delegated execution with complexity routing
- Serana-coordinated pooled `Forge` instances
- unified audit records and debug endpoints

## Next Priorities

### 1. Failure-path hardening

- add more tests for fallback and degraded execution paths
- keep exception handling explicit and observable
- continue reducing silent fallback behavior

### 2. Android parity

- improve session history handling
- add richer debug visibility
- support more complete streaming behavior

### 3. Skill and tool maturity

- expand the local skill store
- improve skill validation and developer guidance
- document recommended tool patterns for `Forge`

### 4. Documentation maintenance

- keep module README files aligned with backend behavior
- update phase docs as implementation changes

## Deferred Work

- formal migration tooling
- broader frontend polish
- advanced browser tooling expansion

## Success Criteria

- backend changes remain covered by automated tests
- docs remain readable and accurate
- the Android client can exercise the main backend flows without protocol drift
