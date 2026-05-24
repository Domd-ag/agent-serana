# Phase 3: Browser Tools

## Goal

Support browser-assisted tasks through tool integrations that can inspect or operate on web content.

## Current Status

This area is still a lower-priority extension compared with the backend orchestration and audit work that is already implemented.

## Intended Direction

- browser navigation support
- page inspection
- action execution
- screenshot and file handoff patterns

## Design Constraints

- keep browser actions visible in audit traces
- align any browser tooling with the personal, self-hosted deployment model
- avoid introducing complexity that weakens the current core backend flows
