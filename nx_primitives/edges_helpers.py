"""Поиск рёбер и швы (из original solid.py, без сокращений)."""
from __future__ import annotations
from math import sqrt
from typing import TYPE_CHECKING
import NXOpen
from .geometry import _subtract, _scale

_LABELS = "abcdefghijklmnopqrstuvwxyz"

def _unit_vector(direction):
    mag = sqrt(direction[0] ** 2 + direction[1] ** 2 + direction[2] ** 2)
    return (direction[0] / mag, direction[1] / mag, direction[2] / mag)


def _points_equal(p1, p2, tol=1e-3):
    return (
        abs(p1[0] - p2[0]) < tol and
        abs(p1[1] - p2[1]) < tol and
        abs(p1[2] - p2[2]) < tol
    )


def _parse_edge_name(name, labels):
    """
    Разбирает имя ребра вида "ab" или "aa1" на две метки вершин.
    """
    candidates = sorted(labels, key=len, reverse=True)

    for l1 in candidates:
        if name.startswith(l1):
            rest = name[len(l1):]
            if rest in labels:
                return l1, rest

    raise ValueError(f"Не удалось разобрать имя ребра: {name}")


def _body_edge_endpoints(edge):
    vertices = edge.GetVertices()
    if len(vertices) != 2:
        return None
    v1 = (vertices[0].X, vertices[0].Y, vertices[0].Z)
    v2 = (vertices[1].X, vertices[1].Y, vertices[1].Z)
    return v1, v2


def _get_body_edges_safe(body):
    """
    Обёртка над body.GetEdges(), которая превращает крипто-ошибку NX
    "Операция, запрещенная на подавленном объекте" в понятное сообщение.

    ПОЧЕМУ ЭТО НУЖНО: после Union/Subtract/Intersect тело, переданное
    как `tools`, физически ПОГЛОЩАЕТСЯ в target и становится SUPPRESSED.
    Любая попытка вызвать body.GetEdges() (а значит и find_edge, и любой
    Fillet(workPart, это_тело, ...)) на таком теле после операции падает
    с малопонятной ошибкой NX. Эта функция даёт явную подсказку, что
    делать вместо этого - использовать edges_after_boolean/
    attachment_seam/Extrude.edges_on(), которые ищут рёбра по заранее
    сохранённым координатам вершин на РЕЗУЛЬТИРУЮЩЕМ теле (merged.body),
    а не на теле-инструменте.
    """
    try:
        return body.GetEdges()
    except NXOpen.NXException as e:
        raise ValueError(
            "Не удалось получить рёбра тела - похоже, это тело УЖЕ "
            "SUPPRESSED (типичная причина: оно было передано как `tools` "
            "в Union/Subtract/Intersect и физически поглощено в target - "
            "это происходит с ЛЮБЫМ телом-инструментом сразу после "
            "булевой операции). "
            "Если это тело участвовало в булевой операции - ищите его "
            "рёбра НЕ через Fillet(workPart, это_тело, ...) и НЕ через "
            "это_тело.find_edge(...), а через один из способов: "
            "edges_after_boolean(это_тело, merged.body, [имена]), "
            "attachment_seam(это_тело, merged.body), или "
            "это_тело.edges_on(merged.body, [имена]) - все они используют "
            "заранее сохранённые координаты вершин (profile_labels), а не "
            "GetEdges() самого тела, поэтому suppressed-статус для них не "
            "проблема. Альтернатива - сделать нужный Fillet ДО Union, пока "
            "тело ещё не подавлено. "
            f"Исходная ошибка NX: {e}"
        ) from e


