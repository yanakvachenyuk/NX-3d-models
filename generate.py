# from __future__ import annotations

# import ast
# import re
# import sys
# from datetime import datetime
# from pathlib import Path

# import requests


# # ==============================================================================
# # НАСТРОЙКИ
# # ==============================================================================

# PROJECT = Path(__file__).resolve().parent

# LIBRARY_DIR = PROJECT / "nx_primitives"
# PROMPTS_DIR = PROJECT / "prompts"
# GENERATED_DIR = PROJECT / "generated"
# LOG_DIR = PROJECT / "logs"
# SYSTEM_PROMPT = PROMPTS_DIR / "system_prompt.txt"
# OUTPUT_FILE = GENERATED_DIR / "result.py"

# OLLAMA_URL = "http://localhost:11434/api/generate"
# MODEL = "qwen2.5-coder:14b"

# RESULT_PREFIX = f"""import sys
# import os

# project_path = r'{PROJECT}'

# if project_path not in sys.path:
#     sys.path.insert(0, project_path)

# import NXOpen
# from nx_primitives import (
#     Triangle,
#     Parallelogram,
#     Polygon,
#     Circle,
#     Line,
#     Extrude,
#     Fillet,
#     Union,
#     Subtract,
#     Intersect,
#     Boolean,
#     Frame,
#     Hide,
#     rect_profile,
#     attachment_seam,
#     edges_after_boolean,
#     edges_in_box,
#     edges_near,
#     center_hole,
#     holes_in_row
# )

# theSession = NXOpen.Session.GetSession()
# workPart = theSession.Parts.Work
# """

# GENERATED_DIR.mkdir(exist_ok=True)
# LOG_DIR.mkdir(exist_ok=True)


# # ==============================================================================
# # ЧТЕНИЕ ФАЙЛОВ / СБОРКА ПРОМПТА
# # ==============================================================================

# def read_text(path: Path) -> str:
#     return path.read_text(encoding="utf-8", errors="ignore")


# def _format_args(args: ast.arguments) -> str:
#     parts = []
#     defaults = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)

#     for arg, default in zip(args.args, defaults):
#         piece = arg.arg
#         if arg.annotation is not None:
#             try:
#                 piece += f": {ast.unparse(arg.annotation)}"
#             except Exception:
#                 pass
#         if default is not None:
#             try:
#                 piece += f"={ast.unparse(default)}"
#             except Exception:
#                 piece += "=..."
#         parts.append(piece)

#     if args.vararg:
#         parts.append(f"*{args.vararg.arg}")
#     for kwarg, default in zip(args.kwonlyargs, args.kw_defaults):
#         piece = kwarg.arg
#         if default is not None:
#             try:
#                 piece += f"={ast.unparse(default)}"
#             except Exception:
#                 piece += "=..."
#         parts.append(piece)

#     return "(" + ", ".join(parts) + ")"


# def _first_doc_line(node) -> str | None:
#     doc = ast.get_docstring(node)
#     if not doc:
#         return None
#     return doc.strip().splitlines()[0]


# def build_library_description() -> str:
#     """
#     Собирает КРАТКУЮ сводку публичного API - сигнатуры классов/функций
#     + первая строка докстринга, БЕЗ реализации (NXOpen-boilerplate там
#     только мешает маленькой модели и съедает контекст без пользы).

#     Разбирает файлы статически через ast - не импортирует nx_primitives
#     (это потянуло бы NXOpen, которого нет в окружении, где запускается
#     сам генератор - он работает вне NX, просто пишет result.py на диск).
#     """
#     init_source = read_text(LIBRARY_DIR / "__init__.py")
#     init_tree = ast.parse(init_source)

#     public_names: set[str] = set()
#     for node in ast.walk(init_tree):
#         if isinstance(node, ast.Assign) and any(
#             isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
#         ):
#             for elt in node.value.elts:
#                 if isinstance(elt, ast.Constant):
#                     public_names.add(elt.value)

#     parts = [
#         "=" * 80,
#         "PUBLIC API (сигнатуры + краткие описания, без реализации)",
#         "Используй ТОЛЬКО то, что здесь перечислено.",
#         "=" * 80,
#         "",
#     ]

#     for file in sorted(LIBRARY_DIR.rglob("*.py")):
#         if file.name == "__init__.py":
#             continue

#         tree = ast.parse(read_text(file))

#         for node in ast.walk(tree):
#             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
#                     node.col_offset == 0 and node.name in public_names:
#                 parts.append(f"def {node.name}{_format_args(node.args)}")
#                 doc = _first_doc_line(node)
#                 if doc:
#                     parts.append(f"    # {doc}")
#                 parts.append("")

#             elif isinstance(node, ast.ClassDef) and node.name in public_names:
#                 parts.append(f"class {node.name}:")
#                 doc = _first_doc_line(node)
#                 if doc:
#                     parts.append(f"    # {doc}")

#                 for item in node.body:
#                     if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
#                         if item.name.startswith("_") and item.name != "__init__":
#                             continue
#                         prefix = "def __init__" if item.name == "__init__" else f"def {item.name}"
#                         parts.append(f"    {prefix}{_format_args(item.args)}")
#                         item_doc = _first_doc_line(item)
#                         if item_doc:
#                             parts.append(f"        # {item_doc}")
#                 parts.append("")

#     parts.append("=" * 80)
#     parts.append("END OF API")
#     parts.append("=" * 80)

#     return "\n".join(parts)


# # ------------------------------------------------------------------------------
# # Сигнатуры API для проверки НЕСУЩЕСТВУЮЩИХ именованных аргументов
# # (используется валидатором, см. _find_invalid_kwargs)
# # ------------------------------------------------------------------------------

# def _extract_param_names(args: ast.arguments) -> set[str]:
#     """
#     Извлекает множество допустимых ИМЁН именованных параметров функции/метода
#     из ast.arguments. Позиционные параметры (args.args) тоже можно передавать
#     как kwargs в Python, поэтому они тоже входят в множество.

#     Специальные пометки:
#       "*"  - функция принимает *args (лишние ПОЗИЦИОННЫЕ аргументы разрешены,
#              на именованные kwargs это не влияет)
#       "**" - функция принимает **kwargs (ЛЮБОЙ именованный аргумент разрешён,
#              проверка для такой функции отключается)
#     """
#     names: set[str] = set()

#     for a in args.args:
#         names.add(a.arg)

#     for a in args.kwonlyargs:
#         names.add(a.arg)

#     if args.vararg:
#         names.add("*")

#     if args.kwarg:
#         names.add("**")

#     return names


# def build_api_signatures() -> dict[str, set[str]]:
#     """
#     Строит словарь {имя_функции_или_метода: множество_допустимых_kwargs}
#     для всех ПУБЛИЧНЫХ функций и методов библиотеки (по тому же принципу
#     отбора, что и build_library_description - имя должно быть в __all__
#     из __init__.py).

#     ВАЖНО - ОГРАНИЧЕНИЕ ПОДХОДА: словарь строится ПО ИМЕНИ метода/функции,
#     БЕЗ учёта класса-владельца (AST не знает типов переменных в
#     сгенерированном коде, поэтому невозможно достоверно определить, что
#     `plate.attach_plate(...)` - это вызов именно Extrude.attach_plate, а
#     не одноимённого метода другого класса). Если у РАЗНЫХ классов
#     библиотеки появятся методы с ОДИНАКОВЫМ именем, но РАЗНЫМ набором
#     параметров - их допустимые kwargs объединятся (набор станет мягче для
#     обоих), и проверка перестанет ловить часть реальных ошибок для этой
#     пары методов. На момент написания коллизий имён в библиотеке нет.

#     Используется отдельно от build_library_description (которая строит
#     ТЕКСТОВОЕ описание для промта) - это дублирует часть обхода AST, но
#     сделано намеренно раздельно, чтобы не усложнять и не рисковать сломать
#     уже работающую сборку промта.
#     """
#     init_source = read_text(LIBRARY_DIR / "__init__.py")
#     init_tree = ast.parse(init_source)

#     public_names: set[str] = set()
#     for node in ast.walk(init_tree):
#         if isinstance(node, ast.Assign) and any(
#             isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
#         ):
#             for elt in node.value.elts:
#                 if isinstance(elt, ast.Constant):
#                     public_names.add(elt.value)

#     signatures: dict[str, set[str]] = {}

#     for file in sorted(LIBRARY_DIR.rglob("*.py")):
#         if file.name == "__init__.py":
#             continue

#         tree = ast.parse(read_text(file))

#         for node in ast.walk(tree):
#             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
#                     node.col_offset == 0 and node.name in public_names:
#                 signatures[node.name] = _extract_param_names(node.args)

#             elif isinstance(node, ast.ClassDef) and node.name in public_names:
#                 for item in node.body:
#                     if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
#                         if item.name.startswith("_") and item.name != "__init__":
#                             continue
#                         params = _extract_param_names(item.args)
#                         params.discard("self")
#                         # __init__ класса вызывается как ИМЯ_КЛАССА(...),
#                         # а не .__init__(...) - регистрируем под именем класса
#                         key = node.name if item.name == "__init__" else item.name
#                         if key in signatures:
#                             # коллизия имён между классами/функциями -
#                             # объединяем множества (см. предупреждение выше)
#                             signatures[key] |= params
#                         else:
#                             signatures[key] = params

#     return signatures


# _API_SIGNATURES_CACHE: dict[str, set[str]] | None = None


# def _get_api_signatures() -> dict[str, set[str]]:
#     """
#     Кэширует build_api_signatures() - файлы библиотеки не меняются во время
#     работы генератора, пересчитывать словарь на каждый validate_code() смысла
#     нет.
#     """
#     global _API_SIGNATURES_CACHE
#     if _API_SIGNATURES_CACHE is None:
#         _API_SIGNATURES_CACHE = build_api_signatures()
#     return _API_SIGNATURES_CACHE


# def build_prompt(user_request: str) -> str:
#     system_prompt = read_text(SYSTEM_PROMPT).strip()
#     library = build_library_description()

#     return f"""{system_prompt}


# {library}


# ================================================================================
# USER REQUEST
# ================================================================================

# {user_request}


# ================================================================================
# IMPORTANT

# Return ONLY executable Python code.
# Do NOT explain anything.
# Do NOT use Markdown.
# Do NOT wrap the code with ```.
# The answer must consist ONLY of Python code.
# ================================================================================
# """


