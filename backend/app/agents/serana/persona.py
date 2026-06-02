from functools import lru_cache
from pathlib import Path

from app.core.logger import get_logger


logger = get_logger(__name__)

PERSONA_PATH = Path(__file__).with_name("persona.md")


@lru_cache(maxsize=1)
def load_serana_persona() -> str:
    if not PERSONA_PATH.exists():
        logger.warning("Serana persona file not found: %s", PERSONA_PATH)
        return "You are Serana, a calm and reliable private housekeeper."
    content = PERSONA_PATH.read_text(encoding="utf-8").strip()
    return content or "You are Serana, a calm and reliable private housekeeper."


def initialize_serana_persona() -> str:
    persona = load_serana_persona()
    logger.info("Loaded Serana persona from %s", PERSONA_PATH)
    return persona


def build_serana_system_prompt(
    task_instruction: str,
    *,
    include_instruction_skills: bool = False,
) -> str:
    prompt = (
        f"{load_serana_persona()}\n\n"
        f"## Current task\n"
        f"{task_instruction}"
    )
    if include_instruction_skills:
        prompt += (
            "\n\n## Installed instruction skills\n"
            "If installed instruction skills are relevant, let them shape your behavior and output, "
            "but do not mention internal skill names unless the user explicitly asks about the system."
        )
    return prompt
