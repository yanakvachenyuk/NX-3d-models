from __future__ import annotations

import ast
import re
import sys
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

RESULT_PREFIX = f"""import sys
import os

project_path = r'{PROJECT}'

if project_path not in sys.path:
    sys.path.insert(0, project_path)

import NXOpen
from nx_primitives import (
    Triangle,
    Parallelogram,
    Polygon,
    Circle,
    Line,
    Extrude,
    Fillet,
    Union,
    Subtract,
    Intersect,
    Boolean,
    Frame,
    Hide,
    rect_profile,
    attachment_seam,
    edges_after_boolean,
    edges_in_box,
    edges_near,
)

theSession = NXOpen.Session.GetSession()
workPart = theSession.Parts.Work
"""

GENERATED_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)


# ==============================================================================
# ЧТЕНИЕ ФАЙЛОВ / СБОРКА ПРОМПТА
# ==============================================================================

def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _format_args(args: ast.arguments) -> str:
    parts = []
    defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)

    for arg, default in zip(args.args, defaults):
        piece = arg.arg
        if arg.annotation is not None:
            try:
                piece += f": {ast.unparse(arg.annotation)}"
            except Exception:
                pass
        if default is not None:
            try:
                piece += f"={ast.unparse(default)}"
            except Exception:
                piece += "=..."
        parts.append(piece)

    if args.vararg:
        parts.append(f"*{args.vararg.arg}")
    for kwarg, default in zip(args.kwonlyargs, args.kw_defaults):
        piece = kwarg.arg
        if default is not None:
            try:
                piece += f"={ast.unparse(default)}"
            except Exception:
                piece += "=..."
        parts.append(piece)

    return "(" + ", ".join(parts) + ")"


def _first_doc_line(node) -> str | None:
    doc = ast.get_docstring(node)
    if not doc:
        return None
    return doc.strip().splitlines()[0]


def build_library_description() -> str:
    """
    Собирает КРАТКУЮ сводку публичного API - сигнатуры классов/функций
    + первая строка докстринга, БЕЗ реализации (NXOpen-boilerplate там
    только мешает маленькой модели и съедает контекст без пользы).

    Разбирает файлы статически через ast - не импортирует nx_primitives
    (это потянуло бы NXOpen, которого нет в окружении, где запускается
    сам генератор - он работает вне NX, просто пишет result.py на диск).
    """
    init_source = read_text(LIBRARY_DIR / "__init__.py")
    init_tree = ast.parse(init_source)

    public_names: set[str] = set()
    for node in ast.walk(init_tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
        ):
            for elt in node.value.elts:
                if isinstance(elt, ast.Constant):
                    public_names.add(elt.value)

    parts = [
        "=" * 80,
        "PUBLIC API (сигнатуры + краткие описания, без реализации)",
        "Используй ТОЛЬКО то, что здесь перечислено.",
        "=" * 80,
        "",
    ]

    for file in sorted(LIBRARY_DIR.rglob("*.py")):
        if file.name == "__init__.py":
            continue

        tree = ast.parse(read_text(file))

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    node.col_offset == 0 and node.name in public_names:
                parts.append(f"def {node.name}{_format_args(node.args)}")
                doc = _first_doc_line(node)
                if doc:
                    parts.append(f"    # {doc}")
                parts.append("")

            elif isinstance(node, ast.ClassDef) and node.name in public_names:
                parts.append(f"class {node.name}:")
                doc = _first_doc_line(node)
                if doc:
                    parts.append(f"    # {doc}")

                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if item.name.startswith("_") and item.name != "__init__":
                            continue
                        prefix = "def __init__" if item.name == "__init__" else f"def {item.name}"
                        parts.append(f"    {prefix}{_format_args(item.args)}")
                        item_doc = _first_doc_line(item)
                        if item_doc:
                            parts.append(f"        # {item_doc}")
                parts.append("")

    parts.append("=" * 80)
    parts.append("END OF API")
    parts.append("=" * 80)

    return "\n".join(parts)


def build_prompt(user_request: str) -> str:
    system_prompt = read_text(SYSTEM_PROMPT).strip()
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


def save_prompt_log(prompt: str) -> Path:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    logfile = LOG_DIR / f"{timestamp}.txt"
    logfile.write_text(prompt, encoding="utf-8")
    return logfile


def cleanup_response(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```python", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text)
    return text.strip()


def generate(prompt: str) -> str:
    payload = {"model": MODEL, "prompt": prompt, "stream": False}
    # payload = {
    #     "model": MODEL,
    #     "prompt": prompt,
    #     "stream": False,
    #     "options": {
    #         "num_ctx": 16384,  # с запасом под реальный размер вашего промпта
    #     }
    # }
    response = requests.post(OLLAMA_URL, json=payload, timeout=600)
    response.raise_for_status()
    data = response.json()

    if "response" not in data:
        raise RuntimeError("Ollama returned an invalid response.")

    return cleanup_response(data["response"])


def save_result(code: str) -> Path:
    OUTPUT_FILE.write_text(RESULT_PREFIX + code, encoding="utf-8")
    return OUTPUT_FILE


FORBIDDEN_SNIPPETS = (
    "import NXOpen",
    "from nx_primitives import",
    "NXOpen.Session.GetSession",
    "theSession.Parts.Work",
    "```",
)


