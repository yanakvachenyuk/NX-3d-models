"""Структурная валидация сгенерированного кода (только объективные ошибки API/геометрии).

Проверки семантической "минимальности" (Fillet/Union/holes должны быть в коде
только если соответствующие слова есть в запросе) сюда намеренно НЕ включены.
Валидатор видит только последнее сообщение пользователя и весь накопленный
код — в многошаговом диалоге ("пластина+стенка+скругли шов" -> "добавь бобышку")
это неизбежно даёт ложные срабатывания на элементах, добавленных в предыдущих
шагах. Эта проверка уже выполняется моделью внутри одного ответа через блок
МИНИМАЛЬНОСТЬ в системном промпте, где есть доступ к полному контексту.
Валидатор оставляет за собой только то, что можно проверить БЕЗ user_request:
объективные нарушения API и геометрии, которые сломают код в NX независимо
от того, что именно просил пользователь.
"""
from __future__ import annotations

import ast
import re

from .library_api import get_api_signatures

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

_SEAM_FUNCS = {"attach_plate_seam", "attachment_seam"}


def _find_seam_missing_union(tree: ast.AST, boolean_vars: set[str]) -> list[str]:
    """
    attach_plate_seam / attachment_seam ищут шов ТОЛЬКО в объединённом теле
    (merged.body после Union) — если Union в коде вообще нет, или seam-функция
    получает body отдельного Extrude вместо merged.body, шва как геометрии не
    существует, и Fillet упадёт в NX ("невозможно ограничить грань скругления").
    """
    errors: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _SEAM_FUNCS):
            continue
        func_name = node.func.id

        if not boolean_vars:
            errors.append(
                f"{func_name}(...) вызван, но в коде нет ни одного Union/Subtract/"
                f"Intersect — шва как геометрии не существует у раздельных Extrude. "
                f"Добавь merged = Union(workPart, ...) ПЕРЕД вызовом {func_name} "
                f"и передай merged.body соответствующим аргументом."
            )
            continue

        body_args = []
        for arg in node.args:
            if isinstance(arg, ast.Attribute) and arg.attr == "body" and isinstance(arg.value, ast.Name):
                body_args.append(arg.value.id)
        for kw in node.keywords:
            if isinstance(kw.value, ast.Attribute) and kw.value.attr == "body" and isinstance(kw.value.value, ast.Name):
                body_args.append(kw.value.value.id)

        for name in body_args:
            if name not in boolean_vars:
                errors.append(
                    f"{func_name}(...) использует '{name}.body', но '{name}' — не "
                    f"результат Union/Subtract/Intersect. Передай merged.body "
                    f"(тело результата Union), а не body отдельного Extrude."
                )
    return errors

def _find_raw_triangle_call(code: str) -> bool:
    return bool(_RAW_TRIANGLE_CALL.search(code))


def _find_boolean_result_vars(tree: ast.AST) -> set[str]:
    boolean_vars: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        func = call.func
        func_name = func.id if isinstance(func, ast.Name) else None
        if func_name in _BOOLEAN_FUNC_NAMES:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    boolean_vars.add(target.id)
    return boolean_vars


def _find_bad_fillet_extrude_args(tree: ast.AST, boolean_vars: set[str]) -> list[str]:
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
    return bad


def _find_attach_pattern_map(tree: ast.AST, source: str) -> dict[str, str]:
    lines = source.splitlines()
    pattern_map: dict[str, str] = {}
    frame_pattern_of_var: dict[str, str] = {}
    for line in lines:
        m = re.match(r"\s*(\w+)\s*=\s*\w+\.anchor\(", line)
        if m:
            frame_pattern_of_var[m.group(1)] = "edge"
        m = re.match(r"\s*(\w+)\s*=\s*\w+\.center_frame\(", line)
        if m:
            frame_pattern_of_var[m.group(1)] = "flush"

    full_source = source
    for m in re.finditer(r"(\w+)\s*=\s*\w+\.attach\(", full_source):
        child_name = m.group(1)
        start = m.end() - 1
        depth = 0
        end = start
        for j in range(start, len(full_source)):
            if full_source[j] == "(":
                depth += 1
            elif full_source[j] == ")":
                depth -= 1
                if depth == 0:
                    end = j
                    break
        call_text = full_source[start:end + 1]

        if ".anchor(" in call_text and "frame=" not in call_text:
            pattern_map[child_name] = "edge"
        elif ".center_frame(" in call_text and "frame=" not in call_text:
            pattern_map[child_name] = "flush"
        else:
            fm = re.search(r"frame\s*=\s*(\w+)", call_text)
            if fm and fm.group(1) in frame_pattern_of_var:
                pattern_map[child_name] = frame_pattern_of_var[fm.group(1)]
    return pattern_map


def _find_wrong_seam_calls(tree: ast.AST, source: str) -> list[str]:
    pattern_map = _find_attach_pattern_map(tree, source)
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
    return errors


def _find_wrong_v0_for_anchor(source: str) -> list[str]:
    errors: list[str] = []
    for m in re.finditer(r"(\w+)\s*=\s*\w+\.attach\(", source):
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
        call_text = source[start:end + 1]
        uses_anchor = (
            ".anchor(" in call_text and "frame=" not in call_text
        ) or (
            "frame=" in call_text and re.search(r"frame\s*=\s*\w*anchor\w*", call_text)
        )
        if not uses_anchor:
            continue
        v0_match = re.search(r"v0\s*=\s*([0-9.]+)", call_text)
        if v0_match and float(v0_match.group(1)) != 0.0:
            errors.append(
                f"{m.group(1)} = X.attach(...) построен от .anchor(...), но "
                f"rect_profile передан с v0={v0_match.group(1)} - должно быть "
                f"v0=0.0 (иначе половина детали уходит ВНУТРЬ родителя)."
            )
    return errors


