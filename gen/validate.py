"""Структурная валидация сгенерированного кода.

Валидатор ловит ДВА разных класса проблем, и их не стоит путать:

1. ЖЁСТКИЕ ИНВАРИАНТЫ API — код гарантированно упадёт или даст неверный
   результат независимо от того, что хотел пользователь (например: Fillet
   на результате Union, attachment_seam на теле без реального attach()).
   Эти проверки безопасны: они не гадают о намерении, а проверяют факт
   о механике библиотеки.

2. СООТВЕТСТВИЕ USER REQUEST (minimality) — эвристики по ключевым словам
   в тексте запроса (есть ли "скруглить", "объединить", "отверстие").
   Это хрупкие regex-проверки: они могут дать ложное срабатывание на
   непредвиденной формулировке. Держим их простыми и не расширяем без
   явной необходимости.

Порядок проверок в validate_code важен: сначала более специфичные и
дешёвые синтаксические проверки, потом более общие.
"""
from __future__ import annotations

import ast
import re

from .library_api import get_api_signatures

# ======================================================================
# Константы
# ======================================================================

FORBIDDEN_SNIPPETS = (
    "import NXOpen",
    "from nx_primitives import",
    "NXOpen.Session.GetSession",
    "theSession.Parts.Work",
    "```",
)

_BOOLEAN_FUNC_NAMES = {"Union", "Subtract", "Intersect", "Boolean"}

# "Triangle(" без точки перед скобкой — сырой __init__, запрещён ВСЕГДА,
# независимо от запроса (Triangle.by_3_sides(... не матчится, т.к. там
# после "Triangle" идёт ".by_3_sides(", а не "(" сразу).
_RAW_TRIANGLE_CALL = re.compile(r"\bTriangle\s*\(")

# Единственный источник триггер-слов для minimality-проверок. Раньше эти
# наборы дублировались в двух местах с разными формулировками — теперь
# один набор, используемый везде.
_FILLET_RE = re.compile(r"скругл|fillet|фаск|сглад", re.I)
_BOOL_RE = re.compile(r"объедин|единое\s+тело|слить|склеить|вычесть|вычит|пересеч|intersect|subtract|boolean", re.I)
_HOLE_RE = re.compile(r"отверст|дыр|паз|hole|прорез|просверл", re.I)
_SEAM_BETWEEN_BODIES_RE = re.compile(r"(переход|шов|стык|соединени\w*)\s+между", re.I)


# ======================================================================
# Вспомогательные сборщики данных из AST/исходника
# ======================================================================

def _find_boolean_result_vars(tree: ast.AST) -> set[str]:
    """Переменные, которым присвоен результат Union/Subtract/Intersect/Boolean.
    У таких переменных нет .anchor/.attach/.attach_plate/find_edge — это
    Boolean-объект (.body, .new_edges), а не Extrude."""
    boolean_vars: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func_name = call.func.id if isinstance(call.func, ast.Name) else None
        if func_name in _BOOLEAN_FUNC_NAMES:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    boolean_vars.add(target.id)
    return boolean_vars


def _call_text_for_assignment(source: str, method_name: str):
    """Итератор (var_name, call_text) для всех присваиваний вида
    `var = X.<method_name>(...)`, где call_text — полный текст вызова
    от открывающей до закрывающей скобки (с учётом вложенных скобок)."""
    for m in re.finditer(rf"(\w+)\s*=\s*\w+\.{method_name}\s*\(", source):
        var_name = m.group(1)
        start = m.end() - 1
        depth = 0
        end = start
        for j in range(start, len(source)):
            if source[j] == "(":
                depth += 1
            elif source[j] == ")":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        yield var_name, source[start:end + 1]


