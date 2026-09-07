"""Цикл генерации: prompt → ollama/gemini → validate → save."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .config import LOG_DIR, OUTPUT_FILE, RESULT_PREFIX, cleanup_old_logs
from .ollama_client import generate
from .prompt_build import build_prompt, MAX_HISTORY_TURNS  # MAX_HISTORY_TURNS переехал в prompt_build.py
from .validate import validate_code

# 3 попытки × 400с таймаут = максимум 1200с внутри одного вызова
# run_generation. Согласовано с subprocess.run(..., timeout=1400) в new_ui.py —
# оставляем ~200с запаса на build_prompt/validate/IO.
DEFAULT_MAX_ATTEMPTS = 3


def save_prompt_log(prompt: str) -> Path:
    cleanup_old_logs()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = LOG_DIR / f"{timestamp}.txt"
    logfile.write_text(prompt, encoding="utf-8")
    return logfile


def save_result(code: str) -> Path:
    OUTPUT_FILE.write_text(RESULT_PREFIX + code, encoding="utf-8")
    return OUTPUT_FILE


def _retry_prompt(
    base_prompt: str,
    error_kind: str,
    error_text: str,
    previous_code: str | None = None,
) -> str:
    code_block = ""
    if previous_code:
        code_block = (
            "\nТВОЙ ПРЕДЫДУЩИЙ (ошибочный) КОД, который нужно починить:\n"
            "--------------------------------------------------------------------------------\n"
            f"{previous_code}\n"
            "--------------------------------------------------------------------------------\n"
        )
    return (
        f"{base_prompt}\n\n"
        "================================================================================\n"
        f"ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ НЕВАЛИДЕН ({error_kind})\n"
        "================================================================================\n"
        f"{code_block}\n"
        f"Ошибка: {error_text}\n\n"
        "ВАЖНО: почини именно ЭТУ ошибку в СВОЁМ предыдущем коде, минимально "
        "его изменив. НЕ заменяй геометрическую фигуру, паттерн присоединения "
        "или общий подход на другой (например, Parallelogram вместо Triangle, "
        "или center_frame вместо anchor), если это не было причиной ошибки — "
        "источник ошибки почти всегда в одном конкретном вызове API, а не в "
        "выборе формы или паттерна. Требования исходного USER REQUEST "
        "(включая форму детали, тип пристроя и т.д.) остаются в силе без изменений.\n\n"
        "Сгенерируй код заново, полностью, с учётом этой ошибки. "
        "Помни: только исполняемый Python-код, без ``` и без import/session/workPart.\n"
        "Идентичный код, возвращённый повторно без единого изменения,"
        "ЗАПРЕЩЁН — это означает, что причина ошибки не найдена. Прежде чем"
        "выдать ответ, явно укажи (в комментарии над изменённой строкой),"
        "какую именно строку ты изменил и почему, по сравнению с предыдущей"
        "попыткой."
    )


def run_generation(
    user_request: str,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    external_error: str | None = None,
    external_previous_code: str | None = None,
    conversation_history: list[dict] | None = None,
) -> Path:
    """
    external_error / external_previous_code — ошибка исполнения в NX и
    код, который её вызвал, из ПРЕДЫДУЩЕГО вызова этой функции (из
    отдельного процесса new_ui.py). Если переданы, учитываются сразу
    в первой же попытке генерации в этом вызове.

    conversation_history — список предыдущих успешных турнов ЭТОЙ ЖЕ
    "сессии" (см. toggle "Отправить в тот же чат"), вида
    [{"request": "...", "code": "..."}, ...]. Если передан и непуст,
    вставляется build_prompt'ом ДО USER REQUEST, так что оба механизма
    (история и external_error-ретрай) работают одновременно и
    независимо друг от друга.
    """
    log_lines: list[str] = []
    base_prompt = build_prompt(user_request, history=conversation_history)

    if conversation_history:
        log_lines.append(
            f"Учитываю контекст диалога: {len(conversation_history)} предыдущих турна(ов)"
        )

    if external_error:
        current_prompt = _retry_prompt(
            base_prompt,
            "ошибка выполнения в NX (предыдущий запуск)",
            external_error,
            previous_code=external_previous_code,
        )
        log_lines.append(f"Учитываю ошибку предыдущего запуска в NX: {external_error}")
    else:
        current_prompt = base_prompt

    # Лог пишем ПОСЛЕ того, как в base_prompt подмешаны history/error —
    # иначе в сохранённом .txt не видно, что реально ушло модели на 1-ю попытку.
    save_prompt_log(current_prompt)

    last_error = None
    last_code: str | None = None

    for attempt in range(1, max_attempts + 1):
        log_lines.append(f"Попытка {attempt} из {max_attempts}")
        code = generate(current_prompt)
        error = validate_code(code, user_request)

        if error is None:
            log_lines.append("✅ Статическая валидация пройдена")
            return save_result(code)

        last_error = error
        last_code = code
        log_lines.append(f"❌ Ошибка статической валидации: {error}")
        current_prompt = _retry_prompt(
            base_prompt, "статическая валидация", error, previous_code=code
        )

    if last_code:
        debug_file = LOG_DIR / "last_failed_code.py"
        debug_file.write_text(last_code, encoding="utf-8")
        log_lines.append(f"Код последней неудачной попытки сохранён: {debug_file}")

    raise RuntimeError(
        f"Не удалось получить статически валидный код за {max_attempts} попыток.\n"
        "Подробный лог:\n" + "\n".join(log_lines) + f"\nПоследняя ошибка: {last_error}"
    )


def run_console():
    from .config import LIBRARY_DIR, LLM_PROVIDERS, OUTPUT_FILE
    import requests

    print("=" * 80)
    print("NX AI Generator (консоль)")
    print("=" * 80)
    print(f"Providers: {' -> '.join(LLM_PROVIDERS)}")
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