from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ragflow_skill_runtime.kb_build import discover_markdown_documents
from ragflow_skill_runtime.manifests import load_doc_manifest


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
CONVERT_SCRIPT = ROOT / "skills" / "ragflow-doc-to-md" / "scripts" / "convert.py"


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env["RAGFLOW_SKILL_RUNTIME_PATH"] = str(RUNTIME_SRC)
    return env


class DocConvertCliTests(unittest.TestCase):
    def test_convert_passthrough_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            (input_dir / "alpha.md").write_text("# Alpha\n\nBody\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--mode",
                    "passthrough",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

            manifest = json.loads((output_dir / "doc_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["document_count"], 1)
        self.assertEqual(manifest["documents"][0]["markdown_path"], "documents/alpha.md")

    def test_convert_manifest_can_feed_kb_build_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            (input_dir / "alpha.md").write_text("# Alpha\n\nBody\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--mode",
                    "passthrough",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            manifest_path = output_dir / "doc_manifest.json"
            manifest = load_doc_manifest(manifest_path)
            docs = discover_markdown_documents(
                doc_manifest=manifest,
                manifest_base_path=manifest_path,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([doc.path.name for doc in docs], ["alpha.md"])

    def test_convert_builtin_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            (input_dir / "page.html").write_text("<h1>Alpha</h1><p>Body</p>", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--backend",
                    "builtin",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

            markdown = (output_dir / "documents" / "page.md").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Alpha", markdown)

    def test_convert_remote_backend_from_environment(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                captured["auth"] = self.headers.get("Authorization")
                captured["payload"] = json.loads(self.rfile.read(length).decode("utf-8"))
                body = json.dumps({"markdown": "# Remote\n\nConverted by fake service.\n"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                input_dir = root / "input"
                output_dir = root / "handoff"
                input_dir.mkdir()
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake")
                env = _env()
                env.update(
                    {
                        "DOC_TO_MD_BACKEND": "remote",
                        "DOC_TO_MD_REMOTE_URL": f"http://127.0.0.1:{server.server_port}/convert",
                        "DOC_TO_MD_REMOTE_API_KEY": "secret",
                        "DOC_TO_MD_TIMEOUT": "5",
                    }
                )

                result = subprocess.run(
                    [
                        sys.executable,
                        str(CONVERT_SCRIPT),
                        "--input",
                        str(input_dir),
                        "--output",
                        str(output_dir),
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=env,
                )

                markdown = (output_dir / "documents" / "paper.md").read_text(encoding="utf-8")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Remote", markdown)
        self.assertEqual(captured["auth"], "Bearer secret")
        self.assertEqual(captured["payload"]["filename"], "paper.pdf")

    def test_convert_skips_unsupported_file_in_non_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            (input_dir / "good.md").write_text("# Good\n", encoding="utf-8")
            (input_dir / "bad.bin").write_bytes(b"\x00\x01")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

        self.assertEqual(result.returncode, 1, result.stdout)
        payload = json.loads(result.stdout)
        self.assertEqual(len(payload["skipped"]), 1)
        self.assertEqual(payload["skipped"][0]["source_path"], "bad.bin")

    def test_convert_help_renders(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CONVERT_SCRIPT), "--help"],
            text=True,
            capture_output=True,
            check=False,
            env=_env(),
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--remote-url", result.stdout)
        self.assertIn("--remote-timeout", result.stdout)
        self.assertIn("--strict", result.stdout)


if __name__ == "__main__":
    unittest.main()
