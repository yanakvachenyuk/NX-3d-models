"""
Использование:
    python generate.py "<user_request>"
    python generate.py "<user_request>" "<путь_к_json_файлу_с_контекстом>"

Файл контекста — JSON, содержащий ЛЮБОЙ (или несколько) из ключей:
    {
        "error": "TypeError: ...",     # ошибка исполнения в NX на предыдущей попытке
        "code": "base = ...\\n...",    # код, который был реально исполнен и вызвал ошибку
        "history": [                    # история "того же чата" (toggle в new_ui.py)
            {"request": "...", "code": "..."},
            ...
        ]
    }

"code" (в паре с "error") — это код, который был реально исполнен в NX на
предыдущей попытке и вызвал ошибку. Без него модель не видит, что она
написала, и вынуждена угадывать заново — на практике это приводило к тому,
что модель подменяла саму форму детали, лишь бы не упасть повторно.

"history" — список предыдущих УСПЕШНЫХ запросов этой же "сессии" (когда в
UI включён переключатель "Отправить в тот же чат"), чтобы новый запрос
рассматривался как продолжение/изменение уже построенной модели.
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from gen.run import run_console, run_generation

if __name__ == "__main__":
    if len(sys.argv) > 1:
        user_request = sys.argv[1]

        external_error = None
        external_previous_code = None
        external_history = None
        if len(sys.argv) > 2:
            context_file = Path(sys.argv[2])
            if context_file.is_file():
                try:
                    data = json.loads(context_file.read_text(encoding="utf-8", errors="replace"))
                    external_error = data.get("error")
                    external_previous_code = data.get("code")
                    external_history = data.get("history")
                except json.JSONDecodeError:
                    # обратная совместимость: файл со старым форматом (просто текст ошибки)
                    external_error = context_file.read_text(encoding="utf-8", errors="replace").strip()

        try:
            path = run_generation(
                user_request,
                external_error=external_error or None,
                external_previous_code=external_previous_code or None,
                conversation_history=external_history or None,
            )
            print(f"OK:{path}")
        except Exception as e:
            print(str(e), file=sys.stderr)
            sys.exit(1)
    else:
        run_console()