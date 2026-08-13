import sys
import os

project_path = r'C:\Users\Chelik\NX-3d-models'

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
base = Parallelogram(workPart, side_a=120.0, side_b=70.0, angle=90.0)
plate = Extrude(workPart, [base], height=6.0, direction=(0.0, 0.0, 1.0))

boss1 = plate.attach(
    lambda f: rect_profile(workPart, f, length=20.0, width=20.0, u0=0.5, v0=0.5),
    thickness=8.0,
    frame=plate.center_frame(side='same', du=-30.0),
)
boss2 = plate.attach(
    lambda f: rect_profile(workPart, f, length=15.0, width=15.0, u0=0.5, v0=0.5),
    thickness=6.0,
    frame=plate.center_frame(side='same', du=30.0),
)

frame_ab = plate.anchor("ab", t=0.5, offset=0.0, angle=0.0)
wall_ab = plate.attach(
    lambda f: rect_profile(workPart, f, length=80.0, width=15.0, u0=0.5, v0=0.0),
    thickness=4.0,
    frame=frame_ab,
)

frame_bc = plate.anchor("bc", t=0.5, offset=0.0, angle=0.0)
wall_bc = plate.attach(
    lambda f: rect_profile(workPart, f, length=40.0, width=20.0, u0=0.5, v0=0.0),
    thickness=4.0,
    frame=frame_bc,
)

frame_da = plate.anchor("da", t=0.5, offset=0.0, angle=0.0)
wall_da = plate.attach(
    lambda f: rect_profile(workPart, f, length=40.0, width=10.0, u0=0.5, v0=0.0),
    thickness=4.0,
    frame=frame_da,
)

frame_cd = plate.anchor("cd", t=0.5, offset=0.0, angle=-90.0)
prong = plate.attach(
    lambda f: rect_profile(workPart, f, length=30.0, width=15.0, u0=0.5, v0=0.0),
    thickness=5.0,
    frame=frame_cd,
    holes=[lambda f: Circle.on_frame(workPart, 2.5, f, u=0.0, v=7.5)],
)

merged = Union(workPart, plate, [boss1, boss2, wall_ab, wall_bc, wall_da, prong])

boss1_seam = attachment_seam(boss1, merged.body)
boss2_seam = attachment_seam(boss2, merged.body)
wall_ab_seam = attachment_seam(wall_ab, merged.body)
wall_bc_seam = attachment_seam(wall_bc, merged.body)
wall_da_seam = attachment_seam(wall_da, merged.body)
prong_seam = edges_after_boolean(prong, merged.body, prong.contact_edges())

all_seams = (
    boss1_seam + boss2_seam +
    wall_ab_seam + wall_bc_seam + wall_da_seam +
    prong_seam
)
Fillet(workPart, plate, all_seams, radius=1.0)

Fillet(workPart, plate, plate.vertical_edges(), radius=2.0)