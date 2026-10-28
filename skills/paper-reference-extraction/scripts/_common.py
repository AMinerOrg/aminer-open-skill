"""Shared helpers: UTF-8 console output and JSON file IO."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent


def setup_io() -> None:
    """Make Windows consoles print non-ASCII text, and make `pdfparse` importable under `python -I`."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))


def load_json(path: str | Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump_json(obj, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
