"""Сборка system prompt из фиксированного набора файлов."""
from __future__ import annotations

from .config import PROMPTS_DIR
from .library_api import read_text


PROMPT_ORDER = [
    "system_base.txt",
    "addon_mapping.txt",
    "addon_checklist.txt",
    "addon_anti_examples.txt",
    "addon_hard_rules.txt",
    "addon_environment_api.txt",
    "addon_examples.txt",
]


def build_prompt(user_request: str) -> str:
    """
    Собирает финальный промпт:
      1) все куски промпта по PROMPT_ORDER (всегда целиком)
      2) USER REQUEST
    """
    parts = []
    for name in PROMPT_ORDER:
        path = PROMPTS_DIR / name
        if path.is_file():
            text = read_text(path).strip()
            if text:
                parts.append(text)

    # fallback, если новых файлов ещё нет
    if not parts:
        legacy = PROMPTS_DIR / "system_prompt.txt"
        if legacy.is_file():
            parts.append(read_text(legacy).strip())

    parts.append(
        "================================================================================\n"
        "USER REQUEST\n"
        "================================================================================\n\n"
        f"{user_request}\n\n"
        "================================================================================\n"
        "IMPORTANT\n\n"
        "Return ONLY executable Python code.\n"
        "Do NOT explain anything.\n"
        "Do NOT use Markdown.\n"
        "Do NOT wrap the code with ```.\n"
        "The answer must consist ONLY of Python code.\n"
        "================================================================================"
    )
    return "\n\n".join(parts)