def _literal_value(node) -> float | None:
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


def _find_holes_out_of_bounds(tree: ast.AST) -> list[str]:
    errors: list[str] = []
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
                errors.append(
                    f"{hole_var} (радиус {radius}, центр ({hcx},{hcy})) выходит за "
                    f"пределы {base_var} (side_a={side_a}, side_b={side_b}). "
                    f"Используй base.point_from_center(dx, dy)."
                )
    return errors


def _find_invalid_kwargs(tree: ast.AST, signatures: dict[str, set[str]]) -> list[str]:
    errors: list[str] = []
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
                errors.append(
                    f"{func_name}(...): неизвестный аргумент '{kw.arg}='. "
                    f"Допустимо: {sorted(a for a in allowed if a not in ('*', '**'))}."
                )
    return errors


def _find_reused_extrude_base(tree: ast.AST) -> list[str]:
    """
    Профиль (2D-контур), переданный как ПЕРВЫЙ элемент списка profiles в
    Extrude(...), физически "потребляется" NX при построении тела. Повторное
    использование той же переменной как внешнего контура во ВТОРОМ Extrude(...)
    не вырежет отверстия (или упадёт) — это структурная ошибка независимо от
    того, что просил пользователь. В отличие от прежней версии проверки, здесь
    сверяется КОНКРЕТНАЯ переменная-контур, а не общее число Extrude(...) в
    коде — так не ловятся ложные срабатывания на двух НЕЗАВИСИМЫХ телах
    (у каждого свой base), что раньше было частой причиной false positive
    в многошаговых диалогах, где код успевает накопить несколько тел.
    """
    errors: list[str] = []
    base_call_count: dict[str, int] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "Extrude"):
            continue
        if len(node.args) < 2 or not isinstance(node.args[1], ast.List):
            continue
        elts = node.args[1].elts
        if not elts or not isinstance(elts[0], ast.Name):
            continue
        base_var = elts[0].id
        base_call_count[base_var] = base_call_count.get(base_var, 0) + 1

    for base_var, count in base_call_count.items():
        if count > 1:
            errors.append(
                f"'{base_var}' передан как внешний контур в Extrude(...) {count} раз(а). "
                f"После первого Extrude контур уже использован — повторный Extrude с тем "
                f"же '{base_var}' не вырежет отверстия и/или упадёт. Собери ВСЕ профили "
                f"(внешний контур + все holes) и сделай ОДИН "
                f"Extrude(workPart, [{base_var}] + holes, ...)."
            )
    return errors


def validate_code(code: str, user_request: str = "") -> str | None:
    """
    user_request принимается только для обратной совместимости вызывающего
    кода — семантические (minimality) проверки, которые раньше сверяли
    ключевые слова запроса с составом кода, удалены: они требуют полной
    истории диалога, которой у валидатора нет, и в многошаговых сценариях
    (например, "пластина+стенка+скругли шов" -> следующим сообщением
    "добавь бобышку") давали ложные срабатывания на элементах, добавленных
    в предыдущих репликах. Эта проверка остаётся на стороне модели
    (блок МИНИМАЛЬНОСТЬ в системном промпте, где есть весь контекст).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"SyntaxError: {e}"

    for snippet in FORBIDDEN_SNIPPETS:
        if snippet in code:
            return (
                f"Код содержит запрещённый фрагмент '{snippet}'. "
                "Session/workPart и импорты уже подставлены снаружи."
            )

    if _find_raw_triangle_call(code):
        return (
            "Обнаружен вызов Triangle(workPart, ...) напрямую — такого __init__ "
            "нет, конструктор ждёт три ТОЧКИ и падает на несовместимом формате "
            "координат (например, 2D-точки вместо 3D). Треугольник строится "
            "ТОЛЬКО через фабричные методы: Triangle.by_3_sides(...), "
            "Triangle.by_2_sides_and_angle(...), Triangle.by_2_angles_and_side(...). "
            "Удали сырой вызов Triangle(...) полностью (включая мёртвый код от "
            "прошлых попыток) и замени его на подходящий фабричный метод."
        )

    boolean_vars = _find_boolean_result_vars(tree)
    bad_fillets = _find_bad_fillet_extrude_args(tree, boolean_vars)
    if bad_fillets:
        names = ", ".join(sorted(set(bad_fillets)))
        return (
            f"Fillet(workPart, {names}, ...) — результат Union. "
            f"Передай target (первый аргумент Union)."
        )

    seam_errors = _find_wrong_seam_calls(tree, code)
    seam_union_errors = _find_seam_missing_union(tree, boolean_vars)
    if seam_errors or seam_union_errors:
        return " ".join(seam_errors + seam_union_errors)

    v0_errors = _find_wrong_v0_for_anchor(code)
    if v0_errors:
        return " ".join(v0_errors)

    bounds_errors = _find_holes_out_of_bounds(tree)
    if bounds_errors:
        return " ".join(bounds_errors)

    kwarg_errors = _find_invalid_kwargs(tree, get_api_signatures())
    if kwarg_errors:
        return " ".join(kwarg_errors)

    if re.search(r"\w+\.Extrude\s*\(", code):
        return (
            "Запрещён profile.Extrude(...). "
            "Используй parent.attach(...) или Extrude(workPart, [profile], height=...)."
        )

    for name in boolean_vars:
        if re.search(rf"\b{re.escape(name)}\.(anchor|attach|attach_plate)\s*\(", code):
            return (
                f"{name} — результат Union, нельзя .{name}.anchor/attach. "
                "Сначала shelf = wall.attach(...), потом Union."
            )

    reused_base_errors = _find_reused_extrude_base(tree)
    if reused_base_errors:
        return " ".join(reused_base_errors)

    return None