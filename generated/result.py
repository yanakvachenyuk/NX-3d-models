import sys
import os

project_path = r'C:\Users\user\Desktop\NX-3d-models'

if project_path not in sys.path:
    sys.path.insert(0, project_path)

import NXOpen
from nx_primitives import (
    Triangle,
    Parallelogram,
    Polygon,
    Circle,
    Line,
    Extrude,
    Fillet,
    Union,
    Subtract,
    Intersect,
    Boolean,
    Frame,
    Chamfer,
    Hide,
    Shell,
    rect_profile,
    attachment_seam,
    edges_after_boolean,
    edges_in_box,
    edges_near,
    center_hole,
    holes_in_row,
    holes_in_circle,
    attach_plate_seam, 
    gap_offset
)

theSession = NXOpen.Session.GetSession()
workPart = theSession.Parts.Work

# Вал строится из отдельных цилиндров-ступеней, поставленных друг на
# друга по оси Z через center=(0,0,z0) у Circle - без attach(), т.к.
# у Circle-профиля нет буквенных рёбер и center_frame/anchor тут не нужны
seg1 = Extrude(workPart, [Circle(workPart, radius=20.0, center=(0.0, 0.0, 0.0))],
               height=15.0, direction=(0.0, 0.0, 1.0))
seg2 = Extrude(workPart, [Circle(workPart, radius=14.0, center=(0.0, 0.0, 15.0))],
               height=40.0, direction=(0.0, 0.0, 1.0))
seg3 = Extrude(workPart, [Circle(workPart, radius=9.0, center=(0.0, 0.0, 55.0))],
               height=20.0, direction=(0.0, 0.0, 1.0))

# Скругления галтелей на переходах ступеней делаем ДО Union: seg2/seg3
# станут tools и suppressed сразу после Union, а их собственное нижнее
# круглое ребро (circular_edge) как раз и есть будущая галтель перехода
Fillet(workPart, seg2, [seg2.circular_edge(ring='bottom')], radius=2.0)
Fillet(workPart, seg3, [seg3.circular_edge(ring='bottom')], radius=1.5)

# Фаска на свободном верхнем торце вала - тоже до Union: после Union
# seg3 suppressed, а circular_edge не умеет искать по merged.body сама
Chamfer(workPart, seg3, [seg3.circular_edge(ring='top')], setback=1.0)
# Фаска на нижнем торце - seg1 остаётся target (не suppressed), можно
# делать и после Union, но для единообразия тоже сразу
Chamfer(workPart, seg1, [seg1.circular_edge(ring='bottom')], setback=1.5)

shaft = Union(workPart, seg1, [seg2, seg3])

# Шпоночный паз на средней ступени (radius=14): строим профиль в
# плоскости XZ (y = const = -width/2) и тянем вдоль Y на всю ширину
# паза - так проще прорезать прямоугольную канавку сквозь боковую
# поверхность цилиндра, чем подбирать Frame через anchor (у круга его нет)
depth, width, length, z0 = 4.0, 6.0, 25.0, 25.0
keyway_pts = [
    (14.0 - depth, -width / 2.0, z0),
    (14.0 + 5.0,   -width / 2.0, z0),
    (14.0 + 5.0,   -width / 2.0, z0 + length),
    (14.0 - depth, -width / 2.0, z0 + length),
]
keyway = Extrude(workPart, [Polygon(workPart, keyway_pts)],
                  height=width, direction=(0.0, 1.0, 0.0))
shaft = Subtract(workPart, shaft, keyway)

# Поперечное отверстие под штифт в толстой части (seg1, radius=20):
# цилиндр с normal вдоль X, длиннее диаметра seg1, чтобы пройти насквозь
cross_pin = Extrude(
    workPart,
    [Circle(workPart, radius=3.0, center=(-25.0, 0.0, 7.0), normal=(1.0, 0.0, 0.0))],
    height=50.0, direction=(1.0, 0.0, 0.0),
)
shaft = Subtract(workPart, shaft, cross_pin)