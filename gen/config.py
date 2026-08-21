
"""Пути, модель, префикс result.py."""
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

LIBRARY_DIR = PROJECT / "nx_primitives"
PROMPTS_DIR = PROJECT / "prompts"
GENERATED_DIR = PROJECT / "generated"
LOG_DIR = PROJECT / "logs"

SYSTEM_BASE = PROMPTS_DIR / "system_base.txt"
OUTPUT_FILE = GENERATED_DIR / "result.py"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5-coder:14b"

RESULT_PREFIX = f"""import sys
import os

project_path = r'{PROJECT}'

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
"""

GENERATED_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
PROMPTS_DIR.mkdir(exist_ok=True)