# def save_prompt_log(prompt: str) -> Path:
#     timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
#     logfile = LOG_DIR / f"{timestamp}.txt"
#     logfile.write_text(prompt, encoding="utf-8")
#     return logfile


# def cleanup_response(text: str) -> str:
#     text = text.strip()
#     text = re.sub(r"^```python", "", text, flags=re.IGNORECASE)
#     text = re.sub(r"^```", "", text)
#     text = re.sub(r"```$", "", text)
#     return text.strip()


# def generate(prompt: str) -> str:
#     # payload = {"model": MODEL, "prompt": prompt, "stream": False}
#     payload = {
#         "model": MODEL,
#         "prompt": prompt,
#         "stream": False,
#         "options": {
#             "num_ctx": 16384,  # с запасом под реальный размер вашего промпта
#         }
#     }
#     response = requests.post(OLLAMA_URL, json=payload, timeout=600)
#     response.raise_for_status()
#     data = response.json()

#     if "response" not in data:
#         raise RuntimeError("Ollama returned an invalid response.")

#     return cleanup_response(data["response"])


# def save_result(code: str) -> Path:
#     OUTPUT_FILE.write_text(RESULT_PREFIX + code, encoding="utf-8")
#     return OUTPUT_FILE


# # ==============================================================================
# # ВАЛИДАТОР: полная структурная + геометрическая проверка сгенерированного кода
# # ==============================================================================
# #
# # Общий принцип: любая проверка здесь либо (А) констатирует ФАКТ о самом
# # API библиотеки (например "у Union нет find_edge") - такие проверки
# # ВСЕГДА блокирующие, ложных срабатываний в принципе быть не может;
# # либо (Б) сверяет число в коде с числом, которое ОДНОЗНАЧНО следует
# # из самого же кода (например u должен равняться length/2 того же
# # rect_profile) - тоже блокирующие, это не эвристика по словам запроса,
# # а внутренняя согласованность сгенерированного кода с самим собой.
# #
# # Эвристики по ключевым словам ЕСТЕСТВЕННОГО ЯЗЫКА запроса (типа "просил
# # ли скругление") оставлены МЯГКИМИ (warning, не блокирует) - у них
# # неизбежны ложные срабатывания, а каждый retry стоит времени.

# FORBIDDEN_SNIPPETS = (
#     "import NXOpen",
#     "from nx_primitives import",
#     "NXOpen.Session.GetSession",
#     "theSession.Parts.Work",
#     "```",
# )

# _BOOLEAN_FUNC_NAMES = {"Union", "Subtract", "Intersect", "Boolean"}


# # ------------------------------------------------------------------------------
# # A) Fillet(workPart, merged, ...) - структурная проверка API
# # ------------------------------------------------------------------------------

# def _find_boolean_result_vars(tree: ast.AST) -> set[str]:
#     """Имена переменных = результат Union/Subtract/Intersect/Boolean (нет find_edge)."""
#     boolean_vars: set[str] = set()
#     for node in ast.walk(tree):
#         if not isinstance(node, ast.Assign):
#             continue
#         call = node.value
#         if not isinstance(call, ast.Call):
#             continue
#         func = call.func
#         func_name = func.id if isinstance(func, ast.Name) else None
#         if func_name in _BOOLEAN_FUNC_NAMES:
#             for target in node.targets:
#                 if isinstance(target, ast.Name):
#                     boolean_vars.add(target.id)
#     return boolean_vars


# def _find_bad_fillet_extrude_args(tree: ast.AST, boolean_vars: set[str]) -> list[str]:
#     """Fillet(workPart, X, ...), где X - результат булевой операции (или X.body)."""
#     bad: list[str] = []
#     for node in ast.walk(tree):
#         if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
#                 and node.func.id == "Fillet"):
#             continue
#         args = node.args
#         if len(args) < 2:
#             continue
#         extrude_arg = args[1]
#         if isinstance(extrude_arg, ast.Name) and extrude_arg.id in boolean_vars:
#             bad.append(extrude_arg.id)
#         if isinstance(extrude_arg, ast.Attribute) and isinstance(extrude_arg.value, ast.Name):
#             if extrude_arg.value.id in boolean_vars:
#                 bad.append(f"{extrude_arg.value.id}.{extrude_arg.attr}")
#     return bad


# # ------------------------------------------------------------------------------
# # B) attachment_seam(...) на теле, присоединённом через anchor (должен быть
# #    contact_edges), и наоборот - contact_edges на теле от center_frame
# # ------------------------------------------------------------------------------

# def _find_attach_pattern_map(tree: ast.AST, source: str) -> dict[str, str]:
#     """
#     Для каждой переменной, полученной из X.attach(...), определяет паттерн
#     построения ('edge' - если frame пришёл от .anchor(...), 'flush' -
#     если от .center_frame(...)), анализируя ТЕКСТ строки с frame= (проще
#     и надёжнее полного AST-разбора цепочек присваивания для этой узкой
#     задачи, т.к. frame почти всегда передаётся как X.anchor(...) или
#     X.center_frame(...) inline в том же вызове attach(), либо через
#     переменную, присвоенную непосредственно перед attach()).
#     """
#     lines = source.splitlines()
#     pattern_map: dict[str, str] = {}

#     # 1) переменные вида: frame_name = X.anchor(...) / X.center_frame(...)
#     frame_pattern_of_var: dict[str, str] = {}
#     for i, line in enumerate(lines):
#         m = re.match(r"\s*(\w+)\s*=\s*\w+\.anchor\(", line)
#         if m:
#             frame_pattern_of_var[m.group(1)] = "edge"
#         m = re.match(r"\s*(\w+)\s*=\s*\w+\.center_frame\(", line)
#         if m:
#             frame_pattern_of_var[m.group(1)] = "flush"

#     # 2) переменные вида: child_name = X.attach(..., frame=FRAME_EXPR, ...)
#     #    ищем по многострочному вызову attach(...) целиком
#     full_source = source
#     for m in re.finditer(r"(\w+)\s*=\s*\w+\.attach\(", full_source):
#         child_name = m.group(1)
#         start = m.end() - 1  # позиция открывающей скобки
#         depth = 0
#         end = start
#         for j in range(start, len(full_source)):
#             if full_source[j] == "(":
#                 depth += 1
#             elif full_source[j] == ")":
#                 depth -= 1
#                 if depth == 0:
#                     end = j
#                     break
#         call_text = full_source[start:end + 1]

#         if ".anchor(" in call_text and "frame=" not in call_text:
#             pattern_map[child_name] = "edge"
#         elif ".center_frame(" in call_text and "frame=" not in call_text:
#             pattern_map[child_name] = "flush"
#         else:
#             fm = re.search(r"frame\s*=\s*(\w+)", call_text)
#             if fm and fm.group(1) in frame_pattern_of_var:
#                 pattern_map[child_name] = frame_pattern_of_var[fm.group(1)]

#     return pattern_map


# def _find_wrong_seam_calls(tree: ast.AST, source: str) -> list[str]:
#     """
#     attachment_seam(X, ...) при X из паттерна 'edge' (anchor) - неверно.
#     X.contact_edges() / edges_after_boolean(X, ..., X.contact_edges())
#         при X из паттерна 'flush' (center_frame) - неверно.
#     """
#     pattern_map = _find_attach_pattern_map(tree, source)
#     errors: list[str] = []

#     for node in ast.walk(tree):
#         if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
#             if node.func.id == "attachment_seam" and node.args:
#                 first = node.args[0]
#                 if isinstance(first, ast.Name) and pattern_map.get(first.id) == "edge":
#                     errors.append(
#                         f"attachment_seam({first.id}, ...) - {first.id} построен через "
#                         f"anchor() (паттерн 'от ребра'), для него attachment_seam НЕЛЬЗЯ, "
#                         f"нужен {first.id}.contact_edges() + edges_on/edges_after_boolean."
#                     )

#         if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
#             if node.func.attr == "contact_edges" and isinstance(node.func.value, ast.Name):
#                 var = node.func.value.id
#                 if pattern_map.get(var) == "flush":
#                     errors.append(
#                         f"{var}.contact_edges() - {var} построен через center_frame() "
#                         f"(паттерн 'плашмя'), для него contact_edges() НЕЛЬЗЯ, нужен "
#                         f"attachment_seam({var}, merged.body)."
#                     )

#     return errors


# # ------------------------------------------------------------------------------
# # C) v0 у rect_profile ДОЛЖЕН быть 0.0, если frame взят из .anchor(...)
# #    (v0=0.5 при anchor - самая частая причина "деталь вдавлена внутрь")
# # ------------------------------------------------------------------------------

# def _find_wrong_v0_for_anchor(source: str) -> list[str]:
#     errors: list[str] = []
#     for m in re.finditer(r"(\w+)\s*=\s*\w+\.attach\(", source):
#         start = m.end() - 1
#         depth = 0
#         end = start
#         for j in range(start, len(source)):
#             if source[j] == "(":
#                 depth += 1
#             elif source[j] == ")":
#                 depth -= 1
#                 if depth == 0:
#                     end = j
#                     break
#         call_text = source[start:end + 1]

#         uses_anchor = (
#             ".anchor(" in call_text and "frame=" not in call_text
#         ) or (
#             "frame=" in call_text and re.search(r"frame\s*=\s*\w*anchor\w*", call_text)
#         )

#         if not uses_anchor:
#             continue

#         v0_match = re.search(r"v0\s*=\s*([0-9.]+)", call_text)
#         if v0_match and float(v0_match.group(1)) != 0.0:
#             errors.append(
#                 f"{m.group(1)} = X.attach(...) построен от .anchor(...), но "
#                 f"rect_profile передан с v0={v0_match.group(1)} - должно быть "
#                 f"v0=0.0 (иначе половина детали уходит ВНУТРЬ родителя)."
#             )
#     return errors


# # ------------------------------------------------------------------------------
# # D) Отверстие ВНУТРИ одиночной пластины (Parallelogram + Circle без attach) -
# #    не выходит ли за пределы контура
# # ------------------------------------------------------------------------------

# def _literal_value(node) -> float | None:
#     """Достаёт float из простого числового литерала или унарного минуса."""
#     if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
#         return float(node.value)
#     if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
#         inner = _literal_value(node.operand)
#         return -inner if inner is not None else None
#     if isinstance(node, ast.BinOp):
#         left = _literal_value(node.left)
#         right = _literal_value(node.right)
#         if left is None or right is None:
#             return None
#         if isinstance(node.op, ast.Add):
#             return left + right
#         if isinstance(node.op, ast.Sub):
#             return left - right
#         if isinstance(node.op, ast.Mult):
#             return left * right
#         if isinstance(node.op, ast.Div):
#             return left / right
#     return None


# def _get_kwarg(call: ast.Call, name: str):
#     for kw in call.keywords:
#         if kw.arg == name:
#             return kw.value
#     return None


# def _find_holes_out_of_bounds(tree: ast.AST) -> list[str]:
#     """
#     Ищет пары (Parallelogram(...), Circle(...)) в одном присваивании-соседстве
#     (та же переменная-контур используется как первый элемент Extrude,
#     а Circle - второй/третий) и проверяет, что окружность (center ± radius)
#     целиком помещается в прямоугольник (по half-extent side_a/2, side_b/2 от
#     центра прямоугольника). Работает только для ЛИТЕРАЛЬНЫХ чисел (не
#     произвольных выражений) - это осознанное ограничение: если параметры
#     не литералы, проверка просто пропускается, а не даёт ложную ошибку.
#     """
#     errors: list[str] = []

#     # переменная -> (side_a, side_b, center_x, center_y)
#     parallelograms: dict[str, tuple] = {}
#     # переменная -> (radius, center_x, center_y)
#     circles: dict[str, tuple] = {}

#     for node in ast.walk(tree):
#         if not (isinstance(node, ast.Assign) and len(node.targets) == 1
#                 and isinstance(node.targets[0], ast.Name)):
#             continue
#         var = node.targets[0].id
#         call = node.value
#         if not isinstance(call, ast.Call):
#             continue
#         func = call.func
#         func_name = func.id if isinstance(func, ast.Name) else (
#             func.attr if isinstance(func, ast.Attribute) else None
#         )

#         if func_name == "Parallelogram":
#             side_a = _literal_value(_get_kwarg(call, "side_a") or (call.args[1] if len(call.args) > 1 else None))
#             side_b = _literal_value(_get_kwarg(call, "side_b") or (call.args[2] if len(call.args) > 2 else None))
#             center_node = _get_kwarg(call, "center")
#             cx, cy = 0.0, 0.0
#             if isinstance(center_node, ast.Tuple) and len(center_node.elts) >= 2:
#                 cx = _literal_value(center_node.elts[0]) or 0.0
#                 cy = _literal_value(center_node.elts[1]) or 0.0
#             if side_a is not None and side_b is not None:
#                 parallelograms[var] = (side_a, side_b, cx, cy)

#         if func_name == "Circle":
#             radius = _literal_value(_get_kwarg(call, "radius") or (call.args[1] if len(call.args) > 1 else None))
#             center_node = _get_kwarg(call, "center")
#             cx, cy = None, None
#             if isinstance(center_node, ast.Tuple) and len(center_node.elts) >= 2:
#                 cx = _literal_value(center_node.elts[0])
#                 cy = _literal_value(center_node.elts[1])
#             elif isinstance(center_node, ast.Call):
#                 # point_from_center(dx, dy) - берём аргументы как смещение от 0
#                 pf_args = center_node.args
#                 cx = _literal_value(pf_args[0]) if len(pf_args) > 0 else 0.0
#                 cy = _literal_value(pf_args[1]) if len(pf_args) > 1 else 0.0
#             if radius is not None and cx is not None and cy is not None:
#                 circles[var] = (radius, cx, cy)

#     # Найдём Extrude(workPart, [base_var, hole_var, ...], ...) чтобы связать пары
#     for node in ast.walk(tree):
#         if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
#                 and node.func.id == "Extrude"):
#             continue
#         if len(node.args) < 2 or not isinstance(node.args[1], ast.List):
#             continue
#         profile_vars = [e.id for e in node.args[1].elts if isinstance(e, ast.Name)]
#         if not profile_vars:
#             continue
#         base_var = profile_vars[0]
#         if base_var not in parallelograms:
#             continue
#         side_a, side_b, pcx, pcy = parallelograms[base_var]
#         half_a, half_b = side_a / 2.0, side_b / 2.0

#         for hole_var in profile_vars[1:]:
#             if hole_var not in circles:
#                 continue
#             radius, hcx, hcy = circles[hole_var]
#             # предполагаем, что hole-координаты УЖЕ абсолютные (после
#             # point_from_center они относительны к центру base - учитываем)
#             abs_hcx, abs_hcy = pcx + hcx, pcy + hcy if False else (hcx, hcy)
#             # если центр отверстия задан через point_from_center(dx,dy) -
#             # dx/dy УЖЕ относительны к центру base, добавляем к нему явно:
#             # (для простоты считаем координаты circles[] как offset от 0,
#             #  а сравниваем с half-extent, что корректно и для случая center=(0,0))
#             if abs(hcx - pcx) + radius > half_a + 1e-6 or abs(hcy - pcy) + radius > half_b + 1e-6:
#                 errors.append(
#                     f"{hole_var} (радиус {radius}, центр ({hcx},{hcy})) выходит за "
#                     f"пределы {base_var} (side_a={side_a}, side_b={side_b}, "
#                     f"центр ({pcx},{pcy})) - половина стороны {half_a}x{half_b}, "
#                     f"а отверстие требует минимум {abs(hcx - pcx) + radius}x"
#                     f"{abs(hcy - pcy) + radius} свободного места от центра. "
#                     f"Пересчитай координаты center - используй base.point_from_center(dx, dy), "
#                     f"где dx/dy отсчитываются ОТ ЦЕНТРА, а не от угла."
#                 )

