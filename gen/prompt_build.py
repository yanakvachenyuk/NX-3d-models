"""Сборка system prompt + роутер addon-файлов по запросу."""
from __future__ import annotations

from pathlib import Path

from .config import PROMPTS_DIR, SYSTEM_BASE
from .library_api import build_library_description, read_text


# ---------------------------------------------------------------------------
# Роутер: по ключевым словам подмешиваются ТОЛЬКО нужные куски промпта.
# База (system_base.txt) — всегда.
# Addon-файлы — только если запрос «похож» на этот класс задач.
# ---------------------------------------------------------------------------

# (имя файла addon, ключевые слова в lower)
_ADDON_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "addon_face_boss.txt",
        (
            "босс", "бобыш", "плашмя", "верхн", "нижн", "сверху", "снизу",
            "на грани", "center_frame", "левее", "правее", "смещен",
        ),
    ),
    (
        "addon_wall.txt",
        ("стенк", "борт", "вдоль ребра", "attach_plate", "на всё ребро", "во всю"),
    ),
    (
        "addon_side_attach.txt",
        (
            "сбоку", "пристрой", "к ребру", "наружу", "от ребра",
            "прилив", "рядом с", "anchor",
        ),
    ),
    (
        "addon_plate_holes.txt",
        ("отверст", "дыр", "в ряд", "по углам", "holes_in_row"),
    ),
    (
        "addon_fillet_union.txt",
        (
            "скругл", "fillet", "объедин", "единое тело", "шов",
            "слить", "склеить",
        ),
    ),
]


def select_prompt_addons(user_request: str) -> list[Path]:
    """
    Возвращает список путей к addon-файлам, которые подходят к запросу.
    Несуществующие файлы пропускаются (можно внедрять аддоны постепенно).
    """
    t = user_request.lower()
    chosen: list[Path] = []
    for filename, keywords in _ADDON_RULES:
        if any(k in t for k in keywords):
            path = PROMPTS_DIR / filename
            if path.is_file():
                chosen.append(path)
    return chosen

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
    Роутер select_prompt_addons НЕ используется.
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

    # API: в addon_environment_api уже есть «ПОЛНЫЙ СПИСОК».
    # Если оставить и library — будет дубль. Можно временно выключить:
    # library = build_library_description()
    # if library:
    #     parts.append(library)

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