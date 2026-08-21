"""
rect_profile + методы присоединения Extrude:
anchor, center_frame, attach, attach_plate.

Подключается к Extrude через mixin (см. extrude_core.Extrude).
"""
from __future__ import annotations

from math import sqrt, radians, cos, sin

from .geometry import _add, _subtract, _scale, _cross, Frame
from .shapes import Polygon
from .edges_helpers import _unit_vector, _parse_edge_name


def rect_profile(
    workPart,
    frame,
    length,
    width,
    u0: float = None,
    v0: float = None,
    align_u: str = "start",
    align_v: str = "start",
):
    """
    Прямоугольник на Frame.

    align_u/align_v: \"start\" | \"center\" | \"end\"
    u0/v0 — старый API (доля 0..1); если переданы — имеют приоритет.
    """
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


class AttachMixin:
    """
    Методы присоединения. self — экземпляр Extrude
    (workPart, direction, height, profiles, edge_points, ...).
    """

    def attach_plate(
        self, edge_name, length, width, thickness,
        rise='same', grow='auto', overlap='auto',
        profile_index=0, holes=None
    ):
        # локальный import, чтобы не было цикла extrude_core ↔ attach
        from .extrude_core import Extrude

        workPart = self.workPart
        p1, p2 = self.edge_points(edge_name, profile_index)
        u = _unit_vector(_subtract(p2, p1))
        if length is None:
            length = sqrt(sum((p2[i] - p1[i]) ** 2 for i in range(3)))

        v = _unit_vector(self.direction) if rise == 'same' else (
            _scale(_unit_vector(self.direction), -1.0) if rise == 'opposite'
            else _unit_vector(rise)
        )
        n = self.inward_direction(edge_name) if grow == 'auto' else _unit_vector(grow)
        ov = self.height if overlap == 'auto' else (overlap or 0.0)

        embed_dir = self.interior_direction(edge_name, profile_index)
        dot = sum(v[i] * embed_dir[i] for i in range(3))
        origin = _add(p1, _scale(embed_dir, ov)) if dot < 0 else p1

        base = Frame(origin, u, v, n)
        a, b = base.point(0, 0), base.point(length, 0)
        c, d = base.point(length, width), base.point(0, width)
        profile = Polygon(workPart, [a, b, c, d])
        profiles = [profile] + [f(base) for f in (holes or [])]
        return Extrude(workPart, profiles, height=thickness, direction=n)

    def anchor(
        self,
        edge_name,
        profile_index: int = 0,
        t: float = 0.0,
        offset: float = 0.0,
        angle: float = 0.0,
        lift: float = 0.0,
    ):
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
        from .extrude_core import Extrude

        if frame is None:
            frame = self.anchor(edge_name, profile_index, t, offset, angle, lift)
        profile = build(frame)
        frame._pad_workPart = self.workPart
        profiles = [profile] + [h(frame) for h in (holes or [])]
        return Extrude(
            self.workPart,
            profiles,
            height=thickness,
            direction=direction or frame.normal,
        )