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
flange_base = Circle(workPart, radius=30.0, center=(0.0, 0.0))
flange = Extrude(workPart, [flange_base] + holes_in_circle(workPart, flange_base, radii=3.0, circle_radius=24.0, n=4), height=5.0)
shaft = flange.attach(
    lambda f: Circle.on_frame(workPart, 15.0, f, u=0.0, v=0.0),
    thickness=25.0,
    frame=flange.center_frame(side='same'),
    holes=[lambda f: Circle.on_frame(workPart, 8.0, f, u=0.0, v=0.0)],  # сквозное отверстие R8 по оси
)
merged = Union(workPart, flange, shaft)
seam = attachment_seam(shaft, merged.body)
Fillet(workPart, flange, seam, radius=2.0)