#     return errors


# # ------------------------------------------------------------------------------
# # D2) Несуществующие именованные аргументы у известных функций/методов API
# # ------------------------------------------------------------------------------

# def _find_invalid_kwargs(tree: ast.AST, signatures: dict[str, set[str]]) -> list[str]:
#     """
#     Проверяет КАЖДЫЙ вызов известной (по имени) функции/метода библиотеки
#     на использование НЕСУЩЕСТВУЮЩЕГО именованного аргумента.

#     Это структурная проверка API (аналог группы А), а не эвристика по
#     словам запроса - ложных срабатываний по смыслу быть не должно (см.
#     docstring build_api_signatures про единственное реальное ограничение:
#     проверка идёт по имени метода, без учёта класса-владельца).

#     Функции/методы, которых нет в словаре signatures (например встроенные
#     Python-функции типа print/range, или что-то не входящее в публичный
#     API библиотеки), пропускаются без ошибки - задача этой проверки
#     только про API самой библиотеки.
#     """
#     errors: list[str] = []

#     for node in ast.walk(tree):
#         if not isinstance(node, ast.Call):
#             continue

#         func = node.func
#         if isinstance(func, ast.Name):
#             func_name = func.id
#         elif isinstance(func, ast.Attribute):
#             func_name = func.attr
#         else:
#             continue

#         if func_name not in signatures:
#             continue

#         allowed = signatures[func_name]

#         if "**" in allowed:
#             continue  # функция принимает произвольные kwargs - не проверяем

#         for kw in node.keywords:
#             if kw.arg is None:
#                 continue  # **dict-распаковка - пропускаем, не наш случай
#             if kw.arg not in allowed:
#                 errors.append(
#                     f"{func_name}(...): неизвестный именованный аргумент "
#                     f"'{kw.arg}='. Допустимые параметры {func_name}: "
#                     f"{sorted(a for a in allowed if a not in ('*', '**'))}."
#                 )

#     return errors


# # ------------------------------------------------------------------------------
# # E) Отверстие "по центру" внутри holes= у attach() - проверяем u == length/2
# # ------------------------------------------------------------------------------

# def _find_offcenter_holes(source: str, user_request: str) -> list[str]:
#     """
#     Если в тексте запроса есть "по центру" (применительно к отверстию в
#     пристрое) - находим соответствующий attach(...) с rect_profile(...,
#     length=L, ...) и holes=[lambda f: Circle.on_frame(..., u=U, ...)],
#     и проверяем U == L/2 (с допуском 0.01мм). ЭТО НЕ эвристика по словам -
#     L и U оба взяты из уже сгенерированного кода, сравниваются между собой.
#     """
#     if "по центру" not in user_request.lower() and "по-центру" not in user_request.lower():
#         return []

#     errors: list[str] = []

#     for m in re.finditer(r"\w+\s*=\s*\w+\.attach\(", source):
#         start = m.end() - 1
#         depth = 0
#         end = start
#         for j in range(start, len(source)):
#             if source[j] == "(":
#                 depth += 1
#             elif source[j] == ")":
#                 depth -= 1
#                 if depth == 0:
#                     end = j
#                     break
#         call_text = source[start:end + 1]

#         if "holes=" not in call_text:
#             continue

#         length_match = re.search(r"length\s*=\s*([0-9.]+)", call_text)
#         u_match = re.search(r"Circle\.on_frame\([^)]*u\s*=\s*([0-9.]+(?:\s*/\s*[0-9.]+)?)", call_text)
#         if not (length_match and u_match):
#             continue

#         length_val = float(length_match.group(1))
#         u_expr = u_match.group(1)
#         try:
#             u_val = eval(u_expr, {"__builtins__": {}})
#         except Exception:
#             continue

#         expected = length_val / 2.0
#         if abs(u_val - expected) > 0.01:
#             errors.append(
#                 f"Запрос требует отверстие ПО ЦЕНТРУ пристроя (длина {length_val}), "
#                 f"значит u должно быть {expected}, но в коде u={u_expr} ({u_val}). "
#                 f"Исправь координату u внутри Circle.on_frame(...) на {expected}."
#             )

#     return errors


# # ------------------------------------------------------------------------------
# # СВОДНАЯ ФУНКЦИЯ: жёсткие (блокирующие) проверки
# # ------------------------------------------------------------------------------

# def validate_code(code: str, user_request: str = "") -> str | None:
#     """Возвращает текст ошибки (блокирует сохранение, уходит в retry), иначе None."""
#     try:
#         tree = ast.parse(code)
#     except SyntaxError as e:
#         return f"SyntaxError: {e}"

#     for snippet in FORBIDDEN_SNIPPETS:
#         if snippet in code:
#             return (
#                 f"Код содержит запрещённый фрагмент '{snippet}'. "
#                 "Session/workPart и импорты уже подставлены снаружи - "
#                 "не пиши их и не оборачивай ответ в ```."
#             )

