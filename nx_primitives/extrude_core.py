"""Extrude + rect_profile (из original solid.py, полностью)."""
from __future__ import annotations

from math import sqrt, radians, cos, sin

import NXOpen
import NXOpen.Features
import NXOpen.GeometricUtilities

from .base import Profile, ClosedProfile
from .geometry import _add, _subtract, _scale, _normalize3, _cross, Frame
from .shapes import Polygon, Triangle, Parallelogram
from .curves import Circle, _plane_basis

from .edges_helpers import (
    _LABELS,
    _unit_vector,
    _points_equal,
    _parse_edge_name,
    _body_edge_endpoints,
    _get_body_edges_safe,
    _find_body_edge,
    edges_after_boolean,
)

def rect_profile(
    workPart,
    frame,
    length,
    width,
    u0: float = None,
    v0: float = None,
    align_u: str = "start",   # "start" | "center" | "end"
    align_v: str = "start",   # "start" | "center" | "end"
):
    """
    Прямоугольник на Frame.

    Предпочтительный способ (понятнее модели и человеку):
        align_u="start"  → растёт от origin только в +u  (отступ + только вперёд)
        align_u="center" → origin в центре по u
        align_u="end"    → origin на дальнем краю

        align_v="start"  → растёт от origin только в +v  (паттерн B, от ребра)
        align_v="center" → origin в центре по v          (паттерн A, плашмя)

    u0/v0 — старый числовой API (доля 0..1). Если переданы — имеют приоритет.
    """

    if length <= 0 or width <= 0:
        raise ValueError(
            f"rect_profile: length и width должны быть положительными, "
            f"получено length={length}, width={width}."
        )

    align_map = {"start": 0.0, "center": 0.5, "end": 1.0}

    if u0 is None:
        if align_u not in align_map:
            raise ValueError(f"align_u must be start/center/end, got {align_u!r}")
        u0 = align_map[align_u]
    if v0 is None:
        if align_v not in align_map:
            raise ValueError(f"align_v must be start/center/end, got {align_v!r}")
        v0 = align_map[align_v]

    lo_u, hi_u = -u0 * length, (1 - u0) * length
    lo_v, hi_v = -v0 * width, (1 - v0) * width
    pts = [(lo_u, lo_v), (hi_u, lo_v), (hi_u, hi_v), (lo_u, hi_v)]
    return Polygon.on_frame(workPart, frame, pts)



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
        direction=(0.0, 0.0, 1.0),
        draft_angle: float = 0.0
    ):

        if len(profiles) == 0:
            raise ValueError("Не передано ни одного профиля.")

        if height <= 0:
            raise ValueError(f"Extrude: height должен быть положительным, получено {height}.")

        dir_mag = sqrt(direction[0]**2 + direction[1]**2 + direction[2]**2)
        if dir_mag < 1e-9:
            raise ValueError(f"Extrude: direction не может быть нулевым вектором, получено {direction}.")

        self.workPart = workPart
        self.profiles = profiles
        self.height = height
        self.direction = direction
        self.draft_angle = draft_angle

        # Флаги suppressed-состояния (см. Boolean.__init__ / _mark_suppressed).
        # По умолчанию тело активно.
        self._suppressed = False
        self._merged_body = None

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

        if draft_angle:
            builder.Draft.DraftOption = (
                NXOpen.GeometricUtilities.SimpleDraft.SimpleDraftType.SimpleFromProfile
            )

        builder.Draft.FrontDraftAngle.SetFormula(str(draft_angle))

        builder.Draft.BackDraftAngle.SetFormula(str(draft_angle))

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

    def _side_face_map(self, profile_index: int = 0) -> dict:
        """
        Возвращает {имя_боковой_грани: имя_нижнего_ребра} для всех
        боковых граней профиля, например {"abb1a1": "ab", "bcc1b1": "bc", ...}.

        Имя боковой грани - это 4 вершины по контуру САМОЙ ГРАНИ, в
        порядке нижняя_начало, нижняя_конец, верхняя_конец, верхняя_начало
        (например "abb1a1" - грань между рёбрами "ab" снизу и "a1b1"
        сверху). Используется _resolve_edge_or_face_name(), чтобы
        anchor()/attach_plate()/edge_points() принимали имя ГРАНИ, а не
        только имя ребра.
        """
        names, n = self._profile_vertex_names(profile_index)
        mapping = {}
        for i in range(n):
            a, b = names[i], names[(i + 1) % n]
            edge_name = a + b
            face_name = f"{a}{b}{b}1{a}1"
            mapping[face_name] = edge_name
        return mapping

    def side_faces(self, profile_index: int = 0) -> list:
        """
        Список имён ВСЕХ боковых граней профиля, в порядке обхода,
        например ["abb1a1", "bcc1b1", ...]. Каждое такое имя можно
        передавать напрямую как edge_name в anchor()/attach_plate()/
        edge_points() - оно автоматически сведётся к соответствующему
        нижнему ребру.
        """
        return list(self._side_face_map(profile_index).keys())

    def _resolve_edge_or_face_name(self, name: str, profile_index: int = 0) -> str:
        """
        Принимает имя РЕБРА ("ab", "aa1", ...) ИЛИ имя БОКОВОЙ ГРАНИ
        (четыре вершины по контуру грани, например "abb1a1") и
        возвращает каноническое имя РЕБРА для дальнейшей работы. Для
        имени грани возвращает её НИЖНЕЕ ребро ("abb1a1" -> "ab") -
        этого достаточно, т.к. anchor() сам поднимает Frame по высоте
        грани через направление экструзии родителя.
        """
        labels = self.profile_labels[profile_index]

        try:
            _parse_edge_name(name, labels.keys())
            return name
        except ValueError:
            pass

        face_map = self._side_face_map(profile_index)
        if name in face_map:
            return face_map[name]

        raise ValueError(
            f"'{name}' не является ни именем ребра, ни именем боковой "
            f"грани этого профиля. Имена рёбер - двухбуквенные ('ab', "
            f"'aa1', ...). Имена боковых граней - четыре вершины по "
            f"контуру грани, например 'abb1a1' (нижнее ребро 'ab' + "
            f"верхнее ребро 'a1b1'). Доступные боковые грани: "
            f"{sorted(face_map.keys())}"
        )

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

    def circular_edge(self, profile_index: int = 0, ring: str = "bottom", tol: float = 1.0):
        """
        Круглое ребро (верхнее или нижнее кольцо) экструзии профиля-окружности
        (Circle). В отличие от многоугольных профилей, у круга нет именованных
        вершин/рёбер - метод ищет ребро по его РАСПОЛОЖЕНИЮ вдоль оси
        экструзии, а не по имени.

        profile_index — индекс профиля (Circle) в списке, переданном в Extrude.
        ring          — "bottom" (плоскость исходного профиля) или "top"
                        (плоскость профиля, сдвинутая на height вдоль direction).
        tol           — допуск (мм) при сравнении положения вдоль оси.

        ПРИМЕЧАНИЕ: опирается на edge.SolidEdgeType == NXOpen.Edge.EdgeType.Circular
        и на edge.GetVertices()[0] как на опорную точку кольца (для замкнутого
        кругового ребра обычно есть ровно одна вершина - шов). Это не так
        отработано на практике, как find_edge для многоугольников - если
        упадёт с неожиданной ошибкой (например AttributeError на
        SolidEdgeType), пришли точный текст ошибки, поправим.
        """
        profile = self.profiles[profile_index]
        center = getattr(profile, "center", None)
        if center is None:
            raise ValueError(
                f"circular_edge(): профиль с индексом {profile_index} не имеет "
                f"атрибута center (ожидался Circle)."
            )

        unit_dir = _unit_vector(self.direction)
        target_h = self.height if ring == "top" else 0.0

        candidates = []
        for edge in _get_body_edges_safe(self.body):
            if getattr(edge, "SolidEdgeType", None) != NXOpen.Edge.EdgeType.Circular:
                continue
            vs = edge.GetVertices()
            if not vs:
                continue
            p = (vs[0].X, vs[0].Y, vs[0].Z)
            to_p = _subtract(p, center)
            proj = sum(a * b for a, b in zip(to_p, unit_dir))
            if abs(proj - target_h) <= tol:
                candidates.append(edge)

        if not candidates:
            raise ValueError(
                f"Круглое ребро ({ring}) не найдено для профиля {profile_index} "
                f"(искали на высоте {target_h} вдоль {self.direction} от {center})."
            )

        return candidates[0]

    def face_from_edges(self, edge_names, profile_index: int = 0):
        """
        Находит ГРАНЬ тела, содержащую ВСЕ указанные рёбра (по имени -
        строка/кортеж, как в find_edge - или уже готовый NXOpen.Edge).

        Работает через пересечение множеств граней, смежных с каждым
        ребром (edge.GetFaces()), и затем выбирает среди кандидатов ту,
        чей СОБСТВЕННЫЙ контур (face.GetEdges()) в точности совпадает
        с переданным набором рёбер - это отсекает, например, боковую
        цилиндрическую грань при поиске круглой торцевой грани по
        одному кольцевому ребру.
        """
        edge_objs = []
        for entry in edge_names:
            if hasattr(entry, "GetVertices"):
                edge_objs.append(entry)
            elif isinstance(entry, tuple):
                name, pi = entry
                edge_objs.append(self.find_edge(name, pi))
            else:
                edge_objs.append(self.find_edge(entry, profile_index))

        target_edges = set(edge_objs)

        common = None
        for edge in edge_objs:
            faces = set(edge.GetFaces())
            common = faces if common is None else (common & faces)

        if not common:
            raise ValueError(
                f"Не найдено грани, смежной со всеми рёбрами {edge_names}."
            )

        exact = [f for f in common if set(f.GetEdges()) == target_edges]
        if len(exact) == 1:
            return exact[0]

        if len(common) == 1:
            return next(iter(common))

        raise ValueError(
            f"Не удалось однозначно определить грань по рёбрам {edge_names} - "
            f"найдено {len(common)} подходящих граней, ни одна не совпадает "
            f"с контуром в точности. Передайте более полный/точный набор рёбер."
        )

    def top_face(self, profile_index: int = 0):
        """Верхняя грань (по кольцу top_edges()) для многоугольного профиля."""
        return self.face_from_edges(self.top_edges(profile_index), profile_index)

    def bottom_face(self, profile_index: int = 0):
        """Нижняя грань (по кольцу bottom_edges()) для многоугольного профиля."""
        return self.face_from_edges(self.bottom_edges(profile_index), profile_index)

    def side_face(self, edge_name: str, profile_index: int = 0):
        """
        Боковая грань по имени нижнего ребра ('ab') или имени самой грани
        ('abb1a1') - принимает то же, что side_faces()/_resolve_edge_or_face_name.
        """
        edge_name = self._resolve_edge_or_face_name(edge_name, profile_index)
        l1, l2 = _parse_edge_name(edge_name, self.profile_labels[profile_index].keys())
        names = [edge_name, l1 + l1 + "1", l2 + l2 + "1", l1 + "1" + l2 + "1"]
        return self.face_from_edges(names, profile_index)

    def circular_face(self, profile_index: int = 0, ring: str = "bottom", tol: float = 1.0):
        """Торцевая грань экструзии профиля-круга (Circle) - верх или низ."""
        edge = self.circular_edge(profile_index, ring, tol)
        return self.face_from_edges([edge], profile_index)

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
        edge_name = self._resolve_edge_or_face_name(edge_name, profile_index)
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

        ЗАЩИТА ОТ SUPPRESSED-ТЕЛ: если это тело было передано как
        `tools` в Union/Subtract/Intersect ВЫШЕ по коду, self.body
        считается подавленным (см. Boolean.__init__/_mark_suppressed).
        В этом случае find_edge САМ прозрачно переключается на поиск
        ребра по сохранённым координатам НА РЕЗУЛЬТИРУЮЩЕМ теле
        (эквивалент edges_after_boolean(self, self._merged_body, ...)) -
        вместо падения с NX-ошибкой "Операция, запрещенная на
        подавленном объекте". Это подстраховка на случай, если
        Fillet(workPart, это_тело, ...) всё же вызван по ошибке
        ПОСЛЕ булевой операции - предпочтительный способ по-прежнему
        либо делать такой Fillet ДО операции, либо использовать
        edges_on()/edges_after_boolean()/attachment_seam() явно.
        """

        if profile_index >= len(self.profile_labels):
            raise ValueError(f"Профиль с индексом {profile_index} не существует.")

        labels = self.profile_labels[profile_index]

        if not labels:
            raise ValueError(
                f"Буквенная разметка недоступна для профиля с индексом {profile_index}."
            )

        if getattr(self, "_suppressed", False):
            if self._merged_body is None:
                raise ValueError(
                    f"Тело suppressed (было передано как tools в Union/"
                    f"Subtract/Intersect), но результирующее тело неизвестно. "
                    f"Используйте edges_after_boolean(это_тело, merged.body, "
                    f"['{name}']) явно."
                )
            edges = edges_after_boolean(self, self._merged_body, [name], profile_index)
            if edges:
                return edges[0]
            raise ValueError(
                f"Ребро '{name}' не найдено на результирующем теле после "
                f"булевой операции - вероятно, оно слилось с соседней гранью "
                f"и перестало существовать как отдельное ребро. Проверьте "
                f"имя ребра или используйте edges_in_box/edges_near."
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
        name = self._resolve_edge_or_face_name(name, profile_index)
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
        if edge_name is None:
            raise ValueError(
                "anchor(): edge_name не передан (None). anchor() строит Frame "
                "НА РЕБРЕ и требует имя ребра ('ab', 'bc', ...). Если деталь "
                "должна лежать ПЛАШМЯ на грани целиком - используй "
                "center_frame(), а не anchor()."
            )

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

        if hasattr(profile, "vertices"):
            u0 = _unit_vector(_subtract(profile.vertices[1], profile.vertices[0]))
            v0 = _unit_vector(_cross(n, u0))
        else:
            u0, v0 = _plane_basis(n)

        theta = radians(spin)
        cos_t, sin_t = cos(theta), sin(theta)
        u = _add(_scale(u0, cos_t), _scale(v0, sin_t))
        v = _add(_scale(u0, -sin_t), _scale(v0, cos_t))

        if lift is None:
            lift = self.height if side == 'same' else 0.0

        origin = _add(origin, _scale(u, du))
        origin = _add(origin, _scale(v, dv))
        origin = _add(origin, _scale(n, lift))

        return Frame(origin, u, v, n)

    def radial_pattern_frames(
        self,
        count: int,
        circle_radius: float,
        profile_index: int = 0,
        side: str = 'same',
        start_angle: float = 0.0,
        spin_along_radius: bool = True,
        lift=None,
    ):
        """
        N Frame, равномерно расположенных по окружности радиуса circle_radius
        на грани профиля - аналог center_frame(), но для паттерна деталей,
        прикрепляемых по кругу (например ножки, рёбра жёсткости, бобышки
        под болты). Каждый Frame передавай по очереди в attach(frame=...).

        count             - число позиций.
        circle_radius     - радиус окружности размещения (мм) от центра профиля.
        side              - 'same'/'opposite', как в center_frame().
        start_angle       - угол первой позиции, градусы (0 = вдоль u0 профиля).
        spin_along_radius - если True (по умолчанию), каждый Frame развёрнут
            так, что его u смотрит РАДИАЛЬНО НАРУЖУ (удобно, если build()
            строит деталь "растущей от центра", например ребро жёсткости) -
            если False, все Frame имеют одинаковую ориентацию, как обычный
            center_frame(spin=0), только сдвинутые по позиции.
        lift              - как в center_frame().
        """
        if count < 1:
            raise ValueError("radial_pattern_frames(): count должен быть >= 1.")
        if circle_radius <= 0:
            raise ValueError("radial_pattern_frames(): circle_radius должен быть положительным.")

        frames = []
        for i in range(count):
            angle = start_angle + 360.0 * i / count
            if spin_along_radius:
                spin = angle
                du, dv = circle_radius, 0.0
            else:
                spin = 0.0
                theta = radians(angle)
                du = circle_radius * cos(theta)
                dv = circle_radius * sin(theta)
            frames.append(
                self.center_frame(
                    profile_index=profile_index, side=side,
                    spin=spin, du=du, dv=dv, lift=lift
                )
            )
        return frames

    def radial_frame(
        self,
        profile_index: int = 0,
        angle: float = 0.0,
        t: float = 0.5,
        lift: float = 0.0,
    ):
        """
        Frame в точке на боковой (цилиндрической) поверхности экструзии
        профиля-круга - аналог anchor(), но для круглого профиля, где нет
        именованных рёбер.

        angle — угол вокруг оси цилиндра, в градусах (0 соответствует
                произвольному, но фиксированному направлению базиса
                профиля - см. _plane_basis).
        t     — положение вдоль высоты цилиндра, доля 0..1
                (0 = нижнее основание, 1 = верхнее).
        lift  — зазор вдоль итоговой нормали (наружу от поверхности) -
                приподнять/утопить деталь относительно боковой стенки.

        Возвращает Frame: origin - на поверхности цилиндра на заданных
        angle/t; normal смотрит НАРУЖУ (радиально) - деталь, построенная
        через build(frame) в attach(), будет расти от поверхности наружу;
        u - вдоль оси цилиндра (self.direction); v - по касательной
        к окружности.
        """
        profile = self.profiles[profile_index]
        radius = getattr(profile, "radius", None)
        center = getattr(profile, "center", None)
        if radius is None or center is None:
            raise ValueError(
                "radial_frame(): профиль должен быть Circle (нужны атрибуты "
                "radius и center)."
            )

        axis = _unit_vector(self.direction)
        u0, v0 = _plane_basis(axis)

        theta = radians(angle)
        radial = _add(_scale(u0, cos(theta)), _scale(v0, sin(theta)))
        tangent = _add(_scale(u0, -sin(theta)), _scale(v0, cos(theta)))

        origin = _add(center, _scale(axis, t * self.height))
        origin = _add(origin, _scale(radial, radius + lift))

        return Frame(origin, u=axis, v=tangent, normal=radial)

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
                     Polygon.on_frame, rect_profile(...) и т.д.). ВАЖНО:
                     build ДОЛЖНА строить профиль ИМЕННО от переданного ей
                     frame (используя f), а не возвращать заранее созданный
                     профиль из внешней переменной — иначе позиция и
                     ориентация присоединения будут проигнорированы.
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
              
        # workPart на frame — на случай других helper'ов; center_hole больше
        # не зависит от _pad_length (длина передаётся явно).
        frame._pad_workPart = self.workPart
        profiles = [profile] + [h(frame) for h in (holes or [])]

        return Extrude(
            self.workPart, profiles, height=thickness, direction=direction or frame.normal
        )

