#!/usr/bin/env python3
"""Astromind Praxis launcher (v0.2.1) - run from any cwd.

Usage:
  python D:/path/to/astromind-praxis/run.py <command> [args...]

Equivalent to `python -m engine` from the skill root directory, but
works from any working directory (agent-friendly).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.main import main  # noqa: E402

if __name__ == "__main__":
    main()