def _find_body_edge(body, p1, p2, tol=1e-3):
    """
    Ищет ребро тела, соединяющее точки p1 и p2 (в любом порядке).

    Сначала пробует точное совпадение по обеим конечным точкам.

    Если оно не найдено — типичная причина: соседняя операция (обычно
    Fillet на смежном ребре/вершине) УКОРОТИЛА это ребро с одного или
    обоих концов примерно на величину радиуса скругления. Величина
    усечения задаётся радиусом, который find_edge не знает заранее и
    который может быть сколь угодно большим (не долями мм, а вплоть до
    десятков мм) — поэтому сравнивать по midpoint+длине с маленьким
    допуском НЕНАДЁЖНО (ровно так ломался предыдущий вариант fallback).

    Вместо этого используется геометрически более устойчивый признак:
    усечённое скруглением ребро остаётся КОЛЛИНЕАРНО исходному (лежит
    на той же прямой) и является его ПОДОТРЕЗКОМ (после проекции на
    исходное направление обе точки нового ребра попадают внутрь
    исходного отрезка, независимо от того, насколько сильно тот был
    обрезан с концов). Среди всех кандидатов на этой прямой выбирается
    тот, что даёт наибольшее перекрытие с исходным отрезком.
    """
    all_edges = _get_body_edges_safe(body)

    for edge in all_edges:

        endpoints = _body_edge_endpoints(edge)
        if endpoints is None:
            continue

        v1, v2 = endpoints

        if (_points_equal(v1, p1, tol) and _points_equal(v2, p2, tol)) or \
           (_points_equal(v1, p2, tol) and _points_equal(v2, p1, tol)):
            return edge

    # --- fallback: точный матч не найден ---
    edge_vec = _subtract(p2, p1)
    target_len = sqrt(sum(c ** 2 for c in edge_vec))

    if target_len < 1e-9:
        raise ValueError(f"Вырожденное ребро: {p1} и {p2} совпадают.")

    direction = _scale(edge_vec, 1.0 / target_len)
    perp_tol = max(tol * 50, 0.5)   # допуск на отклонение от исходной прямой
    span_tol = max(tol * 50, 0.5)   # допуск на выход проекции за пределы [0, target_len]

    best_edge = None
    best_overlap = None

    for edge in all_edges:

        endpoints = _body_edge_endpoints(edge)
        if endpoints is None:
            continue

        v1, v2 = endpoints

        seg = _subtract(v2, v1)
        seg_len = sqrt(sum(c ** 2 for c in seg))
        if seg_len < 1e-9:
            continue

        seg_dir = _scale(seg, 1.0 / seg_len)

        # коллинеарность: |dot| близко к 1 (направление то же или противоположное)
        dot = sum(a * b for a, b in zip(direction, seg_dir))
        if abs(dot) < 0.999:
            continue

        # обе точки кандидата должны лежать на исходной прямой, а не
        # просто быть параллельны ей где-то в стороне
        to_v1 = _subtract(v1, p1)
        proj1 = sum(a * b for a, b in zip(to_v1, direction))
        perp1 = sqrt(max(0.0, sum(c ** 2 for c in to_v1) - proj1 ** 2))
        if perp1 > perp_tol:
            continue

        to_v2 = _subtract(v2, p1)
        proj2 = sum(a * b for a, b in zip(to_v2, direction))
        perp2 = sqrt(max(0.0, sum(c ** 2 for c in to_v2) - proj2 ** 2))
        if perp2 > perp_tol:
            continue

        lo, hi = min(proj1, proj2), max(proj1, proj2)

        # кандидат должен лежать (почти) внутри исходного отрезка [0, target_len],
        # а не быть соседним отрезком той же бесконечной прямой
        if lo < -span_tol or hi > target_len + span_tol:
            continue

        overlap = hi - lo
        if best_overlap is None or overlap > best_overlap:
            best_edge = edge
            best_overlap = overlap

    if best_edge is not None:
        return best_edge

    raise ValueError(
        f"Не найдено ребро между точками {p1} и {p2} (в т.ч. по fallback-"
        f"поиску по коллинеарности/проекции).\n"
        f"Коллинеарный fallback ищет ЧАСТИЧНО укороченное ребро (когда "
        f"предыдущий Fillet/Chamfer срезал его с одного или обоих концов, "
        f"но прямой участок ещё остался). Если это исходное ребро было "
        f"ПОЛНОСТЬЮ заменено дугой скругления (например, radius был "
        f"сопоставим с половиной длины самого ребра или смежной стороны) — "
        f"прямого участка не остаётся вообще, и такой fallback принципиально "
        f"не может его найти, это не ошибка поиска, а исчезновение сущности.\n"
        f"В этом случае вместо поиска по имени используйте геометрический "
        f"поиск рёбер на актуальном теле: edges_in_box(body, p_min, p_max) "
        f"по bounding box нужной грани, либо edges_near(body, point, tol)."
    )


def _find_circular_edges_on_body(body, center, radius, unit_dir, target_h, tol=1.0):
    """
    Общая логика поиска круглого ребра тела по (center, radius, направление,
    высота вдоль направления). Вынесена из circular_edge(), чтобы её можно
    было применять не только к self.body, но и к произвольному body
    (например, parent_body после Union — см. attachment_seam).
    """
    candidates = []
    for edge in _get_body_edges_safe(body):
        if getattr(edge, "SolidEdgeType", None) != NXOpen.Edge.EdgeType.Circular:
            continue
        vs = edge.GetVertices()
        if not vs:
            continue
        p = (vs[0].X, vs[0].Y, vs[0].Z)
        to_p = _subtract(p, center)
        proj = sum(a * b for a, b in zip(to_p, unit_dir))
        if abs(proj - target_h) > tol:
            continue
        radial_vec = _subtract(to_p, _scale(unit_dir, proj))
        radial_dist = sqrt(sum(c ** 2 for c in radial_vec))
        if abs(radial_dist - radius) > tol:
            continue
        candidates.append(edge)
    return candidates


def edges_in_box(body, p_min, p_max):
    """
    Ищет рёбра тела, ЦЕЛИКОМ лежащие внутри осевого параллелепипеда
    [p_min, p_max] (обе вершины - это (x,y,z)).

    Нужен для рёбер без буквенного имени (например, появившихся не от
    Union, а от какой-то другой операции) — достаточно указать примерную
    область в пространстве, где ожидается ребро.

    Для рёбер, появившихся именно от Union/Subtract/Intersect, обычно
    удобнее не считать координаты вручную, а взять готовый список
    Boolean.new_edges — см. класс Boolean ниже.
    """
    result = []
    for edge in _get_body_edges_safe(body):
        endpoints = _body_edge_endpoints(edge)
        if endpoints is None:
            continue
        ok = True
        for v in endpoints:
            if not all(lo <= c <= hi for c, lo, hi in zip(v, p_min, p_max)):
                ok = False
                break
        if ok:
            result.append(edge)
    return result


