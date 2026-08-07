import sys
import os

project_path = r'c:\Users\user\Desktop\AI_3D_NX_python_optimization_project'

if project_path not in sys.path:
    sys.path.insert(0, project_path)

import NXOpen
from nx_primitives import *

theSession = NXOpen.Session.GetSession()
workPart = theSession.Parts.Work
frame = Frame((0,0,0), (1,0,0), (0,1,0))
rect = rect_profile(workPart, frame, 60, 40, u0=0.5, v0=0.5)
hole = Circle(workPart, 5, center=frame.origin, normal=frame.normal)
extrude1 = Extrude(workPart, [rect, hole], 5)