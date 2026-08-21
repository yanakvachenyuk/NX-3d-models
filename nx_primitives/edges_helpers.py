"""Поиск рёбер и швы (из original solid.py, без сокращений)."""
from __future__ import annotations

from math import sqrt

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
        f"поиску по коллинеарности/проекции). Возможно, геометрия изменилась "
        f"сильнее ожидаемого после предыдущей операции Fillet/Boolean над "
        f"смежной вершиной или гранью."
    )



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



def attachment_seam(child: Extrude, parent_body, profile_index: int = 0, ring: str = "bottom"):
    """
    Рёбра шва для детали, присоединённой ВПЛОТНУЮ (через attach() /
    center_frame() с обычным lift, или attach_plate) - то есть там, где
    собственное кольцо вершин детали (a,b,c,d - "нижнее", или a1,b1,c1,d1 -
    "верхнее") совпадает с местом стыка.

    Работает надёжнее, чем Boolean.new_edges, именно для таких случаев:
    new_edges сравнивает "было/стало" и МОЖЕТ пропустить ребро шва, если
    оно совпало с уже существовавшим (собственным) ребром присоединяемой
    детали - а для деталей "впритык" это происходит практически всегда.
    attachment_seam вместо этого просто берёт координаты контура из
    child.profile_labels (посчитаны заранее, при постройке child) и ищет
    рёбра с этими координатами прямо на итоговом теле.

    child         - Extrude присоединённой детали (её .body может уже не
                    существовать после Union/Subtract - не важно, метод
                    его не использует, только profile_labels).
    parent_body   - тело, где теперь физически лежит шов
                    (обычно merged.body после Union).
    ring          - "bottom" (по умолчанию, метки без '1' - обычно это и
                    есть плоскость стыка при обычном присоединении сверху)
                    или "top" (метки с '1').

    Возвращает список найденных NXOpen.Edge. Рёбра, которые после
    объединения слились с соседней гранью и перестали существовать по
    отдельности, просто не попадают в результат (тихо пропускаются) -
    это нормально и не ошибка.
    """
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
