from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ragflow_skill_runtime.doc_convert import (
    ConvertedDocument,
    DEFAULT_MINERU_BASE_URL,
    DocConvertError,
    SourceDocument,
    convert_source_to_markdown,
    copy_local_markdown_assets,
    discover_source_documents,
    extract_markdown_title,
    html_to_markdown,
    make_doc_manifest_payload,
    mineru_fastapi_convert,
    probe_conversion_backends,
    render_backend_probe_markdown,
    safe_markdown_name,
    sha256_file,
    text_to_markdown,
)
from ragflow_skill_runtime.doc_quality import (
    BLOCKED,
    PASS,
    PASS_WITH_REVIEW,
    QualityDocument,
    make_quality_report_payload,
)
from ragflow_skill_runtime.doc_segment import materialize_segments, plan_markdown_segmentation


class DocConvertTests(unittest.TestCase):
    def test_discover_source_documents_skips_hidden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "visible.md").write_text("# Visible\n", encoding="utf-8")
            (root / ".hidden.md").write_text("# Hidden\n", encoding="utf-8")
            docs = discover_source_documents(root)

        self.assertEqual([doc.source_path for doc in docs], ["visible.md"])

    def test_text_to_markdown_adds_title(self) -> None:
        markdown = text_to_markdown("Hello\nWorld", title="sample")
        self.assertTrue(markdown.startswith("# sample"))

    def test_html_to_markdown_handles_heading_and_link(self) -> None:
        markdown = html_to_markdown("<h1>Title</h1><p>Hello <a href='https://e.test'>link</a></p>")
        self.assertIn("# Title", markdown)
        self.assertIn("[link](https://e.test)", markdown)

    def test_convert_source_to_markdown_builtin_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"
            path.write_text("Plain body", encoding="utf-8")
            markdown, warnings = convert_source_to_markdown(
                SourceDocument(path=path, source_path="note.txt"),
                backend="builtin",
            )

        self.assertIn("Plain body", markdown)
        self.assertEqual(warnings, [])

    def test_convert_source_to_markdown_passthrough_rejects_non_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "note.txt"
            path.write_text("Plain body", encoding="utf-8")
            with self.assertRaises(DocConvertError):
                convert_source_to_markdown(
                    SourceDocument(path=path, source_path="note.txt"),
                    mode="passthrough",
                )

    def test_auto_does_not_call_default_mineru_service_without_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "paper.pdf"
            path.write_bytes(b"%PDF fake")
            with self.assertRaisesRegex(DocConvertError, "no converter available"):
                convert_source_to_markdown(
                    SourceDocument(path=path, source_path="paper.pdf"),
                    backend="auto",
                    mineru_base_url=DEFAULT_MINERU_BASE_URL,
                    mineru_api_key=None,
                )

    def test_safe_markdown_name_deduplicates(self) -> None:
        used: set[str] = set()
        first = safe_markdown_name(
            SourceDocument(path=Path("/tmp/a.md"), source_path="dir/a.md"),
            used=used,
        )
        second = safe_markdown_name(
            SourceDocument(path=Path("/tmp/a.txt"), source_path="other/a.txt"),
            used=used,
        )
        self.assertEqual(first, "a.md")
        self.assertEqual(second, "a-2.md")

    def test_make_doc_manifest_payload_uses_relative_markdown_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docs_dir = root / "documents"
            docs_dir.mkdir()
            source_path = root / "input.md"
            source_path.write_text("# Title\n", encoding="utf-8")
            markdown_path = docs_dir / "input.md"
            markdown_path.write_text("# Title\n", encoding="utf-8")

            payload = make_doc_manifest_payload(
                output_root=root,
                documents=[
                    ConvertedDocument(
                        source=SourceDocument(path=source_path, source_path="input.md"),
                        markdown_path=markdown_path,
                        sha256=sha256_file(source_path),
                        title=extract_markdown_title("# Title\n"),
                        warnings=[],
                    )
                ],
            )

        self.assertEqual(payload["documents"][0]["markdown_path"], "documents/input.md")

    def test_backend_probe_emits_runtime_partial_failure_summary(self) -> None:
        report = probe_conversion_backends(
            backend="auto",
            remote_url="ftp://converter.example.test/convert",
            mineru_base_url=None,
            mineru_api_key=None,
            mineru_cli_path="/definitely/missing/mineru",
            network_check=False,
        )
        markdown = render_backend_probe_markdown(report)

        self.assertEqual(report["schema"], "ragflow_doc_backend_probe_report_v1")
        self.assertEqual(report["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "partial")
        self.assertTrue(report["runtime_partial_failure"]["summary"]["partial"])
        self.assertEqual(report["summary"]["runtime_partial_failure_status"], "partial")
        self.assertGreaterEqual(report["summary"]["runtime_failure_count"], 1)
        self.assertGreaterEqual(report["summary"]["runtime_skipped_count"], 1)
        self.assertIn("runtime_partial_failure_status: `partial`", markdown)
        self.assertIn("runtime_skipped:", markdown)

    def test_mineru_fastapi_convert_success(self) -> None:
        captured: dict[str, object] = {"status_calls": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                captured["path"] = self.path
                captured["auth"] = self.headers.get("Authorization")
                captured["body"] = body.decode("utf-8", errors="replace")
                payload = {
                    "task_id": "task-fastapi",
                    "status": "pending",
                    "status_url": f"http://127.0.0.1:{self.server.server_port}/tasks/task-fastapi",
                    "result_url": f"http://127.0.0.1:{self.server.server_port}/tasks/task-fastapi/result",
                }
                raw = json.dumps(payload).encode("utf-8")
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/tasks/task-fastapi":
                    captured["status_calls"] = int(captured["status_calls"]) + 1
                    raw = json.dumps({"task_id": "task-fastapi", "status": "completed"}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if self.path == "/tasks/task-fastapi/result":
                    raw = json.dumps(
                        {
                            "backend": "pipeline",
                            "version": "3.2.1",
                            "results": {"paper": {"md_content": "# FastAPI\n\nConverted.\n"}},
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
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
                source_path = Path(tmp) / "paper.pdf"
                source_path.write_bytes(b"%PDF fake")
                markdown = mineru_fastapi_convert(
                    SourceDocument(path=source_path, source_path="paper.pdf"),
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    api_key="fastapi-secret",
                    timeout=5,
                    poll_interval=0.01,
                    language="ch,en",
                    page_range="1-3",
                    enable_table=False,
                    is_ocr=True,
                    enable_formula=False,
                )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(markdown, "# FastAPI\n\nConverted.\n")
        self.assertEqual(captured["path"], "/tasks")
        self.assertEqual(captured["auth"], "Bearer fastapi-secret")
        body = str(captured["body"])
        self.assertIn('name="files"; filename="paper.pdf"', body)
        self.assertIn('name="lang_list"', body)
        self.assertIn("ch", body)
        self.assertIn("en", body)
        self.assertIn('name="parse_method"', body)
        self.assertIn("ocr", body)
        self.assertIn('name="table_enable"', body)
        self.assertIn("false", body)
        self.assertIn('name="start_page_id"', body)
        self.assertIn("1", body)
        self.assertIn('name="end_page_id"', body)
        self.assertIn("3", body)
        self.assertEqual(captured["status_calls"], 1)

    def test_mineru_fastapi_convert_task_failed(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                raw = json.dumps({"task_id": "task-failed"}).encode("utf-8")
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                raw = json.dumps({"task_id": "task-failed", "status": "failed", "error": "boom"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, _format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                source_path = Path(tmp) / "paper.pdf"
                source_path.write_bytes(b"%PDF fake")
                with self.assertRaisesRegex(DocConvertError, "boom"):
                    mineru_fastapi_convert(
                        SourceDocument(path=source_path, source_path="paper.pdf"),
                        base_url=f"http://127.0.0.1:{server.server_port}",
                        timeout=5,
                        poll_interval=0.01,
                    )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_mineru_fastapi_convert_timeout(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                raw = json.dumps({"task_id": "task-timeout"}).encode("utf-8")
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                raw = json.dumps({"task_id": "task-timeout", "status": "processing"}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, _format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                source_path = Path(tmp) / "paper.pdf"
                source_path.write_bytes(b"%PDF fake")
                with self.assertRaisesRegex(DocConvertError, "timed out"):
                    mineru_fastapi_convert(
                        SourceDocument(path=source_path, source_path="paper.pdf"),
                        base_url=f"http://127.0.0.1:{server.server_port}",
                        timeout=0.05,
                        poll_interval=0.01,
                    )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_probe_mineru_fastapi_available(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["auth"] = self.headers.get("Authorization")
                raw = json.dumps(
                    {
                        "status": "healthy",
                        "version": "3.2.1",
                        "protocol_version": 2,
                        "queued_tasks": 0,
                        "processing_tasks": 0,
                        "completed_tasks": 0,
                        "failed_tasks": 0,
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, _format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            report = probe_conversion_backends(
                backend="mineru-fastapi",
                mineru_base_url=f"http://127.0.0.1:{server.server_port}",
                mineru_api_key="probe-secret",
                network_check=True,
                timeout=2,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(report["backends"][0]["status"], "available")
        self.assertEqual(report["summary"]["available"], 1)
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "completed")
        self.assertEqual(captured["path"], "/health")
        self.assertEqual(captured["auth"], "Bearer probe-secret")

    def test_probe_mineru_fastapi_skips_network_without_network_check(self) -> None:
        report = probe_conversion_backends(
            backend="mineru-fastapi",
            mineru_base_url="http://127.0.0.1:9",
            network_check=False,
            timeout=0.01,
        )

        entry = report["backends"][0]
        self.assertEqual(entry["status"], "available")
        self.assertIn("network check disabled", entry["reasons"])
        self.assertEqual(report["summary"]["available"], 1)
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "completed")
        network_check = [item for item in entry["checks"] if item["name"] == "network_check"][0]
        self.assertTrue(network_check["skipped"])

    def test_quality_report_passes_clean_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "documents" / "clean.md"
            markdown.parent.mkdir()
            markdown.write_text("# Clean\n\nBody\n", encoding="utf-8")

            report = make_quality_report_payload(
                output_root=root,
                documents=[QualityDocument(source_path="clean.md", markdown_path=markdown)],
            )

        self.assertEqual(report["gate"]["status"], PASS)
        self.assertEqual(report["gate"]["summary"]["errors"], 0)

    def test_quality_report_blocks_empty_and_missing_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "documents" / "broken.md"
            empty = root / "documents" / "empty.md"
            markdown.parent.mkdir()
            markdown.write_text("# Broken\n\n![missing](images/nope.png)\n", encoding="utf-8")
            empty.write_text("", encoding="utf-8")

            report = make_quality_report_payload(
                output_root=root,
                documents=[
                    QualityDocument(source_path="broken.md", markdown_path=markdown),
                    QualityDocument(source_path="empty.md", markdown_path=empty),
                ],
            )

        issue_types = {
            issue["issue_type"]
            for document in report["documents"]
            for issue in document["issues"]
        }
        self.assertEqual(report["gate"]["status"], BLOCKED)
        self.assertIn("image_missing", issue_types)
        self.assertIn("markdown_empty", issue_types)

    def test_copy_local_markdown_assets_rewrites_absolute_temp_image(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mineru_root = root / "mineru-output"
            mineru_images = mineru_root / "images"
            mineru_images.mkdir(parents=True)
            markdown_path = mineru_root / "paper.md"
            image_path = mineru_images / "chart.jpg"
            image_path.write_bytes(b"fake image bytes")
            markdown_path.write_text(f"# Paper\n\n![chart]({image_path})\n", encoding="utf-8")
            handoff_documents = root / "handoff" / "documents"

            rewritten = copy_local_markdown_assets(
                markdown_path.read_text(encoding="utf-8"),
                markdown_path=markdown_path,
                source_root=mineru_root,
                asset_output_dir=handoff_documents,
            )
            copied = handoff_documents / "images" / "chart.jpg"
            copied_exists = copied.is_file()

        self.assertIn("![chart](images/chart.jpg)", rewritten)
        self.assertTrue(copied_exists)

    def test_quality_report_marks_conversion_warning_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "documents" / "review.md"
            markdown.parent.mkdir()
            markdown.write_text("# Review\n\nBody\n", encoding="utf-8")

            report = make_quality_report_payload(
                output_root=root,
                documents=[
                    QualityDocument(
                        source_path="review.docx",
                        markdown_path=markdown,
                        warnings=["pandoc was unavailable; used fallback"],
                    )
                ],
            )

        self.assertEqual(report["gate"]["status"], PASS_WITH_REVIEW)
        self.assertEqual(report["gate"]["summary"]["warnings"], 1)

    def test_plan_markdown_segmentation_uses_heading_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            markdown = Path(tmp) / "long.md"
            markdown.write_text("# One\n" + ("a" * 70) + "\n# Two\n" + ("b" * 70) + "\n", encoding="utf-8")

            plan = plan_markdown_segmentation(
                markdown,
                soft_max_chars=50,
                hard_max_chars=90,
                min_segment_chars=20,
            )

        self.assertTrue(plan.recommended)
        self.assertEqual(len(plan.segments), 2)
        self.assertEqual(plan.segments[0].title, "One")
        self.assertEqual(plan.segments[1].title, "Two")

    def test_materialize_segments_writes_segment_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "long.md"
            output = root / "segments"
            plan_output = root / "segmentation_plan.json"
            markdown.write_text("# One\n" + ("a" * 70) + "\n# Two\n" + ("b" * 70) + "\n", encoding="utf-8")

            result = materialize_segments(
                markdown,
                output_dir=output,
                plan_output=plan_output,
                soft_max_chars=50,
                hard_max_chars=90,
                min_segment_chars=20,
            )
            plan_exists = plan_output.exists()
            first_segment_exists = (output / "long.part-001.md").exists()

        self.assertEqual(len(result.segment_paths), 2)
        self.assertTrue(plan_exists)
        self.assertTrue(first_segment_exists)


if __name__ == "__main__":
    unittest.main()
