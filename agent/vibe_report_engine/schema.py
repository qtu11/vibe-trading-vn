"""Compatibility re-export so standalone engine scripts share the single schema."""

from __future__ import annotations

from pathlib import Path
import sys

_AGENT_ROOT = str(Path(__file__).resolve().parents[1])
if _AGENT_ROOT not in sys.path:
    sys.path.insert(0, _AGENT_ROOT)

from src.reporting.schema import *  # noqa: F401,F403,E402
