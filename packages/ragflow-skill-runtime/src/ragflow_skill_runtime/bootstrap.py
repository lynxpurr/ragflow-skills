"""Helpers for release-time vendored imports.

Scripts cannot rely on importing this module before ``ragflow_skill_runtime`` is on
``sys.path``. Public scripts should therefore carry the tiny inline bootstrap
shown in the architecture doc. This module centralizes the same candidate-path
logic for tests and tools.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable


def candidate_paths(script_file: str | Path, *, env: dict[str, str] | None = None) -> list[Path]:
    """Return possible directories that contain ``ragflow_skill_runtime``."""

    env_map = os.environ if env is None else env
    script_path = Path(script_file).resolve()
    raw_candidates: Iterable[str | Path | None] = [
        env_map.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        script_path.parent / "_vendor",
        script_path.parents[1] / "_shared" if len(script_path.parents) > 1 else None,
    ]
    return [Path(p).expanduser() for p in raw_candidates if p]


def add_core_path(script_file: str | Path, *, env: dict[str, str] | None = None) -> Path | None:
    """Add the first existing candidate path to ``sys.path``."""

    for path in candidate_paths(script_file, env=env):
        if path.exists():
            sys.path.insert(0, str(path))
            return path
    return None
