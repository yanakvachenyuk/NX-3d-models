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
base = Parallelogram(workPart, side_a=150.0, side_b=100.0, angle=90.0)
plate = Extrude(workPart, [base], height=6.0)
# gap = 10 мм, side_a = 150, N=4, w=15 → gap = (150 - 4*15)/5 = 12
# step = w + gap = 27; du_i = -75 + 12 + 7.5 + (i-1)*27
boss_1 = plate.attach(
    lambda f: rect_profile(workPart, f, length=15.0, width=15.0, u0=0.5, v0=0.5),
    thickness=5.0, frame=plate.center_frame(side='same', du=-57.5))
boss_2 = plate.attach(
    lambda f: rect_profile(workPart, f, length=15.0, width=15.0, u0=0.5, v0=0.5),
    thickness=5.0, frame=plate.center_frame(side='same', du=-30.5))
boss_3 = plate.attach(
    lambda f: rect_profile(workPart, f, length=15.0, width=15.0, u0=0.5, v0=0.5),
    thickness=5.0, frame=plate.center_frame(side='same', du=26.5))
boss_4 = plate.attach(
    lambda f: rect_profile(workPart, f, length=15.0, width=15.0, u0=0.5, v0=0.5),
    thickness=5.0, frame=plate.center_frame(side='same', du=53.5))