from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import requests


# ==============================================================================
# НАСТРОЙКИ
# ==============================================================================

PROJECT = Path(__file__).resolve().parent

LIBRARY_DIR = PROJECT / "nx_primitives"

PROMPTS_DIR = PROJECT / "prompts"

GENERATED_DIR = PROJECT / "generated"

LOG_DIR = PROJECT / "logs"

SYSTEM_PROMPT = PROMPTS_DIR / "system_prompt.txt"

OUTPUT_FILE = GENERATED_DIR / "result.py"

OLLAMA_URL = "http://localhost:11434/api/generate"

MODEL = "qwen2.5-coder:7b"


# ==============================================================================
# ПРЕФИКС RESULT.PY
# ==============================================================================

RESULT_PREFIX = """import sys
import os

project_path = r'c:\\Users\\user\\Desktop\\AI_3D_NX_python_optimization_project'

if project_path not in sys.path:
    sys.path.insert(0, project_path)

import NXOpen
from nx_primitives import *

theSession = NXOpen.Session.GetSession()
workPart = theSession.Parts.Work
"""


# ==============================================================================
# СОЗДАНИЕ ПАПОК
# ==============================================================================

GENERATED_DIR.mkdir(exist_ok=True)

LOG_DIR.mkdir(exist_ok=True)


# ==============================================================================
# ЧТЕНИЕ ФАЙЛОВ
# ==============================================================================

def read_text(path: Path) -> str:
    return path.read_text(
        encoding="utf-8",
        errors="ignore"
    )


# ==============================================================================
# СБОРКА БИБЛИОТЕКИ
# ==============================================================================

def build_library_description() -> str:
    """
    Превращает всю папку nx_primitives в красивый текст.

    ================= FILE: shapes.py =================

    ...

    ================= FILE: geometry.py =================

    ...
    """

    parts = []

    parts.append(
        "=" * 80
    )

    parts.append(
        "LIBRARY SOURCE CODE"
    )

    parts.append(
        "Everything below is available for use."
    )

    parts.append(
        "Use ONLY classes/functions that exist."
    )

    parts.append(
        "=" * 80
    )

    parts.append("")

    py_files = sorted(
        LIBRARY_DIR.rglob("*.py")
    )

    for file in py_files:

        relative = file.relative_to(
            LIBRARY_DIR
        ).as_posix()

        code = read_text(file).rstrip()

        parts.append(
            f"{'=' * 25} FILE: {relative} {'=' * 25}"
        )

        parts.append("")

        parts.append(code)

        parts.append("")

    parts.append("=" * 80)

    parts.append("END OF LIBRARY")

    parts.append("=" * 80)

    return "\n".join(parts)


# ==============================================================================
# СБОРКА PROMPT
# ==============================================================================

def build_prompt(user_request: str) -> str:

    system_prompt = read_text(
        SYSTEM_PROMPT
    ).strip()

    library = build_library_description()

    return f"""{system_prompt}


{library}


================================================================================
USER REQUEST
================================================================================

{user_request}


================================================================================
IMPORTANT

Return ONLY executable Python code.

Do NOT explain anything.

Do NOT use Markdown.

Do NOT wrap the code with ```.

The answer must consist ONLY of Python code.

================================================================================
"""


# ==============================================================================
# ЛОГИ
# ==============================================================================

def save_prompt_log(prompt: str):

    timestamp = datetime.now().strftime(
        "%Y-%m-%d_%H-%M-%S"
    )

    logfile = LOG_DIR / f"{timestamp}.txt"

    logfile.write_text(
        prompt,
        encoding="utf-8"
    )


# ==============================================================================
# ОЧИСТКА ОТВЕТА
# ==============================================================================

def cleanup_response(text: str) -> str:

    text = text.strip()

    text = re.sub(
        r"^```python",
        "",
        text,
        flags=re.IGNORECASE
    )

    text = re.sub(
        r"^```",
        "",
        text
    )

    text = re.sub(
        r"```$",
        "",
        text
    )

    return text.strip()


# ==============================================================================
# ЗАПРОС К OLLAMA
# ==============================================================================

def generate(prompt: str) -> str:

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
    }

    response = requests.post(
        OLLAMA_URL,
        json=payload,
        timeout=600
    )

    response.raise_for_status()

    data = response.json()

    if "response" not in data:
        raise RuntimeError(
            "Ollama returned an invalid response."
        )

    return cleanup_response(
        data["response"]
    )

# ==============================================================================
# СОХРАНЕНИЕ RESULT.PY
# ==============================================================================

def save_result(code: str):

    OUTPUT_FILE.write_text(
        RESULT_PREFIX + code,
        encoding="utf-8"
    )


# ==============================================================================
# КРАСИВЫЙ ВЫВОД
# ==============================================================================

def print_header():

    print("=" * 80)
    print("NX AI Generator")
    print("=" * 80)
    print()
    print(f"Model      : {MODEL}")
    print(f"Library    : {LIBRARY_DIR}")
    print(f"Prompt     : {SYSTEM_PROMPT}")
    print(f"Output     : {OUTPUT_FILE}")
    print()


def print_success():

    print()
    print("=" * 80)
    print("Generation completed successfully.")
    print(f"Saved to:\n{OUTPUT_FILE}")
    print("=" * 80)
    print()


# ==============================================================================
# MAIN
# ==============================================================================

def main():

    print_header()

    while True:

        print()
        print("-" * 80)

        user_request = input(
            "Enter your request (empty line to exit):\n> "
        ).strip()

        if not user_request:
            break

        print()
        print("Reading library...")

        prompt = build_prompt(
            user_request
        )

        print(
            f"Prompt size: {len(prompt):,} characters"
        )

        print(
            "Saving prompt log..."
        )

        save_prompt_log(
            prompt
        )

        print(
            "Sending request to Ollama..."
        )

        try:

            code = generate(
                prompt
            )

        except requests.exceptions.ConnectionError:

            print()
            print("ERROR")
            print("-" * 80)
            print("Cannot connect to Ollama.")
            print()
            print(f"Expected server: {OLLAMA_URL}")
            print()
            print("Start Ollama first.")
            print()

            continue

        except requests.exceptions.Timeout:

            print()
            print("ERROR")
            print("-" * 80)
            print("Generation timeout.")
            print()

            continue

        except Exception as e:

            print()
            print("ERROR")
            print("-" * 80)
            print(e)
            print()

            continue

        save_result(
            code
        )

        print_success()


# ==============================================================================
# ENTRY POINT
# ==============================================================================

if __name__ == "__main__":
    main()