"""Отверстия (из original solid.py)."""
from __future__ import annotations
from math import radians, cos, sin

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
    if radius <= 0:
        raise ValueError(f"center_hole: radius должен быть положительным, получено {radius}.")
    if length <= 0:
        raise ValueError(f"center_hole: length должен быть положительным, получено {length}.")
    
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


def holes_in_row(workPart, profile, radii, gap: float, y: float = 0.0,
                  n: int = None, align: str = 'center',
                  edge_offset: float = None, x0: float = None):
    """
    Готовые Circle для N отверстий В РЯД вдоль X, с равным шагом gap.
    Возвращает список ГОТОВЫХ Circle-объектов - используй как
    Extrude(workPart, [base] + holes_in_row(workPart, base, [3.0,5.0,7.0], gap=25.0), ...)

    radii:
        - список чисел (длина списка = число отверстий, как раньше), ЛИБО
        - одно число (float/int) - тогда ОБЯЗАТЕЛЕН n= (сколько отверстий
          создать); все N отверстий получат этот радиус. Это защищает от
          частой ошибки "radii=[3.0]" вместо "radii=[3.0]*5" при N
          одинаковых отверстий.
          Пример: holes_in_row(workPart, base, radii=3.0, gap=12.0, n=5)

    align (положение ряда вдоль оси X):
        'center' (по умолчанию, СТАРОЕ ПОВЕДЕНИЕ, без изменений) -
            ряд центрируется симметрично вокруг центра profile.
        'start' - первое отверстие смещено на edge_offset мм от короткого
            края profile (требует edge_offset= И атрибут profile.side_a,
            т.е. profile должен быть Parallelogram с известным side_a).
            Смещение считается ДО ЦЕНТРА первого отверстия (без учёта
            radius), как и в других местах библиотеки (по аналогии с
            отступом d от краёв для угловых отверстий).

    x0: прямое указание X-координаты ПЕРВОГО отверстия (в мм от центра
        profile). Если задан - имеет наивысший приоритет, align и
        edge_offset игнорируются. Используй, если нужен произвольный
        сдвиг ряда, не описываемый через align='start'.

    y: смещение ряда ПОПЕРЁК оси (как и раньше).

    ПРИМЕРЫ:
        # старое поведение - без изменений
        holes_in_row(workPart, base, radii=[3.0, 5.0, 7.0], gap=20.0)

        # 5 одинаковых отверстий, по центру
        holes_in_row(workPart, base, radii=3.0, gap=12.0, n=5)

        # 5 одинаковых отверстий, первое - 15 мм от короткого края
        holes_in_row(workPart, base, radii=3.0, gap=12.0, n=5,
                     align='start', edge_offset=15.0)
    """
    # --- поддержка "один радиус на всех" ---
    if isinstance(radii, (int, float)):
        if n is None:
            raise ValueError(
                "holes_in_row(): если radii - одно число, нужно указать n= "
                "(сколько отверстий создать)."
            )
        radii = [float(radii)] * n
    elif n is not None and n != len(radii):
        raise ValueError(
            f"holes_in_row(): n={n} не совпадает с длиной radii ({len(radii)})."
        )

    n = len(radii)
    if n < 1:
        raise ValueError("holes_in_row(): список radii пуст.")
    for r in radii:
        if r <= 0:
            raise ValueError(f"holes_in_row: радиус должен быть положительным, получено {r}.")
    # --- вычисление стартовой X-координаты ряда ---
    if x0 is not None:
        start_x = x0
    elif align == 'start':
        if edge_offset is None:
            raise ValueError(
                "holes_in_row(): align='start' требует edge_offset=."
            )
        side_a = getattr(profile, 'side_a', None)
        if side_a is None:
            raise ValueError(
                "holes_in_row(): align='start' работает только для "
                "профилей с атрибутом side_a (например, Parallelogram)."
            )
        start_x = -(side_a / 2.0 - edge_offset)
    elif align == 'center':
        total_width = gap * (n - 1)
        start_x = -total_width / 2.0
    else:
        raise ValueError(
            f"holes_in_row(): неизвестный align='{align}' "
            "(допустимо 'center' или 'start')."
        )

    result = []
    for i, r in enumerate(radii):
        x = start_x + i * gap
        result.append(Circle(workPart, radius=r, center=profile.point_from_center(x, y)))
    return result

def holes_in_circle(workPart, profile, radii, circle_radius: float,
                     n: int = None, start_angle: float = 0.0,
                     center=(0.0, 0.0)):
    """
    Готовые Circle для N отверстий, равномерно расположенных по окружности
    (болтовой круг) радиуса circle_radius, вокруг center (смещение от
    центра profile - как в holes_in_row).

    radii:
        - список чисел (длина списка = число отверстий), ЛИБО
        - одно число - тогда ОБЯЗАТЕЛЕН n= (сколько отверстий создать),
          все N отверстий получат этот радиус.

    start_angle - угол ПЕРВОГО отверстия, в градусах, от оси X профиля
                  (0 = вправо от center), далее отверстия идут против
                  часовой стрелки с равным шагом 360/n.

    Возвращает список ГОТОВЫХ Circle - используй как и holes_in_row:
        Extrude(workPart, [base] + holes_in_circle(workPart, base, radii=3.0, circle_radius=40.0, n=6), ...)
    """
    if isinstance(radii, (int, float)):
        if n is None:
            raise ValueError(
                "holes_in_circle(): если radii - одно число, нужно указать n= "
                "(сколько отверстий создать)."
            )
        radii = [float(radii)] * n
    elif n is not None and n != len(radii):
        raise ValueError(
            f"holes_in_circle(): n={n} не совпадает с длиной radii ({len(radii)})."
        )

    n = len(radii)
    if n < 1:
        raise ValueError("holes_in_circle(): список radii пуст.")

    if circle_radius <= 0:
        raise ValueError("holes_in_circle(): circle_radius должен быть положительным.")

    for r in radii:
        if r <= 0:
            raise ValueError(f"holes_in_circle(): радиус должен быть положительным, получено {r}.")

    result = []
    for i, r in enumerate(radii):
        theta = radians(start_angle + 360.0 * i / n)
        x = center[0] + circle_radius * cos(theta)
        y = center[1] + circle_radius * sin(theta)
        result.append(Circle(workPart, radius=r, center=profile.point_from_center(x, y)))
    return result

def width_default_error():
    raise ValueError(
        "center_hole(): нужно указать либо v=, либо distance_from_seam=."
    )