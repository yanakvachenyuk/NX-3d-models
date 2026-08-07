from math import sqrt, cos, sin, radians, acos
from typing import Tuple

Point = Tuple[float, float, float]


def _recenter(points, center):
    """Сдвигает фигуру так, чтобы её центроид оказался в точке center."""
    n = len(points)
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n

    dx = center[0] - cx
    dy = center[1] - cy

    return tuple((p[0] + dx, p[1] + dy, 0.0) for p in points)


def triangle_by_3_sides(
    side_a: float,
    side_b: float,
    side_c: float,
    center=(0.0, 0.0)
) -> tuple[Point, Point, Point]:
    """
    Треугольник по трем сторонам.

    side_a — сторона между p1 и p2.
    side_b — сторона между p1 и p3.
    side_c — сторона между p2 и p3.
    """
    if (side_a + side_b <= side_c) or (side_a + side_c <= side_b) or (side_b + side_c <= side_a):
        raise ValueError("Треугольник с такими сторонами не существует")

    cx, cy = center

    p1 = (cx - side_a / 2, cy, 0.0)
    p2 = (cx + side_a / 2, cy, 0.0)

    cos_angle = (side_a ** 2 + side_b ** 2 - side_c ** 2) / (2 * side_a * side_b)
    cos_angle = max(-1.0, min(1.0, cos_angle))
    angle = acos(cos_angle)

    p3 = (
        p1[0] + side_b * cos(angle),
        p1[1] + side_b * sin(angle),
        0.0
    )

    return (p1, p2, p3)


def triangle_by_2_sides_and_angle(
    side_a: float,
    side_b: float,
    angle_ab: float,
    center=(0.0, 0.0)
) -> tuple[Point, Point, Point]:
    """
    Треугольник по двум сторонам (side_a, side_b) и углу между ними (angle_ab),
    в градусах. Сводится к triangle_by_3_sides через теорему косинусов.
    """
    angle_rad = radians(angle_ab)
    side_c = sqrt(
        side_a ** 2 + side_b ** 2 - 2 * side_a * side_b * cos(angle_rad)
    )
    return triangle_by_3_sides(side_a, side_b, side_c, center)


def triangle_by_2_angles_and_side(
    angle_a: float,
    angle_b: float,
    side_ab: float,
    center=(0.0, 0.0)
) -> tuple[Point, Point, Point]:
    """
    Треугольник по двум углам (angle_a, angle_b) и стороне между ними (side_ab),
    в градусах. Сводится к triangle_by_3_sides через теорему синусов.
    """
    if angle_a + angle_b >= 180:
        raise ValueError("Сумма двух углов должна быть меньше 180 градусов")

    angle_c = 180 - angle_a - angle_b

    a_rad = radians(angle_a)
    b_rad = radians(angle_b)
    c_rad = radians(angle_c)

    side_bc = side_ab * sin(a_rad) / sin(c_rad)
    side_ac = side_ab * sin(b_rad) / sin(c_rad)

    return triangle_by_3_sides(side_ab, side_ac, side_bc, center)


def parallelogram_points(
    side_a: float,
    side_b: float,
    angle: float,
    center=(0.0, 0.0)
) -> tuple[Point, Point, Point, Point]:
    """
    Параллелограмм по двум смежным сторонам и углу между ними.

    side_a — первая сторона (p1->p2 и p4->p3).
    side_b — вторая сторона (p1->p4 и p2->p3), под углом angle к side_a.
    angle — угол между side_a и side_b, в градусах.

    Частные случаи:
    - квадрат: side_a == side_b, angle == 90
    - прямоугольник: side_a != side_b, angle == 90
    - ромб: side_a == side_b, angle != 90
    """
    angle_rad = radians(angle)

    p1 = (0.0, 0.0)
    p2 = (side_a, 0.0)

    dx = side_b * cos(angle_rad)
    dy = side_b * sin(angle_rad)

    p4 = (dx, dy)
    p3 = (p2[0] + dx, p2[1] + dy)

    points = [
        (p1[0], p1[1], 0.0),
        (p2[0], p2[1], 0.0),
        (p3[0], p3[1], 0.0),
        (p4[0], p4[1], 0.0)
    ]

    return _recenter(points, center)

def _subtract(p1, p2):
    return (p1[0]-p2[0], p1[1]-p2[1], p1[2]-p2[2])

def _add(p1, p2):
    return (p1[0]+p2[0], p1[1]+p2[1], p1[2]+p2[2])

def _scale(p, k):
    return (p[0]*k, p[1]*k, p[2]*k)

def _normalize3(v):
    mag = sqrt(v[0]**2 + v[1]**2 + v[2]**2)
    return (v[0]/mag, v[1]/mag, v[2]/mag)


def rectangle_from_edge(p1, p2, depth: float, direction):
    """
    Прямоугольник, одна сторона которого совпадает с отрезком p1-p2,
    вторая сторона уходит вдоль direction на длину depth.

    Возвращает 4 точки в порядке p1, p2, p2+direction*depth, p1+direction*depth —
    то есть сторона p1-p2 совпадает с исходным ребром.
    """
    dir_unit = _normalize3(direction)
    offset = _scale(dir_unit, depth)

    p3 = _add(p2, offset)
    p4 = _add(p1, offset)

    return (p1, p2, p3, p4)

def rectangle_on_edge(
    p1,
    p2,
    length,
    width,
    direction
):
    """
    Строит прямоугольник произвольного размера, привязанный к ребру.

    Parameters
    ----------
    p1, p2
        Ребро, к которому примыкает прямоугольник.
    length
        Размер вдоль ребра.
    width
        Размер поперек ребра.
    direction
        Направление, в котором откладывается width.
    """

    edge = _subtract(p2, p1)
    edge_unit = _normalize3(edge)

    dir_unit = _normalize3(direction)

    p2_new = _add(p1, _scale(edge_unit, length))

    p3 = _add(p2_new, _scale(dir_unit, width))
    p4 = _add(p1, _scale(dir_unit, width))

    return (p1, p2_new, p3, p4)

def _cross(a, b):
    return (
        a[1]*b[2] - a[2]*b[1],
        a[2]*b[0] - a[0]*b[2],
        a[0]*b[1] - a[1]*b[0],
    )

class Frame:
    """
    Локальная система координат в пространстве.
    origin — точка отсчёта, u/v — базис плоскости, normal — направление толщины.
    """
    def __init__(self, origin, u, v, normal=None):
        self.origin = origin
        self.u = _normalize3(u)
        self.v = _normalize3(v)
        self.normal = _normalize3(normal) if normal is not None else _normalize3(_cross(self.u, self.v))

    def point(self, u=0.0, v=0.0, w=0.0):
        p = _add(self.origin, _scale(self.u, u))
        p = _add(p, _scale(self.v, v))
        if w:
            p = _add(p, _scale(self.normal, w))
        return p

    def points(self, local_xy):
        return [self.point(u, v) for u, v in local_xy]