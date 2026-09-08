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
base = Parallelogram(workPart, side_a=80.0, side_b=50.0, angle=90.0)
plate = Extrude(workPart, [base], height=4.0)
wall = plate.attach_plate("ab", length=None, width=15.0, thickness=3.0)
frame = wall.anchor("cd", offset=0.0, angle=0.0)
shelf = wall.attach(
    lambda f: rect_profile(workPart, f, length=20.0, width=10.0, u0=0.0, v0=0.0),
    thickness=3.0, frame=frame,
)
merged = Union(workPart, plate, wall, shelf)
edges = (
    attach_plate_seam(wall, plate, merged.body, side='both', edge_name='ab')
    + attach_plate_seam(shelf, wall, merged.body, side='both', edge_name='cd')
)
Fillet(workPart, plate, edges, radius=3.0)
