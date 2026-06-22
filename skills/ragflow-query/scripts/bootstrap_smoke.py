#!/usr/bin/env python3
"""Smoke test for release-style vendored ``ragflow_skill_runtime`` loading."""

from __future__ import annotations

from pathlib import Path
import json
import os
import sys


def bootstrap_core() -> None:
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parent / "_vendor",
        Path(__file__).parents[1] / "_shared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            sys.path.insert(0, str(candidate))
            return


bootstrap_core()

import ragflow_skill_runtime  # noqa: E402


def main() -> None:
    print(
        json.dumps(
            {
                "ok": True,
                "version": ragflow_skill_runtime.__version__,
                "module": ragflow_skill_runtime.__file__,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
