"""Пути, модель, префикс result.py."""
from pathlib import Path
from datetime import datetime, timedelta

PROJECT = Path(__file__).resolve().parent.parent

LIBRARY_DIR = PROJECT / "nx_primitives"
PROMPTS_DIR = PROJECT / "prompts"
GENERATED_DIR = PROJECT / "generated"
LOG_DIR = PROJECT / "logs"

SYSTEM_BASE = PROMPTS_DIR / "system_base.txt"
OUTPUT_FILE = GENERATED_DIR / "result.py"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen3-coder:30b-a3b-q4_K_M"

LOG_MAX_AGE_DAYS = 14  # логи старше этого возраста удаляются при каждом запуске

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
    holes_in_row,
    attach_plate_seam, 
    gap_offset
)

theSession = NXOpen.Session.GetSession()
workPart = theSession.Parts.Work
"""

GENERATED_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
PROMPTS_DIR.mkdir(exist_ok=True)


def cleanup_old_logs(max_age_days: int = LOG_MAX_AGE_DAYS) -> int:
    """Удаляет файлы логов старше max_age_days. Возвращает число удалённых файлов."""
    cutoff = datetime.now() - timedelta(days=max_age_days)
    removed = 0
    for f in LOG_DIR.glob("*.txt"):
        try:
            if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed