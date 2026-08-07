from __future__ import annotations

from math import sqrt, radians, cos, sin

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

from .base import Profile, ClosedProfile
from .geometry import _add, _subtract, _scale, _normalize3, _cross, Frame
from .shapes import Polygon


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


def _find_body_edge(body, p1, p2, tol=1e-3):
    """
    Ищет ребро тела, соединяющее точки p1 и p2 (в любом порядке).
    """
    for edge in body.GetEdges():

        vertices = edge.GetVertices()

        if len(vertices) != 2:
            continue

        v1 = (vertices[0].X, vertices[0].Y, vertices[0].Z)
        v2 = (vertices[1].X, vertices[1].Y, vertices[1].Z)

        if (_points_equal(v1, p1, tol) and _points_equal(v2, p2, tol)) or \
           (_points_equal(v1, p2, tol) and _points_equal(v2, p1, tol)):
            return edge

    raise ValueError(f"Не найдено ребро между точками {p1} и {p2}")


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
    for edge in body.GetEdges():
        vertices = edge.GetVertices()
        if len(vertices) != 2:
            continue
        ok = True
        for v in vertices:
            p = (v.X, v.Y, v.Z)
            if not all(lo <= c <= hi for c, lo, hi in zip(p, p_min, p_max)):
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
    for edge in body.GetEdges():
        vertices = edge.GetVertices()
        if len(vertices) != 2:
            continue
        v1 = (vertices[0].X, vertices[0].Y, vertices[0].Z)
        v2 = (vertices[1].X, vertices[1].Y, vertices[1].Z)
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
    """
    result = []
    for name in edge_names:
        p1, p2 = child.edge_points(name, profile_index)
        try:
            result.append(_find_body_edge(target_body, p1, p2))
        except ValueError:
            pass
    return result