def validate_code(code: str) -> str | None:
    """Возвращает текст ошибки, если код невалиден, иначе None."""
    try:
        ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e}"

    for snippet in FORBIDDEN_SNIPPETS:
        if snippet in code:
            return (
                f"Код содержит запрещённый фрагмент '{snippet}'. "
                "Session/workPart и импорты уже подставлены снаружи - "
                "не пиши их и не оборачивай ответ в ```."
            )

    return None


def run_generation(user_request: str, max_attempts: int = 3) -> Path:
    """
    Строит промпт, шлёт в Ollama, проверяет синтаксис и запрещённые
    паттерны. Если код невалиден - повторяет запрос (до max_attempts раз),
    добавляя в промпт текст конкретной ошибки, чтобы модель её исправила.
    """
    prompt = build_prompt(user_request)
    save_prompt_log(prompt)

    last_error = None
    current_prompt = prompt

    for attempt in range(1, max_attempts + 1):
        code = generate(current_prompt)
        error = validate_code(code)

        if error is None:
            return save_result(code)

        last_error = error
        current_prompt = (
            f"{prompt}\n\n"
            "================================================================================\n"
            "ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ НЕВАЛИДЕН\n"
            "================================================================================\n\n"
            f"Ошибка: {error}\n\n"
            "Сгенерируй код заново, полностью, с учётом этой ошибки. "
            "Помни: только исполняемый Python-код, без ``` и без import/session/workPart.\n"
        )

    raise RuntimeError(
        f"Не удалось получить валидный код за {max_attempts} попыток. "
        f"Последняя ошибка: {last_error}"
    )


# ==============================================================================
# КОНСОЛЬНЫЙ РЕЖИМ
# ==============================================================================

def run_console():
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


# ==============================================================================
# ПРОСТОЙ GUI (обычное tkinter-окно, БЕЗ NXOpen, запускается отдельным процессом)
# ==============================================================================

def run_gui():
    import tkinter as tk
    from tkinter import scrolledtext, messagebox

    root = tk.Tk()
    root.title("NX AI Generator")
    root.geometry("600x420")

    tk.Label(root, text="Запрос для генерации модели:").pack(anchor="w", padx=8, pady=(8, 0))
    request_box = scrolledtext.ScrolledText(root, height=8)
    request_box.pack(fill="both", padx=8, pady=4, expand=False)
    request_box.insert("1.0", "Создать куб со стороной 20 мм")

    status_var = tk.StringVar(value="Готов к работе")
    tk.Label(root, textvariable=status_var, fg="blue").pack(anchor="w", padx=8, pady=(4, 0))

    log_box = scrolledtext.ScrolledText(root, height=10, state="disabled")
    log_box.pack(fill="both", padx=8, pady=8, expand=True)

    def log(msg: str):
        log_box.configure(state="normal")
        log_box.insert("end", msg + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")
        root.update_idletasks()

    def on_generate():
        user_request = request_box.get("1.0", "end").strip()
        if len(user_request) < 3:
            messagebox.showwarning("NX AI Generator", "Введите запрос (минимум 3 символа).")
            return

        generate_btn.configure(state="disabled")
        status_var.set("Генерация... (может занять 1-3 минуты)")
        log(f"Запрос: {user_request}")

        try:
            output_file = run_generation(user_request)
            status_var.set("Готово")
            log(f"Сохранено: {output_file}")
            messagebox.showinfo(
                "NX AI Generator",
                f"Код сохранён в:\n{output_file}\n\n"
                "Запустите этот файл как Journal в NX, когда будете готовы.",
            )
        except requests.exceptions.ConnectionError:
            status_var.set("Ошибка подключения")
            messagebox.showerror("NX AI Generator", "Не удаётся подключиться к Ollama.\nЗапустите: ollama serve")
        except requests.exceptions.Timeout:
            status_var.set("Таймаут")
            messagebox.showerror("NX AI Generator", "Генерация заняла слишком много времени.")
        except Exception as e:
            status_var.set("Ошибка")
            log(f"Ошибка: {e}")
            messagebox.showerror("NX AI Generator", str(e))
        finally:
            generate_btn.configure(state="normal")

    generate_btn = tk.Button(root, text="Сгенерировать и сохранить в файл", command=on_generate)
    generate_btn.pack(pady=(0, 8))

    root.mainloop()


# ==============================================================================
# ТОЧКА ВХОДА
# ==============================================================================

if __name__ == "__main__":
    if "--gui" in sys.argv:
        run_gui()
    elif len(sys.argv) > 1:
        # "Безголовый" режим - вызывается из NX через subprocess.
        # sys.argv[1] - текст запроса, пришедший из NX-диалога.
        user_request = sys.argv[1]
        try:
            output_file = run_generation(user_request)
            print(f"OK:{output_file}")
        except Exception as e:
            print(f"ERROR:{e}")
            sys.exit(1)
    else:
        run_console()