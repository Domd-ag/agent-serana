# Serana Product Requirements

## Product Positioning

Serana is a personal, self-hosted AI assistant for goal execution, delegated task handling, memory-assisted conversations, and local debugging visibility.

This product is intentionally aimed at single-user deployment. It does not optimize for accounts, teams, or commercial SaaS requirements.

## Product Goals

- turn natural-language requests into actionable plans
- preserve useful memory between interactions
- route complex work through specialized sub-agents
- keep execution visible through trace and audit tools
- provide a mobile client for daily use

## Non-Goals

- multi-user account systems
- enterprise access control
- billing, tenancy, or commercial operations
- heavy cloud-only assumptions

## Core User Scenarios

### 1. Conversational help

The user sends a message and receives either a direct answer or a delegated answer backed by agent coordination and memory context.

### 2. Goal planning

The user describes a goal and receives structured subtasks, progress tracking, and execution traces.

### 3. Personal memory

The system stores preferences, facts, and conversation-relevant history that can be reused in later interactions.

### 4. Local extensibility

The user adds local skill packages to expand what the assistant can do.

### 5. Debug visibility

The user can inspect audit records, timelines, and debug summaries when behavior needs explanation.

## Functional Requirements

### Chat

- create or reuse chat sessions
- persist messages
- support memory-assisted response generation
- support direct and delegated execution modes
- store thinking blocks and tool traces

### Goals

- create goals
- plan subtasks
- update subtask state
- compute overall progress
- expose planning summary and execution history

### Agents

- support `Serana` and `Forge`
- allow pooled `Forge` instances
- let Serana classify tasks and choose delegation patterns
- support retries and parallel Forge dispatch in delegated work

### Memory

- store profile facts
- retrieve recent and relevant context
- inject memory into chat and planning

### Skills

- discover skill packages from local storage
- validate and load package metadata
- expose installed tools to the backend runtime

### Audit and Debug

- write audit records for chat, goals, and agent execution
- support filtered queries
- support timeline aggregation
- support per-entity debug summaries

## Quality Goals

- reliable local startup
- readable traces for debugging
- stable API contracts for the Android client
- documentation that matches the implemented codebase

## Current Release Scope

The current repository contains a strong backend prototype with real orchestration and audit capabilities. The Android client exists but still trails the backend in completeness.
