from __future__ import annotations

from math import sqrt, radians, cos, sin

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

from .base import Profile, ClosedProfile
from .geometry import _add, _subtract, _scale, _normalize3, _cross, Frame
from .shapes import Polygon, Triangle, Parallelogram


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


def rect_profile(workPart, frame, length, width, u0: float = 0.0, v0: float = 0.0):
    """
    Прямоугольник length x width на заданном Frame.

    u0, v0 — где сидит фигура относительно frame.origin, в долях от
    своего размера (0 = растёт от origin в плюс, 0.5 = origin точно
    посередине, 1 = растёт от origin в минус):

        u0=0,   v0=0    -> растёт от origin в (+u, +v)
                           (origin на краю грани, деталь "торчит" от него)
        u0=0.5, v0=0.5  -> центрирована в origin по обеим осям
        u0=0.5, v0=0    -> центрирована по u, но растёт по v от origin
                           (origin на середине РЕБРА, деталь встаёт от него
                           вверх, а не проваливается наполовину под грань)
    """
    lo_u, hi_u = -u0 * length, (1 - u0) * length
    lo_v, hi_v = -v0 * width, (1 - v0) * width
    pts = [(lo_u, lo_v), (hi_u, lo_v), (hi_u, hi_v), (lo_u, hi_v)]
    return Polygon.on_frame(workPart, frame, pts)


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


