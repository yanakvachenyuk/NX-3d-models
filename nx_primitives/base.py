from __future__ import annotations

from typing import Iterator

import NXOpen

from .geometry import _add, _subtract, _scale, _normalize3


class Profile:
    """
    Базовый класс всех двумерных профилей.
    """

    def __init__(self, curves: list[NXOpen.Curve]):
        self.curves = curves

    def __iter__(self) -> Iterator[NXOpen.Curve]:
        return iter(self.curves)

    def __len__(self) -> int:
        return len(self.curves)

    def __getitem__(self, index):
        return self.curves[index]


class ClosedProfile(Profile):
    """
    Базовый класс замкнутых плоских профилей (многоугольников).
    """

    def __init__(self, curves: list[NXOpen.Curve], vertices: list[tuple]):
        self.vertices = list(vertices)
        self.center = self._centroid(self.vertices)
        super().__init__(curves)

    @staticmethod
    def _centroid(vertices: list[tuple]) -> tuple:
        n = len(vertices)
        cx = sum(v[0] for v in vertices) / n
        cy = sum(v[1] for v in vertices) / n
        cz = sum(v[2] for v in vertices) / n
        return (cx, cy, cz)

    def corner_point(self, index: int, offset: float):
        """
        Возвращает точку, смещённую на offset от вершины index
        вдоль обеих сторон, сходящихся в этой вершине, внутрь фигуры.
        """
        n = len(self.vertices)
        p0 = self.vertices[index]
        p_next = self.vertices[(index + 1) % n]
        p_prev = self.vertices[(index - 1) % n]

        dir_next = _normalize3(_subtract(p_next, p0))
        dir_prev = _normalize3(_subtract(p_prev, p0))

        return _add(_add(p0, _scale(dir_next, offset)), _scale(dir_prev, offset))

        # base.py, добавить в ClosedProfile

    