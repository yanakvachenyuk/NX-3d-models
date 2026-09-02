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
base = Parallelogram(workPart, side_a=50.0, side_b=50.0, angle=90.0)
# явно указан уклон стенок 3° -> draft_angle=3.0
box = Extrude(workPart, [base], height=30.0, direction=(0.0, 0.0, 1.0), draft_angle=3.0)
Fillet(workPart, box, box.top_edges(), radius=2.0)