class Extrude:
    """
    Вытягивание одного или нескольких профилей.

    Первый профиль считается внешним контуром.
    Остальные считаются внутренними контурами (например отверстиями).

    Если профиль является многоугольником (ClosedProfile), его вершинам
    присваиваются буквенные имена: нижние вершины — a, b, c, d, ...
    (в порядке profile.vertices), верхние вершины — a1, b1, c1, d1, ... .
    Разметка строится ДЛЯ КАЖДОГО профиля отдельно (и внешнего контура,
    и каждого отверстия), поэтому скруглять можно углы как самой детали,
    так и углы отверстий.

    Для указания ребра отверстия используйте кортеж (имя, индекс_профиля),
    например ("aa1", 1) — ребро первого отверстия (второй профиль
    в списке, переданном в Extrude). Для внешнего контура индекс
    профиля равен 0 и может быть опущен.
    """

    def __init__(
        self,
        workPart,
        profiles: list[Profile],
        height: float,
        direction=(0.0, 0.0, 1.0)
    ):

        if len(profiles) == 0:
            raise ValueError("Не передано ни одного профиля.")

        self.workPart = workPart
        self.profiles = profiles
        self.height = height
        self.direction = direction

        builder = workPart.Features.CreateExtrudeBuilder(
            NXOpen.Features.Feature.Null
        )

        section = workPart.Sections.CreateSection(
            0.01,
            0.01,
            0.5
        )

        builder.Section = section

        builder.AllowSelfIntersectingSection(True)

        builder.DistanceTolerance = 0.01

        builder.Limits.StartExtend.Value.SetFormula("0")

        builder.Limits.EndExtend.Value.SetFormula(str(height))

        builder.Draft.FrontDraftAngle.SetFormula("0")

        builder.Draft.BackDraftAngle.SetFormula("0")

        builder.Offset.StartOffset.SetFormula("0")

        builder.Offset.EndOffset.SetFormula("0")

        smart_profile = builder.SmartVolumeProfile

        smart_profile.OpenProfileSmartVolumeOption = False

        smart_profile.CloseProfileRule = (
            NXOpen.GeometricUtilities.
            SmartVolumeProfileBuilder.
            CloseProfileRuleType.Fci
        )

        section.DistanceTolerance = 0.01

        section.ChainingTolerance = 0.01

        section.AllowSelfIntersection(True)

        section.AllowDegenerateCurves(False)

        section.SetAllowedEntityTypes(

            NXOpen.Section.AllowTypes.OnlyCurves

        )

        rule_options = workPart.ScRuleFactory.CreateRuleOptions()

        rule_options.SetSelectedFromInactive(False)

        curves = []

        for profile in profiles:

            curves.extend(profile.curves)

        rule = workPart.ScRuleFactory.CreateRuleBaseCurveDumb(

            curves,

            rule_options

        )

        rule_options.Dispose()

        rules = [rule]

        section.AddToSection(

            rules,

            NXOpen.NXObject.Null,

            NXOpen.NXObject.Null,

            NXOpen.NXObject.Null,

            NXOpen.Point3d(0.0, 0.0, 0.0),

            NXOpen.Section.Mode.Create,

            False

        )

        origin = NXOpen.Point3d(0.0, 0.0, 0.0)

        vector = NXOpen.Vector3d(

            direction[0],

            direction[1],

            direction[2]

        )

        nx_direction = workPart.Directions.CreateDirection(

            origin,

            vector,

            NXOpen.SmartObject.UpdateOption.WithinModeling

        )

        builder.Direction = nx_direction

        builder.BooleanOperation.Type = (

            NXOpen.GeometricUtilities.

            BooleanOperation.BooleanType.Create

        )

        builder.BooleanOperation.SetTargetBodies([])

        builder.ParentFeatureInternal = False

        self.feature = builder.CommitFeature()

        builder.Destroy()

        self.body = self.feature.GetBodies()[0]

        self.profile_labels = []

        for profile in profiles:
            if isinstance(profile, ClosedProfile):
                self.profile_labels.append(
                    self._compute_labels(profile, direction, height)
                )
            else:
                self.profile_labels.append({})

        # Обратная совместимость: self.labels — разметка внешнего профиля
        self.labels = self.profile_labels[0] if self.profile_labels else {}

    def _compute_labels(self, profile, direction, height):

        unit_dir = _unit_vector(direction)

        bottom = profile.vertices

        top = [
            (
                p[0] + unit_dir[0] * height,
                p[1] + unit_dir[1] * height,
                p[2] + unit_dir[2] * height
            )
            for p in bottom
        ]

        n = len(bottom)

        if n > len(_LABELS):
            raise ValueError("Слишком много вершин для буквенной разметки.")

        labels = {}

        for i in range(n):
            labels[_LABELS[i]] = bottom[i]
            labels[_LABELS[i] + "1"] = top[i]

        return labels

    def _profile_vertex_names(self, profile_index=0):
        """
        Возвращает (список нижних буквенных имён в порядке обхода,
        число вершин) для указанного профиля. Служебный метод для
        bottom_edges/top_edges/vertical_edges.
        """
        labels = self.profile_labels[profile_index]

        if not labels:
            raise ValueError(
                f"Буквенная разметка недоступна для профиля с индексом {profile_index}."
            )

        names = sorted(
            (n for n in labels if not n.endswith("1")),
            key=lambda n: _LABELS.index(n)
        )

        return names, len(names)

    def bottom_edges(self, profile_index: int = 0):
        """
        Список имён ВСЕХ рёбер нижнего контура ("ab", "bc", ...) в
        порядке обхода — для профиля любого числа сторон. Удобнее
        и надёжнее, чем перечислять имена вручную (не нужно знать
        заранее, сколько вершин у контура).
        """
        names, n = self._profile_vertex_names(profile_index)
        return [names[i] + names[(i + 1) % n] for i in range(n)]

    def top_edges(self, profile_index: int = 0):
        """
        Список имён ВСЕХ рёбер верхнего контура ("a1b1", "b1c1", ...)
        в порядке обхода.
        """
        names, n = self._profile_vertex_names(profile_index)
        return [
            names[i] + "1" + names[(i + 1) % n] + "1"
            for i in range(n)
        ]

    def vertical_edges(self, profile_index: int = 0):
        """
        Список имён ВСЕХ вертикальных рёбер ("aa1", "bb1", ...).
        """
        names, _ = self._profile_vertex_names(profile_index)
        return [name + name + "1" for name in names]

    def contact_edges(self, profile_index: int = 0):
        """
        Контур примыкания для детали, присоединённой СБОКУ через
        anchor(edge_name, angle=-90/0/180) + attach(build=rect_profile(...,
        v0=0.0), ...) — т.е. когда деталь РАСТЁТ ОТ РЕБРА родителя, а не
        лежит плашмя на его грани целиком.

        ВАЖНО: это НЕ то же самое, что attachment_seam(ring="bottom")!
        attachment_seam(ring="bottom") предполагает, что контакт — это
        ВЕСЬ нижний контур детали (верно для boss/платформы, посаженных
        плашмя через center_frame). Для бокового примыкания это неверно:
        нижний контур детали в этом случае — это её "пол" (a,b,c,d), а
        реальная зона контакта с родителем — только ОДНА грань (та, что
        лежит в плоскости v=0 у anchor-frame'а).

        Метод предполагает СТАНДАРТНУЮ конвенцию построения такой
        детали: rect_profile(workPart, frame, length, width, v0=0.0) —
        тогда вершины a,b (первые две) всегда лежат В ПЛОСКОСТИ СТЫКА
        (frame.origin), и реальный контур примыкания — это
        ["ab", "aa1", "bb1", "a1b1"]: нижнее ребро на стыке, обе
        ближние вертикали и верхнее ребро на стыке. Дальние рёбра
        (bc, cd, da, cc1, dd1, b1c1, c1d1, d1a1) к родителю не
        относятся — это "свободные" грани самой детали.

        Если деталь НЕ прямоугольная (Polygon с произвольным контуром)
        или построена НЕ с v0=0.0 — этот метод НЕ подходит, определяйте
        контур примыкания вручную по факту построения build-функции.

        Использование (после Union):
            addon = box.attach(..., frame=box.anchor("ab", angle=-90.0))
            merged = Union(workPart, box, addon)
            contact = edges_after_boolean(addon, merged.body, addon.contact_edges())
            Fillet(workPart, box, contact, radius=1.0)
        """
        names, n = self._profile_vertex_names(profile_index)
        if n < 4:
            raise ValueError(
                "contact_edges() рассчитан на 4-вершинный (прямоугольный) "
                "профиль, построенный через rect_profile(v0=0.0)."
            )
        a, b = names[0], names[1]
        return [a + b, a + a + "1", b + b + "1", a + "1" + b + "1"]

    def inward_direction(self, edge_name: str):
        """
        Возвращает единичный вектор направления "внутрь" — от середины
        указанного ребра внешнего контура к центру этого тела, лежащий
        в плоскости основания (перпендикулярно направлению исходной
        экструзии).

        Используется по умолчанию при присоединении второй фигуры
        к этому ребру, чтобы вторая фигура строилась В СТОРОНУ
        существующего тела и не увеличивала общий габарит детали.
        """

        if not self.labels:
            raise ValueError("Буквенная разметка недоступна.")

        p1, p2 = self.edge_points(edge_name)

        midpoint = (
            (p1[0] + p2[0]) / 2,
            (p1[1] + p2[1]) / 2,
            (p1[2] + p2[2]) / 2,
        )

        outer_profile = self.profiles[0]
        center = outer_profile.center

        vec = (
            center[0] - midpoint[0],
            center[1] - midpoint[1],
            center[2] - midpoint[2],
        )

        unit_extrude_dir = _unit_vector(self.direction)

        dot = (
            vec[0] * unit_extrude_dir[0] +
            vec[1] * unit_extrude_dir[1] +
            vec[2] * unit_extrude_dir[2]
        )

        vec = (
            vec[0] - dot * unit_extrude_dir[0],
            vec[1] - dot * unit_extrude_dir[1],
            vec[2] - dot * unit_extrude_dir[2],
        )

        mag = sqrt(vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2)

        if mag < 1e-9:
            raise ValueError("Не удалось определить направление внутрь для этого ребра.")

        return (vec[0] / mag, vec[1] / mag, vec[2] / mag)

    def interior_direction(self, edge_name, profile_index=0):
        """
        Направление ОТ ребра ВНУТРЬ этого тела. Не зависит от rise/grow
        новой пластины — определяется только по тому, primed это имя
        ("a1") или нет ("a"), и по self.direction этого тела.
        """
        labels = self.profile_labels[profile_index]
        l1, _ = _parse_edge_name(edge_name, labels.keys())
        primed = l1.endswith('1')
        d = _unit_vector(self.direction)
        return d if not primed else _scale(d, -1.0)

    def find_edge(self, name: str, profile_index: int = 0):
        """
        Возвращает объект NXOpen.Edge по имени ребра.

        profile_index — индекс профиля в списке, переданном в Extrude:
        0 — внешний контур (по умолчанию), 1, 2, ... — отверстия
        в порядке их передачи.

        ВАЖНО: работает только пока self.body НЕ suppressed. Если это
        тело было передано как `tools` в Union/Subtract/Intersect - оно
        подавляется сразу после операции, и find_edge на нём больше не
        работает (см. edges_on() ниже для этого случая).
        """

        if profile_index >= len(self.profile_labels):
            raise ValueError(f"Профиль с индексом {profile_index} не существует.")

        labels = self.profile_labels[profile_index]

        if not labels:
            raise ValueError(
                f"Буквенная разметка недоступна для профиля с индексом {profile_index}."
            )

        l1, l2 = _parse_edge_name(name, labels.keys())

        return _find_body_edge(self.body, labels[l1], labels[l2])

    def edges_on(self, body, names, profile_index: int = 0):
        """
        Ищет рёбра ЭТОГО профиля (по именам, например top_edges() или
        vertical_edges()) на ПРОИЗВОЛЬНОМ теле body - а не на self.body.

        ЗАЧЕМ: после Union/Subtract/Intersect тело, переданное как
        `tools` (например деталь, присоединённая через attach()),
        физически ПОГЛОЩАЕТСЯ в target и становится SUPPRESSED. Любой
        Fillet(workPart, это_тело, [...], radius) или
        это_тело.find_edge(...) после такой операции упадёт с ошибкой
        NX "Операция, запрещенная на подавленном объекте" - потому что
        self.body для них больше не является активным телом модели.

        edges_on() не использует self.body вовсе - только заранее
        сохранённые координаты вершин (self.profile_labels) - и ищет
        их на РЕЗУЛЬТИРУЮЩЕМ теле (обычно merged.body). Поэтому
        suppressed-статус исходного тела для него не проблема.

        Это метод-обёртка над свободной функцией edges_after_boolean -
        используйте любую форму, они эквивалентны:
            boss.edges_on(merged.body, boss.top_edges())
            edges_after_boolean(boss, merged.body, boss.top_edges())

        Пример - скругление верхних рёбер боковой детали ПОСЛЕ Union:
            merged = Union(workPart, plate, boss)
            top = boss.edges_on(merged.body, boss.top_edges())
            seam = attachment_seam(boss, merged.body)
            Fillet(workPart, plate, top + seam, radius=1.0)
        """
        return edges_after_boolean(self, body, names, profile_index)

    def edge_points(self, name: str, profile_index: int = 0):
        """
        Возвращает пару 3D-точек (начало, конец) ребра по его имени.
        profile_index — см. find_edge.
        """

        if profile_index >= len(self.profile_labels):
            raise ValueError(f"Профиль с индексом {profile_index} не существует.")

        labels = self.profile_labels[profile_index]

        l1, l2 = _parse_edge_name(name, labels.keys())

        return labels[l1], labels[l2]

    def edge_frame(self, edge_name, profile_index=0, rise=None):
        p1, p2 = self.edge_points(edge_name, profile_index)
        u = _unit_vector(_subtract(p2, p1))
        v = rise if rise is not None else self.inward_direction(edge_name)
        n = _unit_vector(self.direction)
        return Frame(p1, u, v, n)

    def attach_plate(
        self, edge_name, length, width, thickness,
        rise='same', grow='auto', overlap='auto',
        profile_index=0, holes=None
    ):
        workPart = self.workPart
        p1, p2 = self.edge_points(edge_name, profile_index)
        u = _unit_vector(_subtract(p2, p1))
        if length is None:
            length = sqrt(sum((p2[i]-p1[i])**2 for i in range(3)))

        v = _unit_vector(self.direction) if rise == 'same' else (
            _scale(_unit_vector(self.direction), -1.0) if rise == 'opposite'
            else _unit_vector(rise)
        )
        n = self.inward_direction(edge_name) if grow == 'auto' else _unit_vector(grow)
        ov = self.height if overlap == 'auto' else (overlap or 0.0)

        embed_dir = self.interior_direction(edge_name, profile_index)
        dot = sum(v[i] * embed_dir[i] for i in range(3))

        # рост уже проходит сквозь толщину родителя -> сдвиг не нужен (dot > 0)
        # рост направлен НАРУЖУ от родителя -> утапливаем старт на ov (dot < 0)
        origin = _add(p1, _scale(embed_dir, ov)) if dot < 0 else p1

        base = Frame(origin, u, v, n)
        a, b = base.point(0, 0), base.point(length, 0)
        c, d = base.point(length, width), base.point(0, width)

        profile = Polygon(workPart, [a, b, c, d])
        profiles = [profile] + [f(base) for f in (holes or [])]

        return Extrude(workPart, profiles, height=thickness, direction=n)

    def vertex(self, name: str, profile_index: int = 0):
        """
        Точка в 3D по имени вершины ("a", "b1", "c", ...).

        Нужна, когда даже anchor() не хватает и хочется собрать Frame
        полностью вручную:

            origin = wall2.vertex("b1")
            frame = Frame(origin, u=(1,0,0), v=(0,0,1), normal=(0,1,0))
        """
        labels = self.profile_labels[profile_index]
        if name not in labels:
            raise ValueError(f"Вершина '{name}' не найдена (профиль {profile_index}).")
        return labels[name]

    def anchor(
        self,
        edge_name,
        profile_index: int = 0,
        t: float = 0.0,
        offset: float = 0.0,
        angle: float = 0.0,
        lift: float = 0.0,
    ):
        """
        Frame в произвольной точке РЕБРА — для деталей, растущих ОТ ребра
        под каким-то углом (перпендикулярно, наклонно, вдоль поверхности).

        t, offset  — позиция вдоль ребра (доля 0..1 + добавка в мм).
        angle      — угол поворота вокруг оси ребра, в градусах:
                    0   -> деталь встаёт в направлении экструзии родителя
                    180 -> в обратную сторону
                    90  -> ложится плашмя, в плоскости родителя
        lift       — зазор вдоль итоговой нормали (приподнять/утопить).

        Один параметр angle тут осмыслен, т.к. у детали, растущей ОТ РЕБРА,
        есть только одна степень свободы поворота (вокруг оси самого ребра).
        """
        p1, p2 = self.edge_points(edge_name, profile_index)
        edge_vec = _subtract(p2, p1)
        edge_len = sqrt(sum(c ** 2 for c in edge_vec))
        u = _scale(edge_vec, 1.0 / edge_len)

        d0 = _unit_vector(self.direction)
        n0 = self.inward_direction(edge_name)

        theta = radians(angle)
        cos_t, sin_t = cos(theta), sin(theta)
        v = _add(_scale(d0, cos_t), _scale(n0, sin_t))
        n = _add(_scale(d0, -sin_t), _scale(n0, cos_t))

        along = t * edge_len + offset
        origin = _add(p1, _scale(u, along))
        if lift:
            origin = _add(origin, _scale(n, lift))

        return Frame(origin, u, v, n)

    def center_frame(
        self,
        profile_index: int = 0,
        side: str = 'same',
        spin: float = 0.0,
        du: float = 0.0,
        dv: float = 0.0,
        lift=None,
    ):
        """
        Frame для деталей, лежащих ПЛАШМЯ на грани целиком (не на ребре).

        side  — 'same' (расти в направлении экструзии родителя, "сверху")
                или 'opposite' ("снизу").
        spin  — поворот детали В ЕЁ ЖЕ ПЛОСКОСТИ, вокруг нормали грани,
                в градусах (0, 90, 180, ... как угодно). Это ОТДЕЛЬНАЯ вещь
                от side — здесь нет риска случайно "положить деталь на ребро".
        du,dv — сдвиг в плоскости грани (вдоль итоговых u, v — уже после spin),
                в мм, от центра грани.
        lift  — зазор вдоль нормали. По умолчанию (None) равен толщине
                родителя (self.height) — деталь просто ложится ВПЛОТНУЮ на
                поверхность, не залезая внутрь родителя.
        """
        profile = self.profiles[profile_index]
        origin = profile.center

        n = _unit_vector(self.direction)
        if side == 'opposite':
            n = _scale(n, -1.0)

        u0 = _unit_vector(_subtract(profile.vertices[1], profile.vertices[0]))
        v0 = _unit_vector(_cross(n, u0))

        theta = radians(spin)
        cos_t, sin_t = cos(theta), sin(theta)
        u = _add(_scale(u0, cos_t), _scale(v0, sin_t))
        v = _add(_scale(u0, -sin_t), _scale(v0, cos_t))

        if lift is None:
            lift = self.height

        origin = _add(origin, _scale(u, du))
        origin = _add(origin, _scale(v, dv))
        origin = _add(origin, _scale(n, lift))

        return Frame(origin, u, v, n)

    def attach(
        self,
        build,
        thickness: float,
        frame=None,
        edge_name=None,
        profile_index: int = 0,
        t: float = 0.0,
        offset: float = 0.0,
        angle: float = 0.0,
        lift: float = 0.0,
        direction=None,
        holes=None,
    ):
        """
        Универсальное присоединение ЛЮБОЙ фигуры к этому телу.

        build      — функция(frame) -> Profile. Любая фигура, не только
                     прямоугольник (Circle.on_frame, Parallelogram(frame=f),
                     Polygon.on_frame, rect_profile(...) и т.д.)
        thickness  — толщина/высота получаемой детали.
        frame      — готовый Frame (например, от anchor()/center_frame()).
                     Если передан — параметры edge_name/t/offset/angle/lift
                     игнорируются.
        edge_name, profile_index, t, offset, angle, lift — см. anchor(),
                     используются, если frame не передан напрямую.
        direction  — направление экструзии; по умолчанию нормаль frame.
        holes      — список функций(frame) -> Profile, вычитаемые отверстия.
        """
        if frame is None:
            frame = self.anchor(edge_name, profile_index, t, offset, angle, lift)

        profile = build(frame)
        profiles = [profile] + [h(frame) for h in (holes or [])]

        return Extrude(
            self.workPart, profiles, height=thickness, direction=direction or frame.normal
        )


