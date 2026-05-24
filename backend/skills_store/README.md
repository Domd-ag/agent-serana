# Skill Store

This directory contains local skill packages that can be discovered and loaded by the backend skill manager.

## Purpose

Skill packages extend the backend with reusable local tools. Each package lives in its own directory and exposes metadata through `skill.json`, plus human-readable guidance in `SKILL.md`.

## Current Local Packages

- `calculator`
- `time_manager`
- `note_manager`
- `data_operations`
- `weather`

The repository intentionally excludes simulated or mock external-service skills.

## Expected Package Layout

```text
skill_name/
+-- SKILL.md
+-- skill.json
+-- __init__.py
```

## Minimal Package Metadata

```json
{
  "name": "skill_name",
  "version": "1.0.0",
  "description": "Short package description",
  "author": "Author name",
  "format": "sebastian_package",
  "runtime": "python",
  "instruction_file": "SKILL.md",
  "entrypoint": "__init__.py",
  "agent_type": "all",
  "max_instances": 3,
  "tools": [
    {
      "name": "tool_name",
      "description": "Tool description",
      "input_schema": {
        "type": "object",
        "properties": {
          "param": {
            "type": "string",
            "description": "Parameter description"
          }
        },
        "required": ["param"]
      }
    }
  ]
}
```

## Minimal Skill Guidance

```md
# Skill Name

Use this skill when the user needs a specific local capability.

## Tools

- `tool_name`
```

## Minimal Python Runtime

```python
from typing import Any, Dict


async def tool_name(param: str) -> Dict[str, Any]:
    return {"result": param}
```

## Related Docs

- [Backend Guide](../README.md)
- [Architecture](../../docs/Architecture.md)
