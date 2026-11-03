#!/usr/bin/env python3
"""Repository-independent entry point for the Baseline Audit Skill."""

import sys
from pathlib import Path

skill_root = Path(__file__).resolve().parents[1]
source = skill_root / "src"
if source.is_dir():
    sys.path.insert(0, str(source))

from baseline_audit.cli import main  # noqa: E402

raise SystemExit(main(sys.argv[1:]))