def edges_near(body, point, tol=1.0):
    """
    Ищет рёбра тела, СЕРЕДИНА которых находится в пределах tol от point.
    Альтернатива edges_in_box - удобна, когда легче указать одну точку.
    """
    result = []
    for edge in _get_body_edges_safe(body):
        endpoints = _body_edge_endpoints(edge)
        if endpoints is None:
            continue
        v1, v2 = endpoints
        mid = tuple((a + b) / 2 for a, b in zip(v1, v2))
        dist = sqrt(sum((m - p) ** 2 for m, p in zip(mid, point)))
        if dist <= tol:
            result.append(edge)
    return result



def attachment_seam(child: Extrude, parent_body, profile_index: int = 0, ring: str = "bottom", tol: float = 1.0):
    """
    Рёбра шва для детали, присоединённой ВПЛОТНУЮ...
    [существующий докстринг без изменений]
    """
    profile = child.profiles[profile_index]

    # Круглый профиль (Circle) - нет буквенных вершин/profile_labels,
    # ищем шов геометрически по (center, radius) вместо имён вершин.
    # center у профиля уже в глобальных координатах (Circle.on_frame
    # ставит center = frame.point(u, v)), поэтому его можно использовать
    # напрямую как точку на искомом ребре шва.
    radius = getattr(profile, "radius", None)
    center = getattr(profile, "center", None)
    if radius is not None and center is not None:
        unit_dir = _unit_vector(child.direction)
        target_h = child.height if ring == "top" else 0.0
        return _find_circular_edges_on_body(parent_body, center, radius, unit_dir, target_h, tol)

    # существующая логика для именованных профилей (Parallelogram/Triangle/Polygon)
    labels = child.profile_labels[profile_index]
    names = [n for n in labels if (n.endswith("1") if ring == "top" else not n.endswith("1"))]
    names.sort(key=lambda n: _LABELS.index(n[0]))

    n = len(names)
    result = []
    for i in range(n):
        p1 = labels[names[i]]
        p2 = labels[names[(i + 1) % n]]
        try:
            result.append(_find_body_edge(parent_body, p1, p2))
        except ValueError:
            pass
    return result


def edges_after_boolean(child: Extrude, target_body, edge_names, profile_index: int = 0):
    """
    Обобщение attachment_seam: ищет на target_body рёбра child
    по ИМЕНАМ (посчитанным ДО boolean-операции), а не только целое
    кольцо. Рёбра, которые после объединения слились и перестали
    существовать отдельно, тихо пропускаются - как в attachment_seam.

    Это ОСНОВНОЙ способ получить рёбра тела-инструмента (tools) ПОСЛЕ
    Union/Subtract/Intersect, когда его собственное .body уже suppressed -
    в т.ч. для рёбер, НЕ являющихся швом (например top_edges() детали,
    присоединённой сбоку). См. также Extrude.edges_on() - метод-обёртка
    над этой же функцией.
    """
    result = []
    for name in edge_names:
        p1, p2 = child.edge_points(name, profile_index)
        try:
            result.append(_find_body_edge(target_body, p1, p2))
        except ValueError:
            pass
    return result

def _add(a, b):
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def attach_plate_seam(wall, plate, parent_body, side='outer', edge_name='ab', tol=1.5):
    """
    Швы после attach_plate + Union.

    side:
      'outer' — только наружный стыковой шов
      'inner' — только внутренний шов (на верхней грани пластины,
                смещённый внутрь на толщину стенки)
      'both'  — оба

    edge_name — ребро, на которое ставили стенку (то же, что в attach_plate).
    parent_body — обычно merged.body.
    """
    side = side.lower().strip()
    if side not in ('outer', 'inner', 'both'):
        raise ValueError("side должен быть 'outer', 'inner' или 'both'")

    result = []

    # --- наружный шов (через исходные рёбра стенки) ---
    if side in ('outer', 'both'):
        names = list(dict.fromkeys(wall.contact_edges()))
        result.extend(edges_after_boolean(wall, parent_body, names))

    # --- внутренний шов (ищем по положению) ---
    if side in ('inner', 'both'):
        p1, p2 = plate.edge_points(edge_name)
        mid = tuple((a + b) / 2 for a, b in zip(p1, p2))

        inward = plate.inward_direction(edge_name)
        up = _unit_vector(plate.direction)

        # внутрь на толщину стенки + на верх пластины
        inner_point = _add(
            mid,
            _add(
                _scale(inward, wall.height),
                _scale(up, plate.height),
            ),
        )
        result.extend(edges_near(parent_body, inner_point, tol=tol))

    # убрать возможные дубликаты (один и тот же Edge)
    seen = set()
    unique = []
    for e in result:
        if id(e) not in seen:
            seen.add(id(e))
            unique.append(e)
    return unique