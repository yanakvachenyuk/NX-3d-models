import sys
import os
from pathlib import Path

project_path = str(Path(__file__).resolve().parent)

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
# Базовая пластина 120х80х6
base = Parallelogram(workPart, side_a=120.0, side_b=80.0, angle=90.0)
plate = Extrude(workPart, [base], height=6.0, direction=(0.0, 0.0, 1.0))

# Центральная бобышка 20x20x6 в центре верхней грани с отверстием R3
boss_c = plate.attach(
    lambda f: rect_profile(workPart, f, length=20.0, width=20.0, u0=0.5, v0=0.5),
    thickness=6.0,
    # Бобышка лежит плашмя в центре верхней грани
    frame=plate.center_frame(side='same'),
    holes=[lambda f: Circle.on_frame(workPart, 3.0, f, u=0.0, v=0.0)],
)

# Левая бобышка 12x12x4 со смещением 30 мм влево и отверстием R2
boss_l = plate.attach(
    lambda f: rect_profile(workPart, f, length=12.0, width=12.0, u0=0.5, v0=0.5),
    thickness=4.0,
    # du=-30 мм для смещения влево относительно центра верхней грани
    frame=plate.center_frame(side='same', du=-30.0),
    holes=[lambda f: Circle.on_frame(workPart, 2.0, f, u=0.0, v=0.0)],
)

# Правая бобышка 12x12x4 со смещением 30 мм вправо и отверстием R2
boss_r = plate.attach(
    lambda f: rect_profile(workPart, f, length=12.0, width=12.0, u0=0.5, v0=0.5),
    thickness=4.0,
    # du=30 мм для смещения вправо относительно центра верхней грани
    frame=plate.center_frame(side='same', du=30.0),
    holes=[lambda f: Circle.on_frame(workPart, 2.0, f, u=0.0, v=0.0)],
)