class Fillet:
    """
    Скругление рёбер тела.

    Parameters
    ----------
    extrude : Extrude
        Объект, через который ищутся рёбра по имени (нужен только для
        элементов-СТРОК/кортежей в edges; для готовых NXOpen.Edge не
        используется).

        ВАЖНО: extrude.body должен быть АКТИВНЫМ (не suppressed) телом.
        Если тело участвовало как `tools` в Union/Subtract/Intersect -
        оно подавляется сразу после операции, и передавать его сюда
        напрямую больше нельзя. В этом случае сначала получите готовые
        NXOpen.Edge через extrude.edges_on(merged.body, names) /
        edges_after_boolean(...) / attachment_seam(...), а вторым
        аргументом передайте ЛЮБОЙ ДРУГОЙ активный Extrude (например
        target, `plate`) - он используется только как "якорь" для
        готовых Edge, поиск по имени для них не выполняется.
    edges : list
        Список, где каждый элемент может быть:
        - строкой "ab"            -> ребро внешнего контура (индекс профиля 0)
        - кортежем ("ab", 1)      -> ребро профиля с индексом 1 (например,
          первое отверстие)
        - готовым NXOpen.Edge     -> используется как есть, БЕЗ поиска по
          имени (например, из Boolean.new_edges после Union/Subtract/
          Intersect, или из edges_in_box/edges_near)
        Строки/кортежи и готовые Edge можно свободно смешивать в одном списке.
    radius : float
        Радиус скругления.

    МОЖНО делать НЕСКОЛЬКО последовательных вызовов Fillet на одном и
    том же extrude с разными группами рёбер и разными радиусами (например
    сначала вертикальные рёбра радиусом 2, затем верхний контур радиусом
    1) — find_edge сам находит актуальное положение рёбер даже после
    того, как предыдущий Fillet изменил геометрию у общих вершин.

    ВАЖНО про радиус: он должен быть ЗАМЕТНО МЕНЬШЕ, чем самая короткая
    из смежных с ребром размеров (высота детали, ширина грани и т.п.).
    Если radius >= высоты/толщины детали, в которой лежит ребро — NX,
    скорее всего, откажется строить скругление с ошибкой вида
    "невозможно ограничить грань скругления". Если это случилось —
    в СЛЕДУЮЩЕЙ попытке возьми радиус заметно меньше (например вдвое).

    ВАЖНО: если ДВЕ группы рёбер (например vertical_edges присоединённой
детали и рёбра шва) ДЕЛЯТ ОБЩИЕ ВЕРШИНЫ и скругляются ОДНИМ радиусом —
их нужно передать в ОДИН вызов Fillet(workPart, extrude, group1+group2,
radius), а НЕ в раздельные последовательные вызовы. Раздельные вызовы
на общих вершинах вызывают ошибку NX "Невозможно ограничить грань
скругления" — это не значит, что не хватает ещё одного ребра другого
типа, это значит, что рёбра нужно объединить в один вызов.
    """

    def __init__(
        self,
        workPart,
        extrude: Extrude,
        edges: list,
        radius: float
    ):

        self.workPart = workPart
        self.extrude = extrude
        self.edges = edges
        self.radius = radius

        if not edges:
            raise ValueError(
                "Fillet: передан пустой список рёбер - скруглять нечего. "
                "Если это результат Union/Subtract/Intersect, проверьте "
                "merged.new_edges - похоже, шов в этом месте не появился "
                "(например, если тела слились без видимого перепада)."
            )

        edge_objs = []

        for entry in edges:
            if hasattr(entry, "GetVertices"):
                # уже готовый NXOpen.Edge - искать по имени не нужно
                edge_objs.append(entry)
            elif isinstance(entry, tuple):
                name, profile_index = entry
                edge_objs.append(extrude.find_edge(name, profile_index))
            else:
                edge_objs.append(extrude.find_edge(entry, 0))

        builder = workPart.Features.CreateEdgeBlendBuilder(
            NXOpen.Features.Feature.Null
        )

        builder.Tolerance = 0.01

        collector = workPart.ScCollectors.CreateCollector()

        rule_options = workPart.ScRuleFactory.CreateRuleOptions()

        rule_options.SetSelectedFromInactive(False)

        rule = workPart.ScRuleFactory.CreateRuleEdgeDumb(
            edge_objs,
            rule_options
        )

        rule_options.Dispose()

        collector.ReplaceRules([rule], False)

        builder.AddChainset(collector, str(radius))

        self.feature = builder.CommitFeature()

        builder.Destroy()


def _as_bodies(obj):
    """
    Приводит что угодно к списку NXOpen.Body:
    - готовое тело NXOpen.Body -> [тело]
    - объект с атрибутом .body (Extrude, Boolean, ...) -> [obj.body]
    - список/кортеж таких объектов -> объединяет рекурсивно
    """
    if isinstance(obj, (list, tuple)):
        result = []
        for o in obj:
            result.extend(_as_bodies(o))
        return result
    if hasattr(obj, "body"):
        return [obj.body]
    return [obj]


def _edge_signature(edge):
    vs = edge.GetVertices()
    if len(vs) != 2:
        return None
    p1 = (round(vs[0].X, 3), round(vs[0].Y, 3), round(vs[0].Z, 3))
    p2 = (round(vs[1].X, 3), round(vs[1].Y, 3), round(vs[1].Z, 3))
    return frozenset([p1, p2])


def _edge_signatures(bodies):
    sigs = set()
    for body in bodies:
        for edge in body.GetEdges():
            sig = _edge_signature(edge)
            if sig:
                sigs.add(sig)
    return sigs


class Boolean:
    """
    Булева операция над телами: объединение, вычитание, пересечение.

    После выполнения доступны:
        self.body                - результирующее тело
        self.new_edges           - список рёбер (NXOpen.Edge), появившихся
                                    ИМЕННО от этой операции - т.е. шов. Их
                                    не было ни у target, ни у tools ДО
                                    операции. Передавайте сразу в Fillet(...)
                                    - без всяких координат.
        self.removed_edges_count - сколько рёбер пропало (для справки/
                                    отладки, например если общая грань
                                    исчезла)

    ВАЖНО (частый источник ошибок): сразу ПОСЛЕ этой операции тело(а),
    переданные как `tools`, становятся SUPPRESSED - NX физически
    поглощает их в target. Это означает:
      - tools.body.GetEdges() и всё, что на нём основано (find_edge,
        Fillet(workPart, tools, [...], radius)), больше не работает и
        падает с ошибкой NX "Операция, запрещенная на подавленном объекте".
      - Это касается ЛЮБЫХ рёбер tools, не только шва - в т.ч.
        tools.top_edges()/bottom_edges()/vertical_edges(), если их
        нужно скруглить ПОСЛЕ Union.
      - Если такие рёбра нужны - используйте
        tools.edges_on(merged.body, names) / edges_after_boolean(...) /
        attachment_seam(...) - они ищут рёбра по заранее сохранённым
        координатам НА РЕЗУЛЬТИРУЮЩЕМ теле (merged.body), а не через
        само tools.body.
      - Либо сделайте нужный Fillet на tools ДО вызова Union/Subtract/
        Intersect, пока тело ещё активно.
    """

    _KIND_MAP = {
        "unite": NXOpen.Features.Feature.BooleanType.Unite,
        "subtract": NXOpen.Features.Feature.BooleanType.Subtract,
        "intersect": NXOpen.Features.Feature.BooleanType.Intersect,
    }

    def __init__(self, workPart, target, tools, kind="unite", tolerance=0.01):
        self.workPart = workPart
        self.kind = kind

        target_bodies = _as_bodies(target)
        tool_bodies = _as_bodies(tools)

        if not target_bodies:
            raise ValueError("Boolean: target не содержит ни одного тела.")
        if not tool_bodies:
            raise ValueError("Boolean: tools не содержит ни одного тела.")

        # запоминаем рёбра ДО операции, пока оба тела ещё существуют
        before_sigs = _edge_signatures(target_bodies) | _edge_signatures(tool_bodies)

        builder = workPart.Features.CreateBooleanBuilderUsingCollector(
            NXOpen.Features.BooleanFeature.Null
        )
        builder.Tolerance = tolerance
        builder.Operation = self._KIND_MAP[kind]

        rule_options_t = workPart.ScRuleFactory.CreateRuleOptions()
        rule_options_t.SetSelectedFromInactive(False)
        target_rule = workPart.ScRuleFactory.CreateRuleBodyDumb(
            target_bodies, True, rule_options_t
        )
        rule_options_t.Dispose()
        target_collector = workPart.ScCollectors.CreateCollector()
        target_collector.ReplaceRules([target_rule], False)
        builder.TargetBodyCollector = target_collector

        rule_options_k = workPart.ScRuleFactory.CreateRuleOptions()
        rule_options_k.SetSelectedFromInactive(False)
        tool_rule = workPart.ScRuleFactory.CreateRuleBodyDumb(
            tool_bodies, True, rule_options_k
        )
        rule_options_k.Dispose()
        tool_collector = workPart.ScCollectors.CreateCollector()
        tool_collector.ReplaceRules([tool_rule], False)
        builder.ToolBodyCollector = tool_collector

        builder.BooleanRegionSelect.AssignTargets(target_bodies)
        builder.BooleanRegionSelect.AssignTargets(tool_bodies)

        self.feature = builder.Commit()
        builder.Destroy()

        self.body = target_bodies[0] if target_bodies else None

        # сравниваем "было / стало" - без единой ручной координаты
        self.new_edges = []
        after_sigs = set()
        if self.body:
            for edge in self.body.GetEdges():
                sig = _edge_signature(edge)
                if sig:
                    after_sigs.add(sig)
                    if sig not in before_sigs:
                        self.new_edges.append(edge)

        self.removed_edges_count = len(before_sigs - after_sigs)


class Union(Boolean):
    def __init__(self, workPart, target, tools, tolerance=0.01):
        super().__init__(workPart, target, tools, kind="unite", tolerance=tolerance)


class Subtract(Boolean):
    def __init__(self, workPart, target, tools, tolerance=0.01):
        super().__init__(workPart, target, tools, kind="subtract", tolerance=tolerance)


class Intersect(Boolean):
    def __init__(self, workPart, target, tools, tolerance=0.01):
        super().__init__(workPart, target, tools, kind="intersect", tolerance=tolerance)


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