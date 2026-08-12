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
    Hide,
    rect_profile,
    attachment_seam,
    edges_after_boolean,
    edges_in_box,
    edges_near,
)

theSession = NXOpen.Session.GetSession()
workPart = theSession.Parts.Work
base = Circle(workPart, radius=20.0)
plate = Extrude(workPart, [base], height=8.0, direction=(0.0, 0.0, 1.0))
Fillet(workPart, plate, ["a", "b", "c"], radius=1.5)