"""Цикл генерации: prompt → ollama → validate → save."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import LOG_DIR, OUTPUT_FILE, RESULT_PREFIX
from .ollama_client import generate
from .prompt_build import build_prompt
from .validate import validate_code


def save_prompt_log(prompt: str) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = LOG_DIR / f"{timestamp}.txt"
    logfile.write_text(prompt, encoding="utf-8")
    return logfile


def save_result(code: str) -> Path:
    OUTPUT_FILE.write_text(RESULT_PREFIX + code, encoding="utf-8")
    return OUTPUT_FILE


def run_generation(user_request: str, max_attempts: int = 5) -> Path:
    log_lines = []                     # <-- собираем лог
    prompt = build_prompt(user_request)
    save_prompt_log(prompt)

    last_error = None
    current_prompt = prompt

    for attempt in range(1, max_attempts + 1):
        log_lines.append(f"Попытка {attempt} из {max_attempts}")
        code = generate(current_prompt)
        error = validate_code(code, user_request)

        if error is None:
            log_lines.append("✅ Валидация пройдена")
            # в случае успеха лог не выводим, но можем сохранить для отладки
            return save_result(code)

        last_error = error
        log_lines.append(f"❌ Ошибка валидации: {error}")
        current_prompt = (
            f"{prompt}\n\n"
            "================================================================================\n"
            "ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ НЕВАЛИДЕН\n"
            "================================================================================\n\n"
            f"Ошибка: {error}\n\n"
            "Сгенерируй код заново, полностью, с учётом этой ошибки. "
            "Помни: только исполняемый Python-код, без ``` и без import/session/workPart.\n"
        )

    # Если все попытки неудачны – выбрасываем исключение с полным логом
    raise RuntimeError(
        f"Не удалось получить валидный код за {max_attempts} попыток.\n"
        "Подробный лог:\n" + "\n".join(log_lines) + f"\nПоследняя ошибка: {last_error}"
    )


def run_console():
    from .config import LIBRARY_DIR, MODEL, OUTPUT_FILE
    import requests

    print("=" * 80)
    print("NX AI Generator (консоль)")
    print("=" * 80)
    print(f"Model   : {MODEL}")
    print(f"Library : {LIBRARY_DIR}")
    print(f"Output  : {OUTPUT_FILE}")
    print()

    while True:
        print("-" * 80)
        user_request = input("Запрос (пустая строка для выхода):\n> ").strip()
        if not user_request:
            break
        try:
            print("Генерация...")
            output_file = run_generation(user_request)
            print(f"Готово: {output_file}\n")
        except requests.exceptions.ConnectionError:
            print("ОШИБКА: не могу подключиться к Ollama. Запустите `ollama serve`.\n")
        except requests.exceptions.Timeout:
            print("ОШИБКА: превышено время ожидания генерации.\n")
        except Exception as e:
            print(f"ОШИБКА: {e}\n")