from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.config import (
    ConfigError,
    load_config,
    load_skill_config,
    normalize_base_url,
    read_config_file,
)


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

    def test_read_nested_yaml_file_with_env_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.yaml"
            path.write_text(
                "ragflow:\n"
                "  base_url: https://ragflow.example.test\n"
                "  api_key: ${RAGFLOW_API_KEY}\n"
                "doc_to_md:\n"
                "  backend: mineru\n"
                "mineru:\n"
                "  base_url: https://mineru.example.test/api/v1/agent\n"
                "  api_key: ${MINERU_API_KEY}\n"
                "  cli_path: ${MINERU_CLI_PATH}\n"
                "  cli_backend: pipeline\n"
                "  timeout: 123\n"
                "  enable_table: true\n"
                "  verify_ssl: false\n",
                encoding="utf-8",
            )
            data = read_config_file(
                path,
                env={
                    "RAGFLOW_API_KEY": "ragflow-secret",
                    "MINERU_API_KEY": "mineru-secret",
                    "MINERU_CLI_PATH": "/opt/mineru/bin/mineru",
                },
            )

        self.assertEqual(data["ragflow"]["api_key"], "ragflow-secret")
        self.assertEqual(data["doc_to_md"]["backend"], "mineru")
        self.assertEqual(data["mineru"]["api_key"], "mineru-secret")
        self.assertEqual(data["mineru"]["cli_path"], "/opt/mineru/bin/mineru")
        self.assertEqual(data["mineru"]["cli_backend"], "pipeline")
        self.assertEqual(data["mineru"]["timeout"], 123)
        self.assertTrue(data["mineru"]["enable_table"])
        self.assertFalse(data["mineru"]["verify_ssl"])

    def test_load_skill_config_merges_project_local_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / ".ragflow"
            config_dir.mkdir()
            (config_dir / "config.yaml").write_text(
                "ragflow:\n"
                "  base_url: https://ragflow.example.test\n"
                "  timeout: 44\n"
                "  verify_ssl: false\n"
                "doc_to_md:\n"
                "  backend: remote\n"
                "mineru:\n"
                "  base_url: https://mineru.example.test/api/v1/agent\n"
                "  cli_path: /opt/mineru/bin/mineru\n"
                "  cli_backend: pipeline\n"
                "  timeout: 300\n",
                encoding="utf-8",
            )
            (config_dir / "config.local.yaml").write_text(
                "ragflow:\n"
                "  api_key: local-ragflow-key\n"
                "doc_to_md:\n"
                "  backend: mineru\n"
                "mineru:\n"
                "  api_key: local-mineru-key\n"
                "  timeout: 120\n",
                encoding="utf-8",
            )

            config = load_skill_config(env={}, cwd=root)

        self.assertEqual(config.ragflow.base_url, "https://ragflow.example.test/api/v1")
        self.assertEqual(config.ragflow.api_key, "local-ragflow-key")
        self.assertEqual(config.ragflow.timeout, 44)
        self.assertFalse(config.ragflow.verify_ssl)
        self.assertEqual(config.doc_to_md.backend, "mineru")
        self.assertEqual(config.mineru.base_url, "https://mineru.example.test/api/v1/agent")
        self.assertEqual(config.mineru.api_key, "local-mineru-key")
        self.assertEqual(config.mineru.cli_path, "/opt/mineru/bin/mineru")
        self.assertEqual(config.mineru.cli_backend, "pipeline")
        self.assertEqual(config.mineru.timeout, 120)
        self.assertTrue(config.mineru.verify_ssl)

    def test_load_skill_config_reads_mineru_cli_from_environment(self) -> None:
        config = load_skill_config(
            env={
                "MINERU_CLI_PATH": "/opt/mineru/bin/mineru",
                "MINERU_CLI_BACKEND": "pipeline",
            }
        )

        self.assertEqual(config.mineru.cli_path, "/opt/mineru/bin/mineru")
        self.assertEqual(config.mineru.cli_backend, "pipeline")

    def test_environment_overrides_verify_ssl(self) -> None:
        config = load_config(
            env={
                "RAGFLOW_BASE_URL": "https://ragflow.example.test",
                "RAGFLOW_VERIFY_SSL": "false",
            }
        )

        self.assertFalse(config.verify_ssl)

    def test_environment_overrides_mineru_verify_ssl(self) -> None:
        config = load_skill_config(
            env={
                "MINERU_BASE_URL": "https://mineru.example.test",
                "MINERU_VERIFY_SSL": "false",
            }
        )

        self.assertFalse(config.mineru.verify_ssl)

    def test_missing_base_url_raises_when_normalized_property_used(self) -> None:
        config = load_config(env={})
        with self.assertRaises(ConfigError):
            _ = config.normalized_base_url


if __name__ == "__main__":
    unittest.main()