def _find_attach_pattern_map(source: str) -> dict[str, str]:
    """Для каждой переменной, построенной через parent.attach(...),
    определяет паттерн родительского frame: 'edge' (anchor — 'от ребра')
    или 'flush' (center_frame — 'плашмя')."""
    frame_pattern_of_var: dict[str, str] = {}
    for line in source.splitlines():
        m = re.match(r"\s*(\w+)\s*=\s*\w+\.anchor\(", line)
        if m:
            frame_pattern_of_var[m.group(1)] = "edge"
        m = re.match(r"\s*(\w+)\s*=\s*\w+\.center_frame\(", line)
        if m:
            frame_pattern_of_var[m.group(1)] = "flush"

    pattern_map: dict[str, str] = {}
    for child_name, call_text in _call_text_for_assignment(source, "attach"):
        if ".anchor(" in call_text and "frame=" not in call_text:
            pattern_map[child_name] = "edge"
        elif ".center_frame(" in call_text and "frame=" not in call_text:
            pattern_map[child_name] = "flush"
        else:
            fm = re.search(r"frame\s*=\s*(\w+)", call_text)
            if fm and fm.group(1) in frame_pattern_of_var:
                pattern_map[child_name] = frame_pattern_of_var[fm.group(1)]
    return pattern_map


def _find_attached_var_names(source: str) -> set[str]:
    """Переменные, реально ПРИСОЕДИНЁННЫЕ к родителю через
    parent.attach(...) или parent.attach_plate(...) — то есть физически
    позиционированные относительно родителя (frame взят от родителя)."""
    attached: set[str] = set()
    for var_name, _ in _call_text_for_assignment(source, "attach"):
        attached.add(var_name)
    for var_name, _ in _call_text_for_assignment(source, "attach_plate"):
        attached.add(var_name)
    return attached


def _find_independent_extrude_var_names(tree: ast.AST) -> set[str]:
    """Переменные, построенные НАПРЯМУЮ через Extrude(workPart, [...], ...) —
    независимые тела, не позиционированные относительно какого-либо
    родителя (даже если они потом участвуют в Union)."""
    independent: set[str] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        call = node.value
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "Extrude":
            independent.add(node.targets[0].id)
    return independent


