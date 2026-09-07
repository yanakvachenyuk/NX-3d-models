import sys
import os

project_path = r'C:\Users\user\Desktop\AI_3D_NX_python_optimization_project'

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
# Уменьшенный автобус: масштаб ~1/8 от предыдущей версии,
# все пропорции и логика построения сохранены без изменений.
base = Parallelogram(workPart, side_a=1250.0, side_b=310.0, angle=90.0)
body = Extrude(workPart, [base], height=375.0, direction=(0.0, 0.0, 1.0))

wheel_radius = 60.0
wheel_thickness = 35.0

margin_x = 190.0  # отступ от переда/зада, чтобы колёса не вылезали за бамперы
half_b = base.side_b / 2.0  # боковая грань кузова (y = ±half_b)

# Центр колеса по Z = radius: нижняя точка диска садится на землю (z=0),
# верхняя часть уходит в нижнюю часть кузова — так колесо не "висит в воздухе".
wheel_z = wheel_radius

def make_wheel_frame(x, side_sign):
    # u вдоль X, v вдоль Z -> круг лежит в вертикальной плоскости XZ
    # (диск виден сбоку, как настоящее колесо), normal вдоль Y -> толщина
    # (ширина шины) растёт НАРУЖУ от боковой грани кузова.
    origin = (x, side_sign * half_b, wheel_z)
    return Frame(origin=origin, u=(1.0, 0.0, 0.0), v=(0.0, 0.0, 1.0),
                 normal=(0.0, side_sign, 0.0))

x_front = base.side_a / 2.0 - margin_x
x_rear = -base.side_a / 2.0 + margin_x

wheel_fr = body.attach(
    lambda f: Circle.on_frame(workPart, wheel_radius, f, u=0.0, v=0.0),
    thickness=wheel_thickness, frame=make_wheel_frame(x_front, 1.0),
)
wheel_fl = body.attach(
    lambda f: Circle.on_frame(workPart, wheel_radius, f, u=0.0, v=0.0),
    thickness=wheel_thickness, frame=make_wheel_frame(x_front, -1.0),
)
wheel_rr = body.attach(
    lambda f: Circle.on_frame(workPart, wheel_radius, f, u=0.0, v=0.0),
    thickness=wheel_thickness, frame=make_wheel_frame(x_rear, 1.0),
)
wheel_rl = body.attach(
    lambda f: Circle.on_frame(workPart, wheel_radius, f, u=0.0, v=0.0),
    thickness=wheel_thickness, frame=make_wheel_frame(x_rear, -1.0),
)