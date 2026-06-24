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


def _write_fake_mineru_cli(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "out_dir = Path(args[args.index('-o') + 1])\n"
        "source = Path(args[args.index('-p') + 1])\n"
        "backend = args[args.index('-b') + 1]\n"
        "out_dir.mkdir(parents=True, exist_ok=True)\n"
        "(out_dir / (source.stem + '.md')).write_text(\n"
        "    f'# MinerU CLI\\n\\nbackend={backend}\\nsource={source.name}\\n',\n"
        "    encoding='utf-8',\n"
        ")\n"
        "log = os.environ.get('FAKE_MINERU_LOG')\n"
        "if log:\n"
        "    Path(log).write_text('\\n'.join(args), encoding='utf-8')\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_fake_mineru_cli_with_image(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "out_dir = Path(args[args.index('-o') + 1])\n"
        "source = Path(args[args.index('-p') + 1])\n"
        "images_dir = out_dir / 'images'\n"
        "images_dir.mkdir(parents=True, exist_ok=True)\n"
        "(images_dir / 'chart.jpg').write_bytes(b'fake image bytes')\n"
        "(out_dir / (source.stem + '.md')).write_text(\n"
        "    '# MinerU CLI Assets\\n\\n![chart](images/chart.jpg)\\n',\n"
        "    encoding='utf-8',\n"
        ")\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


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
            quality_report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["document_count"], 1)
        self.assertEqual(payload["quality_gate"]["status"], "PASS")
        self.assertEqual(quality_report["gate"]["status"], "PASS")
        self.assertEqual(manifest["quality_gate"]["status"], "PASS")
        self.assertEqual(manifest["quality_report"], "quality_report.json")
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

    def test_package_rich_creates_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            (input_dir / "alpha.md").write_text("# Alpha\n\nBody\n", encoding="utf-8")

            convert_result = subprocess.run(
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
            package_result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "package",
                    "--handoff",
                    str(output_dir),
                    "--rich",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
            artifact_index = json.loads((output_dir / "artifact_index.json").read_text(encoding="utf-8"))
            suggestions = json.loads((output_dir / "profile_suggestions.json").read_text(encoding="utf-8"))
            readme_exists = (output_dir / "package_readme.md").exists()

        self.assertEqual(convert_result.returncode, 0, convert_result.stderr)
        self.assertEqual(package_result.returncode, 0, package_result.stderr)
        payload = json.loads(package_result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["package"]["schema"], "ragflow_handoff_package_v1")
        self.assertEqual(metadata["schema"], "ragflow_document_metadata_v1")
        self.assertEqual(artifact_index["schema"], "ragflow_artifact_index_v1")
        self.assertEqual(suggestions["schema"], "ragflow_profile_suggestions_v1")
        self.assertTrue(readme_exists)

    def test_postprocess_single_markdown_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "messy.md"
            output = root / "clean.md"
            report = root / "postprocess_report.json"
            markdown.write_text("#Title\n\n\nBody", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "postprocess",
                    "--markdown",
                    str(markdown),
                    "--profile",
                    "safe",
                    "--output",
                    str(output),
                    "--report-json",
                    str(report),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            cleaned = output.read_text(encoding="utf-8")
            report_payload = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Title\n\nBody\n", cleaned)
        self.assertEqual(report_payload["schema"], "doc_postprocess_report_v1")
        self.assertTrue(json.loads(result.stdout)["ok"])

    def test_postprocess_doc_manifest_cli_writes_handoff_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff"
            docs = handoff / "documents"
            docs.mkdir(parents=True)
            (docs / "sample.md").write_text("#Title\n\n\nBody", encoding="utf-8")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [{"source_path": "sample.md", "markdown_path": "documents/sample.md"}],
                    }
                ),
                encoding="utf-8",
            )
            output = root / "processed"

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "postprocess",
                    "--doc-manifest",
                    str(manifest),
                    "--profile",
                    "safe",
                    "--output",
                    str(output),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            cleaned = (output / "documents" / "sample.md").read_text(encoding="utf-8")
            report = json.loads((output / "postprocess_report.json").read_text(encoding="utf-8"))

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("# Title\n\nBody\n", cleaned)
            self.assertEqual(report["schema"], "doc_postprocess_report_v1")
            self.assertTrue((output / "doc_manifest.json").is_file())

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

    def test_convert_mineru_backend_from_environment(self) -> None:
        captured: dict[str, object] = {"uploads": 0, "status_calls": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                captured["auth"] = self.headers.get("Authorization")
                captured["create_payload"] = json.loads(self.rfile.read(length).decode("utf-8"))
                body = json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "task_id": "task-1",
                            "file_url": f"http://127.0.0.1:{self.server.server_port}/upload/task-1",
                        },
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_PUT(self) -> None:  # noqa: N802
                captured["uploads"] = int(captured["uploads"]) + 1
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(204)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/parse/task-1":
                    captured["status_calls"] = int(captured["status_calls"]) + 1
                    body = json.dumps(
                        {
                            "code": 0,
                            "data": {
                                "state": "done",
                                "markdown_url": f"http://127.0.0.1:{self.server.server_port}/markdown/task-1.md",
                            },
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/markdown/task-1.md":
                    body = b"# MinerU\n\nConverted by fake MinerU service.\n"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/markdown")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

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
                        "DOC_TO_MD_BACKEND": "mineru",
                        "MINERU_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                        "MINERU_API_KEY": "mineru-secret",
                        "MINERU_TIMEOUT": "5",
                        "MINERU_POLL_INTERVAL": "0.1",
                        "MINERU_LANGUAGE": "en",
                        "MINERU_PAGE_RANGE": "1-2",
                        "MINERU_ENABLE_TABLE": "true",
                        "MINERU_IS_OCR": "false",
                        "MINERU_ENABLE_FORMULA": "true",
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
        self.assertIn("# MinerU", markdown)
        self.assertEqual(captured["auth"], "Bearer mineru-secret")
        self.assertEqual(captured["uploads"], 1)
        self.assertEqual(captured["status_calls"], 1)
        payload = captured["create_payload"]
        self.assertEqual(payload["file_name"], "paper.pdf")
        self.assertEqual(payload["language"], "en")
        self.assertEqual(payload["page_range"], "1-2")
        self.assertTrue(payload["enable_table"])

    def test_convert_mineru_sync_backend_from_environment(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                captured["path"] = self.path
                captured["auth"] = self.headers.get("Authorization")
                captured["content_type"] = self.headers.get("Content-Type")
                captured["body"] = self.rfile.read(length)
                body = json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "markdown": "# MinerU Sync\n\nConverted by a synchronous multipart service.\n"
                        },
                    }
                ).encode("utf-8")
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
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake sync")
                env = _env()
                env.update(
                    {
                        "DOC_TO_MD_BACKEND": "mineru-sync",
                        "MINERU_BASE_URL": f"http://127.0.0.1:{server.server_port}/api/v1",
                        "MINERU_API_KEY": "mineru-secret",
                        "MINERU_TIMEOUT": "5",
                        "MINERU_LANGUAGE": "en",
                        "MINERU_ENABLE_TABLE": "true",
                        "MINERU_IS_OCR": "false",
                        "MINERU_ENABLE_FORMULA": "true",
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
        self.assertIn("# MinerU Sync", markdown)
        self.assertEqual(captured["path"], "/api/v1/parse")
        self.assertEqual(captured["auth"], "Bearer mineru-secret")
        self.assertIn("multipart/form-data", str(captured["content_type"]))
        body = captured["body"]
        self.assertIsInstance(body, bytes)
        self.assertIn(b'name="file"; filename="paper.pdf"', body)
        self.assertIn(b"%PDF fake sync", body)
        self.assertIn(b'name="language"', body)
        self.assertIn(b"en", body)

    def test_convert_mineru_cli_backend_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            fake_cli = _write_fake_mineru_cli(root / "mineru")
            fake_log = root / "mineru-args.log"
            input_dir.mkdir()
            (input_dir / "paper.pdf").write_bytes(b"%PDF fake cli")
            env = _env()
            env.update(
                {
                    "DOC_TO_MD_BACKEND": "mineru-cli",
                    "MINERU_CLI_PATH": str(fake_cli),
                    "MINERU_CLI_BACKEND": "pipeline",
                    "FAKE_MINERU_LOG": str(fake_log),
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
            log_text = fake_log.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# MinerU CLI", markdown)
        self.assertIn("backend=pipeline", markdown)
        self.assertIn("-b\npipeline", log_text)
        self.assertIn("-p", log_text)

    def test_convert_mineru_cli_copies_local_image_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            fake_cli = _write_fake_mineru_cli_with_image(root / "mineru")
            input_dir.mkdir()
            (input_dir / "paper.pdf").write_bytes(b"%PDF fake cli image")
            env = _env()
            env.update(
                {
                    "DOC_TO_MD_BACKEND": "mineru-cli",
                    "MINERU_CLI_PATH": str(fake_cli),
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
            quality_report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_dir / "doc_manifest.json").read_text(encoding="utf-8"))
            image_exists = (output_dir / "documents" / "images" / "chart.jpg").is_file()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("![chart](images/chart.jpg)", markdown)
        self.assertTrue(image_exists)
        self.assertEqual(quality_report["gate"]["status"], "PASS")
        self.assertEqual(manifest["quality_gate"]["status"], "PASS")

    def test_convert_auto_prefers_mineru_cli_for_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            fake_cli = _write_fake_mineru_cli(root / "mineru")
            input_dir.mkdir()
            (input_dir / "paper.pdf").write_bytes(b"%PDF fake auto cli")
            env = _env()
            env.update(
                {
                    "DOC_TO_MD_BACKEND": "auto",
                    "MINERU_CLI_PATH": str(fake_cli),
                    "MINERU_CLI_BACKEND": "pipeline",
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

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# MinerU CLI", markdown)
        self.assertIn("source=paper.pdf", markdown)

    def test_convert_mineru_backend_from_config_file(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "task_id": "task-config",
                            "file_url": f"http://127.0.0.1:{self.server.server_port}/upload/task-config",
                        },
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_PUT(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(204)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/parse/task-config":
                    body = json.dumps(
                        {
                            "code": 0,
                            "data": {
                                "state": "done",
                                "markdown_url": f"http://127.0.0.1:{self.server.server_port}/markdown/task-config.md",
                            },
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/markdown/task-config.md":
                    body = b"# Config MinerU\n\nConverted through config file.\n"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/markdown")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(404)
                self.end_headers()

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
                config_path = root / "ragflow-config.yaml"
                input_dir.mkdir()
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake")
                config_path.write_text(
                    "doc_to_md:\n"
                    "  backend: mineru\n"
                    "mineru:\n"
                    f"  base_url: http://127.0.0.1:{server.server_port}\n"
                    "  timeout: 5\n"
                    "  poll_interval: 0.1\n",
                    encoding="utf-8",
                )

                result = subprocess.run(
                    [
                        sys.executable,
                        str(CONVERT_SCRIPT),
                        "--config",
                        str(config_path),
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

                markdown = (output_dir / "documents" / "paper.md").read_text(encoding="utf-8")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Config MinerU", markdown)

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

    def test_inspect_generates_blocked_quality_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            docs = handoff / "documents"
            docs.mkdir(parents=True)
            (docs / "empty.md").write_text("", encoding="utf-8")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": "empty.md",
                                "markdown_path": "documents/empty.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report_md = handoff / "quality_report.md"

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "inspect",
                    "--doc-manifest",
                    str(manifest),
                    "--report-md",
                    str(report_md),
                    "--fail-on-blocked",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

            report = json.loads((handoff / "quality_report.json").read_text(encoding="utf-8"))
            report_md_text = report_md.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 1, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["quality_gate"]["status"], "BLOCKED")
        self.assertEqual(report["gate"]["status"], "BLOCKED")
        self.assertIn("Document Quality Report", report_md_text)

    def test_segment_plan_and_split_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "long.md"
            plan_output = root / "segmentation_plan.json"
            segments = root / "segments"
            markdown.write_text("# One\n" + ("a" * 70) + "\n# Two\n" + ("b" * 70) + "\n", encoding="utf-8")

            plan_result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "segment-plan",
                    "--markdown",
                    str(markdown),
                    "--output",
                    str(plan_output),
                    "--soft-max-chars",
                    "50",
                    "--hard-max-chars",
                    "90",
                    "--min-segment-chars",
                    "20",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            split_result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "split",
                    "--markdown",
                    str(markdown),
                    "--output",
                    str(segments),
                    "--plan-output",
                    str(root / "split_plan.json"),
                    "--soft-max-chars",
                    "50",
                    "--hard-max-chars",
                    "90",
                    "--min-segment-chars",
                    "20",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

            plan_payload = json.loads(plan_result.stdout)
            split_payload = json.loads(split_result.stdout)
            plan_exists = plan_output.exists()
            first_segment_exists = (segments / "long.part-001.md").exists()

        self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
        self.assertEqual(split_result.returncode, 0, split_result.stderr)
        self.assertTrue(plan_exists)
        self.assertEqual(len(plan_payload["segmentation_plan"]["segments"]), 2)
        self.assertEqual(split_payload["segment_count"], 2)
        self.assertTrue(first_segment_exists)

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
        self.assertIn("--mineru-base-url", result.stdout)
        self.assertIn("--mineru-cli-path", result.stdout)
        self.assertIn("--quality-report-name", result.stdout)
        self.assertIn("segment-plan", result.stdout)
        self.assertIn("--strict", result.stdout)


if __name__ == "__main__":
    unittest.main()
