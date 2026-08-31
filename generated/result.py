import sys
import os

project_path = r'C:\Users\Chelik\Desktop\NX-3d-models'

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
    Hide,
    rect_profile,
    attachment_seam,
    edges_after_boolean,
    edges_in_box,
    edges_near,
    center_hole,
    holes_in_row,
    attach_plate_seam, 
    gap_offset
)

theSession = NXOpen.Session.GetSession()
workPart = theSession.Parts.Work
# Фланцевая гайка "под ключ": круглый фланец-основание + шестигранный
# корпус (профиль через Polygon.on_frame — вершины по кругу с шагом 60°,
# порядок точек против часовой стрелки, чтобы контур не самопересекался)
# + сквозное отверстие через обе части + фаска на верхнем торце + галтель
# на переходе фланец->шестигранник.

import math

flange_r = 20.0
hex_circumradius = 14.0
hole_r = 6.0
flange_h = 4.0
hex_h = 12.0

# --- Фланец (круглое основание с отверстием) ---
flange_hole = Circle(workPart, radius=hole_r, center=(0.0, 0.0, 0.0))
flange_base = Circle(workPart, radius=flange_r, center=(0.0, 0.0, 0.0))
flange = Extrude(workPart, [flange_base, flange_hole], height=flange_h, direction=(0.0, 0.0, 1.0))

# --- Шестигранный корпус гайки, стоит поверх фланца по той же оси ---
# frame сдвинут по z на высоту фланца, чтобы шестигранник начинался
# ровно там, где заканчивается фланец
hex_frame = Frame(origin=(0.0, 0.0, flange_h), u=(1.0, 0.0, 0.0), v=(0.0, 1.0, 0.0), normal=(0.0, 0.0, 1.0))
# вершины по кругу против часовой стрелки, шаг 60° — стандартный
# правильный шестиугольник, вписанный в окружность hex_circumradius
local_hex_pts = [
    (hex_circumradius * math.cos(math.radians(60 * i)),
     hex_circumradius * math.sin(math.radians(60 * i)))
    for i in range(6)
]
hex_profile = Polygon.on_frame(workPart, hex_frame, local_hex_pts)
hex_hole = Circle(workPart, radius=hole_r, center=(0.0, 0.0, flange_h))
hex_body = Extrude(workPart, [hex_profile, hex_hole], height=hex_h, direction=(0.0, 0.0, 1.0))

# Фаска на верхнем торце шестигранника (top_edges, не задевает нижний
# контур — тот нужен нетронутым для скругления перехода к фланцу)
Fillet(workPart, hex_body, hex_body.top_edges(), radius=1.0)

merged = Union(workPart, flange, hex_body)

# Скругление "плеча" на переходе фланец -> шестигранник: нижний контур
# шестигранника (Polygon имеет буквенную разметку, bottom_edges доступен)
shoulder_names = hex_body.bottom_edges()
shoulder_edges = hex_body.edges_on(merged.body, shoulder_names)
Fillet(workPart, flange, shoulder_edges, radius=1.0)