#     # A) Fillet на результате Union/Subtract/Intersect
#     boolean_vars = _find_boolean_result_vars(tree)
#     bad_fillets = _find_bad_fillet_extrude_args(tree, boolean_vars)
#     if bad_fillets:
#         names = ", ".join(sorted(set(bad_fillets)))
#         return (
#             f"Fillet(workPart, {names}, ...) - вторым аргументом передан результат "
#             f"Union/Subtract/Intersect, у которого НЕТ find_edge. Передай вместо "
#             f"этого target-тело (первый аргумент Union/Subtract/Intersect)."
#         )

#     # B) attachment_seam/contact_edges перепутаны местами
#     seam_errors = _find_wrong_seam_calls(tree, code)
#     if seam_errors:
#         return " ".join(seam_errors)

#     # C) v0 != 0.0 при anchor()
#     v0_errors = _find_wrong_v0_for_anchor(code)
#     if v0_errors:
#         return " ".join(v0_errors)

#     # D) отверстие вылезает за пределы контура
#     bounds_errors = _find_holes_out_of_bounds(tree)
#     if bounds_errors:
#         return " ".join(bounds_errors)

#     # D2) несуществующие именованные аргументы у известных функций/методов API
#     kwarg_errors = _find_invalid_kwargs(tree, _get_api_signatures())
#     if kwarg_errors:
#         return " ".join(kwarg_errors)

#     # # E) отверстие "по центру" реально не по центру
#     # offcenter_errors = _find_offcenter_holes(code, user_request)
#     # if offcenter_errors:
#     #     return " ".join(offcenter_errors)

#     if re.search(r"\w+\.Extrude\s*\(", code):
#         return (
#             "Запрещён вызов profile.Extrude(...). "
#             "У Profile/Parallelogram/Polygon нет метода Extrude. "
#             "Для пристроя используй parent.attach(lambda f: rect_profile(...), thickness=..., frame=parent.anchor(...)). "
#             "Для отдельного тела: Extrude(workPart, [profile], height=...)."
#         )

#     boolean_vars = _find_boolean_result_vars(tree)  # уже есть
#     for name in boolean_vars:
#         if re.search(rf"\b{re.escape(name)}\.(anchor|attach|attach_plate)\s*\(", code):
#             return (
#                 f"{name} — результат Union, нельзя .{name}.anchor/attach. "
#                 "Сначала: shelf/ear = wall.attach(...), потом Union(workPart, plate, wall, shelf)."
#             )

#     minimality_errors = check_minimality_warnings(code, user_request)
#     if minimality_errors:
#         return " ".join(minimality_errors)

#     return None


# # ------------------------------------------------------------------------------
# # Мягкие проверки "ничего лишнего" по ключевым словам (блокирующие, но с
# # исправленным regex - "радиус" больше НЕ триггерит Fillet ложно)
# # ------------------------------------------------------------------------------

# _FILLET_TRIGGER_PATTERN = re.compile(
#     r"скругл|fillet|фаск|радиус\w*\s+скругл", re.IGNORECASE
# )
# _BOOLEAN_TRIGGER_WORDS = (
#     "объедин", "единое тело", "слить", "склеить",
#     "вычесть", "вычит", "пересеч", "intersect", "subtract", "boolean",
# )
# _HOLE_TRIGGER_WORDS = ("отверст", "дыр", "паз", "hole", "прорез", "просверл")


# def _contains_any(text: str, words) -> bool:
#     lowered = text.lower()
#     return any(w in lowered for w in words)


# def check_minimality_warnings(code: str, user_request: str) -> list[str]:
#     warnings: list[str] = []

#     if "Fillet(" in code and not _FILLET_TRIGGER_PATTERN.search(user_request):
#         warnings.append(
#             "В коде есть Fillet(...), но в запросе нет слов про скругление "
#             "(просто 'радиус N' у отверстия - не считово). Убери Fillet(...) полностью."
#         )

#     if any(f"{name}(" in code for name in ("Union", "Subtract", "Intersect")) and \
#             not _contains_any(user_request, _BOOLEAN_TRIGGER_WORDS):
#         warnings.append(
#             "В коде есть Union/Subtract/Intersect(...), но в запросе нет слов "
#             "про объединение. Убери эти вызовы, оставь тела раздельными."
#         )

#     if "holes=" in code and not _contains_any(user_request, _HOLE_TRIGGER_WORDS):
#         warnings.append(
#             "В коде есть holes=[...], но в запросе нет слов про отверстие. "
#             "Убери holes=... полностью."
#         )

#     return warnings

# def run_generation(user_request: str, max_attempts: int = 3) -> Path:
#     """
#     Строит промпт, шлёт в Ollama, проверяет синтаксис, запрещённые
#     паттерны и структурную корректность Fillet/Union (см. validate_code).
#     Если код невалиден - повторяет запрос (до max_attempts раз), добавляя
#     в промпт текст конкретной ошибки, чтобы модель её исправила.
#     """
#     prompt = build_prompt(user_request)
#     save_prompt_log(prompt)

#     last_error = None
#     current_prompt = prompt

#     for attempt in range(1, max_attempts + 1):
#         code = generate(current_prompt)
#         error = validate_code(code, user_request)

#         if error is None:
#             return save_result(code)

