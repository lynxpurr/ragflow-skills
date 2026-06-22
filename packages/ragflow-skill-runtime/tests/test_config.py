from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.config import ConfigError, load_config, normalize_base_url, read_config_file


class ConfigTests(unittest.TestCase):
    def test_normalize_base_url_adds_api_v1(self) -> None:
        self.assertEqual(normalize_base_url("https://example.test"), "https://example.test/api/v1")

    def test_load_config_from_env(self) -> None:
        config = load_config(
            env={
                "RAGFLOW_BASE_URL": "https://ragflow.example.test",
                "RAGFLOW_API_KEY": "test-key",
            }
        )
        self.assertEqual(config.base_url, "https://ragflow.example.test/api/v1")
        self.assertEqual(config.api_key, "test-key")

    def test_load_config_from_json_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "ragflow": {
                            "base_url": "https://ragflow.example.test/api/v1",
                            "api_key": "file-key",
                        }
                    }
                ),
                encoding="utf-8",
            )
            config = load_config(config_file=path, env={})
        self.assertEqual(config.base_url, "https://ragflow.example.test/api/v1")
        self.assertEqual(config.api_key, "file-key")

    def test_read_simple_yaml_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text("base_url: https://ragflow.example.test\ntimeout: 12\n", encoding="utf-8")
            data = read_config_file(path)
        self.assertEqual(data["base_url"], "https://ragflow.example.test")
        self.assertEqual(data["timeout"], 12)

    def test_missing_base_url_raises_when_normalized_property_used(self) -> None:
        config = load_config(env={})
        with self.assertRaises(ConfigError):
            _ = config.normalized_base_url


if __name__ == "__main__":
    unittest.main()
