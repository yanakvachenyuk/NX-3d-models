from __future__ import annotations

from .base import Profile, ClosedProfile
from .curves import Line
from .geometry import (
    triangle_by_3_sides,
    triangle_by_2_sides_and_angle,
    triangle_by_2_angles_and_side,
    parallelogram_points,
)


class Triangle(ClosedProfile):
    """
    Треугольник.

    Единый класс для всех способов построения треугольника.
    Создавать напрямую через __init__ не нужно — используйте
    один из фабричных методов:

    - Triangle.by_3_sides(workPart, side_a, side_b, side_c, center)
    - Triangle.by_2_sides_and_angle(workPart, side_a, side_b, angle_ab, center)
    - Triangle.by_2_angles_and_side(workPart, angle_a, angle_b, side_ab, center)

    Частные случаи (равносторонний, равнобедренный, прямоугольный)
    выражаются через эти же методы подстановкой соответствующих
    значений сторон и углов.
    """

    def __init__(self, workPart, p1, p2, p3):
        l1 = Line(workPart, p1, p2)
        l2 = Line(workPart, p2, p3)
        l3 = Line(workPart, p3, p1)

        self.lines = [l1, l2, l3]

        curves = []
        for line in self.lines:
            curves.extend(line.curves)

        super().__init__(curves, vertices=[p1, p2, p3])

    @classmethod
    def by_3_sides(cls, workPart, side_a, side_b, side_c, center=(0.0, 0.0), frame=None):
        p1, p2, p3 = triangle_by_3_sides(side_a, side_b, side_c, center)
        if frame is not None:
            p1, p2, p3 = frame.points([(p[0], p[1]) for p in (p1, p2, p3)])
        return cls(workPart, p1, p2, p3)

    @classmethod
    def by_2_sides_and_angle(cls, workPart, side_a: float, side_b: float, angle_ab: float, center=(0.0, 0.0), frame=None):
        p1, p2, p3 = triangle_by_2_sides_and_angle(side_a, side_b, angle_ab, center)
        if frame is not None:
            p1, p2, p3 = frame.points([(p[0], p[1]) for p in (p1, p2, p3)])
        return cls(workPart, p1, p2, p3)

    @classmethod
    def by_2_angles_and_side(cls, workPart, angle_a: float, angle_b: float, side_ab: float, center=(0.0, 0.0), frame=None):
        p1, p2, p3 = triangle_by_2_angles_and_side(angle_a, angle_b, side_ab, center)
        if frame is not None:
            p1, p2, p3 = frame.points([(p[0], p[1]) for p in (p1, p2, p3)])
        return cls(workPart, p1, p2, p3)


class Parallelogram(ClosedProfile):
    def __init__(self, workPart, side_a, side_b, angle, center=(0.0, 0.0), frame=None):
        self.side_a = side_a
        self.side_b = side_b
        self.angle = angle

        p1, p2, p3, p4 = parallelogram_points(side_a, side_b, angle, center)
        if frame is not None:
            p1, p2, p3, p4 = frame.points([(p[0], p[1]) for p in (p1, p2, p3, p4)])

        l1 = Line(workPart, p1, p2)
        l2 = Line(workPart, p2, p3)
        l3 = Line(workPart, p3, p4)
        l4 = Line(workPart, p4, p1)

        self.lines = [l1, l2, l3, l4]

        curves = []
        for line in self.lines:
            curves.extend(line.curves)

        super().__init__(curves, vertices=[p1, p2, p3, p4])

class Polygon(ClosedProfile):
    """
    Многоугольник по явным 3D-вершинам.
    Используется для стыковки новой фигуры к существующему телу
    (например, присоединение перпендикулярной пластины к ребру).
    """

    def __init__(self, workPart, vertices: list):
        n = len(vertices)
        lines = []

        for i in range(n):
            l = Line(workPart, vertices[i], vertices[(i + 1) % n])
            lines.append(l)

        self.lines = lines

        curves = []
        for line in lines:
            curves.extend(line.curves)

        super().__init__(curves, vertices=list(vertices))

    @classmethod
    def on_frame(cls, workPart, frame, local_vertices):
        return cls(workPart, frame.points(local_vertices))