def _literal_value(node) -> float | None:
    """Вычисляет числовое значение простого константного AST-выражения
    (числа, унарный минус, +-*/ над числами). Возвращает None, если
    выражение не сводится к литералу (например, содержит переменную)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal_value(node.operand)
        return -inner if inner is not None else None
    if isinstance(node, ast.BinOp):
        left = _literal_value(node.left)
        right = _literal_value(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
    return None


def _get_kwarg(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


# ======================================================================
# Проверки: жёсткие инварианты API (не зависят от текста запроса)
# ======================================================================

def _check_forbidden_snippets(code: str) -> str | None:
    for snippet in FORBIDDEN_SNIPPETS:
        if snippet in code:
            return (
                f"Код содержит запрещённый фрагмент '{snippet}'. "
                "Session/workPart и импорты уже подставлены снаружи."
            )
    return None


def _check_raw_triangle(code: str) -> str | None:
    if not _RAW_TRIANGLE_CALL.search(code):
        return None
    return (
        "Обнаружен вызов Triangle(workPart, ...) напрямую — такого __init__ "
        "нет, конструктор ждёт три ТОЧКИ и падает на несовместимом формате "
        "координат (например, 2D-точки вместо 3D). Треугольник строится "
        "ТОЛЬКО через фабричные методы: Triangle.by_3_sides(...), "
        "Triangle.by_2_sides_and_angle(...), Triangle.by_2_angles_and_side(...). "
        "Удали сырой вызов Triangle(...) полностью (включая мёртвый код от "
        "прошлых попыток) и замени его на подходящий фабричный метод."
    )


def _check_fillet_on_boolean_result(tree: ast.AST, boolean_vars: set[str]) -> str | None:
    """Fillet(workPart, X, ...) — X должен быть Extrude (target), а не
    результат Union/Subtract/Intersect (у Boolean нет нужных методов/
    структуры рёбер)."""
    bad: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Fillet"):
            continue
        args = node.args
        if len(args) < 2:
            continue
        extrude_arg = args[1]
        if isinstance(extrude_arg, ast.Name) and extrude_arg.id in boolean_vars:
            bad.append(extrude_arg.id)
        if isinstance(extrude_arg, ast.Attribute) and isinstance(extrude_arg.value, ast.Name):
            if extrude_arg.value.id in boolean_vars:
                bad.append(f"{extrude_arg.value.id}.{extrude_arg.attr}")
    if not bad:
        return None
    names = ", ".join(sorted(set(bad)))
    return f"Fillet(workPart, {names}, ...) — результат Union. Передай target (первый аргумент Union)."


def _check_seam_pattern_mismatch(source: str) -> str | None:
    """Метод поиска шва должен соответствовать паттерну присоединения:
    attachment_seam — только для center_frame ('плашмя'); contact_edges —
    только для anchor ('от ребра'). Перепутанные пары дают неверный или
    пустой список рёбер."""
    pattern_map = _find_attach_pattern_map(source)
    tree = ast.parse(source)
    errors: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "attachment_seam" and node.args:
                first = node.args[0]
                if isinstance(first, ast.Name) and pattern_map.get(first.id) == "edge":
                    errors.append(
                        f"attachment_seam({first.id}, ...) - {first.id} построен через "
                        f"anchor() (паттерн 'от ребра'), для него attachment_seam НЕЛЬЗЯ, "
                        f"нужен {first.id}.contact_edges() + edges_on/edges_after_boolean."
                    )
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "contact_edges" and isinstance(node.func.value, ast.Name):
                var = node.func.value.id
                if pattern_map.get(var) == "flush":
                    errors.append(
                        f"{var}.contact_edges() - {var} построен через center_frame() "
                        f"(паттерн 'плашмя'), для него contact_edges() НЕЛЬЗЯ, нужен "
                        f"attachment_seam({var}, merged.body)."
                    )
    return " ".join(errors) if errors else None


def _check_seam_on_unattached_body(tree: ast.AST, source: str) -> str | None:
    """attachment_seam(child, ...) физически осмыслен только если child был
    ПРИСОЕДИНЁН к родителю через .attach()/.attach_plate() — тогда между
    ними реально есть граница/уступ. Если child построен напрямую через
    Extrude(workPart, [...]) (независимое тело, даже от той же точки
    (0,0,0), что и родитель), шва физически может не быть — тела просто
    взаимно проникают друг в друга, и attachment_seam закономерно вернёт
    пустой список рёбер (Fillet потом падает с ValueError)."""
    attached_vars = _find_attached_var_names(source)
    independent_vars = _find_independent_extrude_var_names(tree)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "attachment_seam"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Name):
            continue
        var = first.id
        if var in independent_vars and var not in attached_vars:
            return (
                f"attachment_seam({var}, ...) — {var} построен НАПРЯМУЮ через "
                f"Extrude(workPart, [...], ...), а не через parent.attach(...). "
                f"Между двумя независимыми Extrude физического шва может не быть "
                f"(они просто взаимно проникают друг в друга от одной и той же "
                f"точки), и attachment_seam закономерно вернёт пустой список рёбер. "
                f"Чтобы шов реально существовал, {var} должен быть построен как "
                f"parent.attach(lambda f: <профиль на f>, thickness=..., "
                f"frame=parent.center_frame(side='same')) — то есть поставлен "
                f"НА грань родителя, а не построен независимо от той же точки "
                f"начала координат."
            )
    return None


def _check_v0_for_anchor(source: str) -> str | None:
    """При паттерне anchor() (пристрой 'от ребра') v0 у rect_profile ВСЕГДА
    должен быть 0.0 — v0=0.5 (и любое другое ненулевое значение) уводит
    половину детали внутрь родителя."""
    for var_name, call_text in _call_text_for_assignment(source, "attach"):
        uses_anchor = (
            (".anchor(" in call_text and "frame=" not in call_text)
            or ("frame=" in call_text and re.search(r"frame\s*=\s*\w*anchor\w*", call_text))
        )
        if not uses_anchor:
            continue
        v0_match = re.search(r"v0\s*=\s*([0-9.]+)", call_text)
        if v0_match and float(v0_match.group(1)) != 0.0:
            return (
                f"{var_name} = X.attach(...) построен от .anchor(...), но "
                f"rect_profile передан с v0={v0_match.group(1)} - должно быть "
                f"v0=0.0 (иначе половина детали уходит ВНУТРЬ родителя)."
            )
    return None


def _check_holes_out_of_bounds(tree: ast.AST) -> str | None:
    """Отверстие в пластине (Parallelogram + Circle в списке Extrude) не
    должно геометрически выходить за пределы внешнего контура."""
    parallelograms: dict[str, tuple] = {}
    circles: dict[str, tuple] = {}

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        var = node.targets[0].id
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        func_name = func.id if isinstance(func, ast.Name) else (
            func.attr if isinstance(func, ast.Attribute) else None
        )
        if func_name == "Parallelogram":
            side_a = _literal_value(_get_kwarg(call, "side_a") or (call.args[1] if len(call.args) > 1 else None))
            side_b = _literal_value(_get_kwarg(call, "side_b") or (call.args[2] if len(call.args) > 2 else None))
            center_node = _get_kwarg(call, "center")
            cx, cy = 0.0, 0.0
            if isinstance(center_node, ast.Tuple) and len(center_node.elts) >= 2:
                cx = _literal_value(center_node.elts[0]) or 0.0
                cy = _literal_value(center_node.elts[1]) or 0.0
            if side_a is not None and side_b is not None:
                parallelograms[var] = (side_a, side_b, cx, cy)
        if func_name == "Circle":
            radius = _literal_value(_get_kwarg(call, "radius") or (call.args[1] if len(call.args) > 1 else None))
            center_node = _get_kwarg(call, "center")
            cx, cy = None, None
            if isinstance(center_node, ast.Tuple) and len(center_node.elts) >= 2:
                cx = _literal_value(center_node.elts[0])
                cy = _literal_value(center_node.elts[1])
            elif isinstance(center_node, ast.Call):
                pf_args = center_node.args
                cx = _literal_value(pf_args[0]) if len(pf_args) > 0 else 0.0
                cy = _literal_value(pf_args[1]) if len(pf_args) > 1 else 0.0
            if radius is not None and cx is not None and cy is not None:
                circles[var] = (radius, cx, cy)

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Extrude"):
            continue
        if len(node.args) < 2 or not isinstance(node.args[1], ast.List):
            continue
        profile_vars = [e.id for e in node.args[1].elts if isinstance(e, ast.Name)]
        if not profile_vars:
            continue
        base_var = profile_vars[0]
        if base_var not in parallelograms:
            continue
        side_a, side_b, pcx, pcy = parallelograms[base_var]
        half_a, half_b = side_a / 2.0, side_b / 2.0
        for hole_var in profile_vars[1:]:
            if hole_var not in circles:
                continue
            radius, hcx, hcy = circles[hole_var]
            if abs(hcx - pcx) + radius > half_a + 1e-6 or abs(hcy - pcy) + radius > half_b + 1e-6:
                return (
                    f"{hole_var} (радиус {radius}, центр ({hcx},{hcy})) выходит за "
                    f"пределы {base_var} (side_a={side_a}, side_b={side_b}). "
                    f"Используй base.point_from_center(dx, dy)."
                )
    return None


def _check_invalid_kwargs(tree: ast.AST) -> str | None:
    """Ключевые аргументы функций/методов должны существовать в реальной
    сигнатуре библиотеки (защита от выдуманных kwargs)."""
    signatures = get_api_signatures()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            func_name = func.attr
        else:
            continue
        if func_name not in signatures:
            continue
        allowed = signatures[func_name]
        if "**" in allowed:
            continue
        for kw in node.keywords:
            if kw.arg is None:
                continue
            if kw.arg not in allowed:
                return (
                    f"{func_name}(...): неизвестный аргумент '{kw.arg}='. "
                    f"Допустимо: {sorted(a for a in allowed if a not in ('*', '**'))}."
                )
    return None


def _check_raw_profile_extrude(code: str) -> str | None:
    """profile.Extrude(...) не существует — единственные способы получить
    тело: Extrude(workPart, [profile], ...) или parent.attach(...)."""
    if re.search(r"\w+\.Extrude\s*\(", code):
        return (
            "Запрещён profile.Extrude(...). "
            "Используй parent.attach(...) или Extrude(workPart, [profile], height=...)."
        )
    return None


def _check_boolean_result_misuse(source: str, boolean_vars: set[str]) -> str | None:
    """Результат Union/Subtract/Intersect — это Boolean (.body, .new_edges),
    у него НЕТ .anchor/.attach/.attach_plate."""
    for name in boolean_vars:
        if re.search(rf"\b{re.escape(name)}\.(anchor|attach|attach_plate)\s*\(", source):
            return (
                f"{name} — результат Union, нельзя .{name}.anchor/attach. "
                "Сначала shelf = wall.attach(...), потом Union."
            )
    return None


def _check_reused_profile_in_extrudes(tree: ast.AST) -> str | None:
    """Один и тот же профиль (переменная, построенная как Parallelogram/
    Circle/Triangle/Polygon) не может быть первым элементом списка
    профилей в ДВУХ разных Extrude(...) — второй Extrude либо не
    построится, либо не вырежет отверстия, т.к. кривые уже "израсходованы"
    первым Extrude. Типичный мусорный паттерн:
        base = Circle(...)
        flange = Extrude(workPart, [base], height=...)          # мёртвая
        holes = holes_in_circle(workPart, base, ...)
        flange_with_holes = Extrude(workPart, [base] + holes, height=...)
    """
    base_var_usage: dict[str, list[int]] = {}

    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Extrude"):
            continue
        if len(node.args) < 2:
            continue
        profiles_arg = node.args[1]

        first_elem = None
        if isinstance(profiles_arg, ast.List) and profiles_arg.elts:
            first_elem = profiles_arg.elts[0]
        elif isinstance(profiles_arg, ast.BinOp) and isinstance(profiles_arg.op, ast.Add):
            # [base] + holes / [base] + holes_in_circle(...)
            left = profiles_arg.left
            if isinstance(left, ast.List) and left.elts:
                first_elem = left.elts[0]

        if isinstance(first_elem, ast.Name):
            base_var_usage.setdefault(first_elem.id, []).append(node.lineno)

    for var, lines in base_var_usage.items():
        if len(lines) > 1:
            return (
                f"Профиль '{var}' передан первым элементом списка профилей в "
                f"{len(lines)} разных Extrude(...) (строки {lines}). Каждый "
                f"профиль можно использовать только в ОДНОМ Extrude. Удали "
                f"лишний/мёртвый Extrude и оставь только тот, что реально "
                f"используется дальше (обычно последний, с отверстиями)."
            )
    return None


# ======================================================================
# Проверки: соответствие USER REQUEST (minimality, хрупкие эвристики)
# ======================================================================

def _check_minimality(tree: ast.AST, user_request: str) -> str | None:
    """Код не должен содержать Fillet/Union/holes, если в тексте запроса
    нет соответствующих ключевых слов — иначе модель "додумывает" операции,
    которые пользователь не просил."""
    called_funcs = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    holes_used = any(
        kw.arg == "holes"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for kw in node.keywords
    )

    errs = []

    if "Fillet" in called_funcs and not _FILLET_RE.search(user_request):
        errs.append(
            "В коде есть Fillet(...), в запросе нет слов про скругление — удали Fillet целиком."
        )

    bool_used = bool(called_funcs & {"Union", "Subtract", "Intersect"})
    if bool_used and not _BOOL_RE.search(user_request) and not _SEAM_BETWEEN_BODIES_RE.search(user_request):
        errs.append(
            "В коде есть Union/Subtract/Intersect, в запросе нет объединения — удали."
        )

    if holes_used and not _HOLE_RE.search(user_request):
        errs.append(
            "В коде есть holes=, в запросе нет отверстия — удали holes=."
        )

    return " ".join(errs) if errs else None


# ======================================================================
# Точка входа
# ======================================================================

def validate_code(code: str, user_request: str = "") -> str | None:
    """Возвращает текст ошибки, если код невалиден, иначе None.
    Проверки идут от самых дешёвых/специфичных к более общим; при первой
    найденной ошибке валидация останавливается — модель чинит по одной
    проблеме за retry, а не пытается угадать все сразу."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e}"

    boolean_vars = _find_boolean_result_vars(tree)

    checks = [
        lambda: _check_forbidden_snippets(code),
        lambda: _check_raw_triangle(code),
        lambda: _check_fillet_on_boolean_result(tree, boolean_vars),
        lambda: _check_seam_pattern_mismatch(code),
        lambda: _check_seam_on_unattached_body(tree, code),
        lambda: _check_v0_for_anchor(code),
        lambda: _check_holes_out_of_bounds(tree),
        lambda: _check_invalid_kwargs(tree),
        lambda: _check_raw_profile_extrude(code),
        lambda: _check_boolean_result_misuse(code, boolean_vars),
        lambda: _check_reused_profile_in_extrudes(tree),
        lambda: _check_minimality(tree, user_request),
    ]

    for check in checks:
        error = check()
        if error:
            return error

    return None