#         last_error = error
#         current_prompt = (
#             f"{prompt}\n\n"
#             "================================================================================\n"
#             "ПРЕДЫДУЩИЙ ОТВЕТ БЫЛ НЕВАЛИДЕН\n"
#             "================================================================================\n\n"
#             f"Ошибка: {error}\n\n"
#             "Сгенерируй код заново, полностью, с учётом этой ошибки. "
#             "Помни: только исполняемый Python-код, без ``` и без import/session/workPart.\n"
#         )

#     raise RuntimeError(
#         f"Не удалось получить валидный код за {max_attempts} попыток. "
#         f"Последняя ошибка: {last_error}"
#     )


# # ==============================================================================
# # КОНСОЛЬНЫЙ РЕЖИМ
# # ==============================================================================

# def run_console():
#     print("=" * 80)
#     print("NX AI Generator (консоль)")
#     print("=" * 80)
#     print(f"Model   : {MODEL}")
#     print(f"Library : {LIBRARY_DIR}")
#     print(f"Output  : {OUTPUT_FILE}")
#     print()

#     while True:
#         print("-" * 80)
#         user_request = input("Запрос (пустая строка для выхода):\n> ").strip()
#         if not user_request:
#             break

#         try:
#             print("Генерация...")
#             output_file = run_generation(user_request)
#             print(f"Готово: {output_file}\n")
#         except requests.exceptions.ConnectionError:
#             print("ОШИБКА: не могу подключиться к Ollama. Запустите `ollama serve`.\n")
#         except requests.exceptions.Timeout:
#             print("ОШИБКА: превышено время ожидания генерации.\n")
#         except Exception as e:
#             print(f"ОШИБКА: {e}\n")


# # ==============================================================================
# # ПРОСТОЙ GUI (обычное tkinter-окно, БЕЗ NXOpen, запускается отдельным процессом)
# # ==============================================================================

# def run_gui():
#     import tkinter as tk
#     from tkinter import scrolledtext, messagebox

#     root = tk.Tk()
#     root.title("NX AI Generator")
#     root.geometry("600x420")

#     tk.Label(root, text="Запрос для генерации модели:").pack(anchor="w", padx=8, pady=(8, 0))
#     request_box = scrolledtext.ScrolledText(root, height=8)
#     request_box.pack(fill="both", padx=8, pady=4, expand=False)
#     request_box.insert("1.0", "Создать куб со стороной 20 мм")

#     status_var = tk.StringVar(value="Готов к работе")
#     tk.Label(root, textvariable=status_var, fg="blue").pack(anchor="w", padx=8, pady=(4, 0))

#     log_box = scrolledtext.ScrolledText(root, height=10, state="disabled")
#     log_box.pack(fill="both", padx=8, pady=8, expand=True)

#     def log(msg: str):
#         log_box.configure(state="normal")
#         log_box.insert("end", msg + "\n")
#         log_box.see("end")
#         log_box.configure(state="disabled")
#         root.update_idletasks()

#     def on_generate():
#         user_request = request_box.get("1.0", "end").strip()
#         if len(user_request) < 3:
#             messagebox.showwarning("NX AI Generator", "Введите запрос (минимум 3 символа).")
#             return

#         generate_btn.configure(state="disabled")
#         status_var.set("Генерация... (может занять 1-3 минуты)")
#         log(f"Запрос: {user_request}")

#         try:
#             output_file = run_generation(user_request)
#             status_var.set("Готово")
#             log(f"Сохранено: {output_file}")
#             messagebox.showinfo(
#                 "NX AI Generator",
#                 f"Код сохранён в:\n{output_file}\n\n"
#                 "Запустите этот файл как Journal в NX, когда будете готовы.",
#             )
#         except requests.exceptions.ConnectionError:
#             status_var.set("Ошибка подключения")
#             messagebox.showerror("NX AI Generator", "Не удаётся подключиться к Ollama.\nЗапустите: ollama serve")
#         except requests.exceptions.Timeout:
#             status_var.set("Таймаут")
#             messagebox.showerror("NX AI Generator", "Генерация заняла слишком много времени.")
#         except Exception as e:
#             status_var.set("Ошибка")
#             log(f"Ошибка: {e}")
#             messagebox.showerror("NX AI Generator", str(e))
#         finally:
#             generate_btn.configure(state="normal")

#     generate_btn = tk.Button(root, text="Сгенерировать и сохранить в файл", command=on_generate)
#     generate_btn.pack(pady=(0, 8))

#     root.mainloop()


# # ==============================================================================
# # ТОЧКА ВХОДА
# # ==============================================================================

# if __name__ == "__main__":
#     if "--gui" in sys.argv:
#         run_gui()
#     elif len(sys.argv) > 1:
#         # "Безголовый" режим - вызывается из NX через subprocess.
#         # sys.argv[1] - текст запроса, пришедший из NX-диалога.
#         user_request = sys.argv[1]
#         try:
#             output_file = run_generation(user_request)
#             print(f"OK:{output_file}")
#         except Exception as e:
#             print(f"ERROR:{e}")
#             sys.exit(1)
#     else:
#         run_console()


import sys
from gen.run import run_console, run_generation

if __name__ == "__main__":
    if len(sys.argv) > 1:
        try:
            path = run_generation(sys.argv[1])
            print(f"OK:{path}")
        except Exception as e:
            print(f"ERROR:{e}")
            sys.exit(1)
    else:
        run_console()