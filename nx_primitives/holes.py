"""Отверстия (из original solid.py)."""
from __future__ import annotations

from .curves import Circle

def center_hole(workPart, radius: float, length: float,
                distance_from_seam: float = None, u: float = None, v: float = None):
    """
    Строит функцию-отверстие для holes= у attach().

    Только для rect_profile(..., u0=0.0, v0=0.0) (паттерн «от ребра»).
    length — тот же, что передан в rect_profile того же attach().
    distance_from_seam — расстояние от стыка до БЛИЖНЕГО края отверстия;
    radius добавляется автоматически, центр получается на v = D + R.
    По умолчанию u = length/2 (по центру вдоль ребра).

    Пример:
        holes=[center_hole(workPart, radius=2.0, length=10.0, distance_from_seam=3.0)]
    """
    def build(f):
        u_val = u if u is not None else length / 2.0
        if v is not None:
            v_val = v
        elif distance_from_seam is not None:
            v_val = distance_from_seam + radius
        else:
            raise ValueError(
                "center_hole(): нужно указать либо v=, либо distance_from_seam=."
            )
        return Circle.on_frame(workPart, radius, f, u=u_val, v=v_val)

    return build

def holes_in_row(workPart, profile, radii: list, gap: float, y: float = 0.0):
    """
    Готовые Circle для N отверстий В РЯД вдоль X, с равным шагом gap,
    симметрично относительно центра profile (использует
    profile.point_from_center - profile должен быть ClosedProfile:
    Parallelogram/Triangle/Polygon, НЕ Circle).

    Возвращает список ГОТОВЫХ Circle-объектов - используй как
    Extrude(workPart, [base] + holes_in_row(workPart, base, [3.0,5.0,7.0], gap=25.0), ...)

    НЕ нужно считать spacing/length/2 вручную - шаг между отверстиями
    задаётся напрямую через gap, ряд центрируется автоматически.
    """
    n = len(radii)
    total_width = gap * (n - 1)
    start_x = -total_width / 2.0

    result = []
    for i, r in enumerate(radii):
        x = start_x + i * gap
        result.append(Circle(workPart, radius=r, center=profile.point_from_center(x, y)))
    return result



def width_default_error():
    raise ValueError(
        "center_hole(): нужно указать либо v=, либо distance_from_seam=."
    )