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
    Hide,
    rect_profile,
    attachment_seam,
    edges_after_boolean,
    edges_in_box,
    edges_near,
    center_hole,
    holes_in_row
)

theSession = NXOpen.Session.GetSession()
workPart = theSession.Parts.Work
base = Parallelogram(workPart, side_a=100.0, side_b=50.0, angle=90.0)
holes = [
    Circle(workPart, radius=6.0, center=base.point_from_center(-40.0, -20.0)),
    Circle(workPart, radius=6.0, center=base.point_from_center( 40.0, -20.0)),
    Circle(workPart, radius=6.0, center=base.point_from_center(-40.0,  20.0)),
    Circle(workPart, radius=6.0, center=base.point_from_center( 40.0,  20.0)),
]
plate = Extrude(workPart, [base] + holes, height=5.0)