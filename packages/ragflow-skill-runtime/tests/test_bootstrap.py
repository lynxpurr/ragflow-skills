from __future__ import annotations

import unittest
from pathlib import Path

from ragflow_skill_runtime.bootstrap import candidate_paths


class BootstrapTests(unittest.TestCase):
    def test_candidate_paths_include_env_and_vendor(self) -> None:
        paths = candidate_paths(
            "/tmp/example-skill/scripts/tool.py",
            env={"RAGFLOW_SKILL_RUNTIME_PATH": "/tmp/core-src"},
        )
        self.assertEqual(paths[0], Path("/tmp/core-src"))
        self.assertEqual(paths[1], Path("/tmp/example-skill/scripts/_vendor"))


if __name__ == "__main__":
    unittest.main()
