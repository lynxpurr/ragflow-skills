from __future__ import annotations

import base64
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


def _write_fake_mineru_cli_with_html_table(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "from pathlib import Path\n"
        "import sys\n"
        "args = sys.argv[1:]\n"
        "out_dir = Path(args[args.index('-o') + 1])\n"
        "source = Path(args[args.index('-p') + 1])\n"
        "out_dir.mkdir(parents=True, exist_ok=True)\n"
        "(out_dir / (source.stem + '.md')).write_text(\n"
        "    '# APOLLO 产品目录\\n\\n'\n"
        "    'APOLLO 产品用于高精度选型。\\n\\n'\n"
        "    '## 技术参数\\n\\n'\n"
        "    '<table>\\n'\n"
        "    '<thead><tr><th>型号</th><th>精度</th><th>尺寸</th></tr></thead>\\n'\n"
        "    '<tbody><tr><td>APOLLO-H</td><td>0.01 mm</td><td>250 mm</td></tr></tbody>\\n'\n"
        "    '</table>\\n',\n"
        "    encoding='utf-8',\n"
        ")\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _write_slow_mineru_cli(path: Path) -> Path:
    path.write_text(
        "#!/usr/bin/env python3\n"
        "import time\n"
        "time.sleep(5)\n",
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
        self.assertEqual(payload["handoff_mode"], "thin_preview")
        self.assertEqual(payload["handoff_advisory"][0]["code"], "formal_ingest_pipeline_recommended")
        self.assertEqual(payload["document_count"], 1)
        self.assertEqual(payload["quality_gate"]["status"], "PASS")
        self.assertEqual(quality_report["gate"]["status"], "PASS")
        self.assertEqual(manifest["handoff_mode"], "thin_preview")
        self.assertEqual(manifest["handoff_advisory"][0]["severity"], "info")
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
            images = output_dir / "documents" / "images"
            images.mkdir()
            (images / "chart.png").write_bytes(b"fake chart")
            markdown = output_dir / "documents" / "alpha.md"
            markdown.write_text(
                markdown.read_text(encoding="utf-8") + "\n![Alpha chart](images/chart.png)\n",
                encoding="utf-8",
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
            retrieval_hints = json.loads((output_dir / "retrieval_hints.json").read_text(encoding="utf-8"))
            assistant_profile = json.loads((output_dir / "assistant_profile.json").read_text(encoding="utf-8"))
            assistant_test_plan = json.loads((output_dir / "assistant_test_plan.json").read_text(encoding="utf-8"))
            ingest_readiness = json.loads((output_dir / "ingest_readiness_report.json").read_text(encoding="utf-8"))
            ingest_readiness_md = (output_dir / "ingest_readiness_report.md").read_text(encoding="utf-8")
            readme_exists = (output_dir / "package_readme.md").exists()

        self.assertEqual(convert_result.returncode, 0, convert_result.stderr)
        self.assertEqual(package_result.returncode, 0, package_result.stderr)
        payload = json.loads(package_result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["package"]["schema"], "ragflow_handoff_package_v1")
        self.assertEqual(payload["package"]["asset_semantic_count"], 1)
        self.assertEqual(payload["package"]["ingest_readiness_status"], "ready_with_review")
        self.assertEqual(metadata["schema"], "ragflow_document_metadata_v1")
        self.assertEqual(artifact_index["schema"], "ragflow_artifact_index_v1")
        self.assertEqual(artifact_index["asset_semantics"]["schema"], "ragflow_asset_semantics_v1")
        self.assertEqual(artifact_index["asset_semantics"]["summary"]["image_count"], 1)
        self.assertEqual(artifact_index["asset_semantics"]["images"][0]["semantic_kind"], "chart")
        self.assertEqual(artifact_index["asset_semantics"]["images"][0]["bytes"], len(b"fake chart"))
        self.assertEqual(suggestions["schema"], "ragflow_profile_suggestions_v1")
        self.assertEqual(retrieval_hints["schema"], "ragflow_retrieval_hints_v1")
        self.assertEqual(retrieval_hints["asset_semantics"]["summary"]["image_count"], 1)
        self.assertEqual(retrieval_hints["image_artifacts"][0]["semantic_kind"], "chart")
        self.assertEqual(assistant_profile["schema"], "ragflow_assistant_profile_v1")
        self.assertEqual(assistant_test_plan["schema"], "ragflow_assistant_test_plan_v1")
        self.assertTrue(any(case.get("source_image") == "documents/images/chart.png" for case in assistant_test_plan["cases"]))
        self.assertEqual(ingest_readiness["schema"], "ragflow_doc_ingest_readiness_v1")
        self.assertEqual(ingest_readiness["status"], "ready_with_review")
        self.assertIn("RAGFlow Doc Ingest Readiness", ingest_readiness_md)
        self.assertTrue(readme_exists)

    def test_pipeline_creates_rich_handoff_and_ingest_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            (input_dir / "alpha.md").write_text(
                "# Alpha\n\nIntro\n\n## Specs\n\nBody\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "pipeline",
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--mode",
                    "passthrough",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            markdown = (output_dir / "documents" / "alpha.md").read_text(encoding="utf-8")
            manifest = json.loads((output_dir / "doc_manifest.json").read_text(encoding="utf-8"))
            package_readme_exists = (output_dir / "package_readme.md").is_file()
            package_readme = (output_dir / "package_readme.md").read_text(encoding="utf-8")
            retrieval_hints = json.loads((output_dir / "retrieval_hints.json").read_text(encoding="utf-8"))
            ingest_readiness = json.loads((output_dir / "ingest_readiness_report.json").read_text(encoding="utf-8"))
            ingest_readiness_md = (output_dir / "ingest_readiness_report.md").read_text(encoding="utf-8")
            postprocess_report = json.loads((output_dir / "postprocess_report.json").read_text(encoding="utf-8"))
            chunk_profile_report = json.loads((output_dir / "chunk_profile_report.json").read_text(encoding="utf-8"))
            ingest_plan = (output_dir / "ragflow_ingest_plan.yaml").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["handoff_mode"], "formal_ingest")
        self.assertEqual(payload["pipeline"]["handoff_mode"], "formal_ingest")
        self.assertTrue(payload["formal_ingest"]["chunk_markers"]["enabled"])
        self.assertGreaterEqual(payload["formal_ingest"]["chunk_markers"]["marker_count"], 1)
        self.assertEqual(payload["formal_ingest"]["chunk_markers"]["chunk_profile_report"], "chunk_profile_report.json")
        self.assertTrue(payload["formal_ingest"]["rich_sidecars"]["complete"])
        self.assertTrue(payload["formal_ingest"]["ragflow_ingest_plan"]["generated"])
        self.assertEqual(payload["formal_ingest"]["ingest_readiness"]["status"], "ready")
        self.assertTrue(payload["formal_ingest"]["ingest_readiness"]["generated"])
        self.assertEqual(payload["quality_gate"]["status"], "PASS")
        self.assertEqual(payload["pipeline"]["stages"]["postprocess"]["profile"], "chunk-markers")
        self.assertTrue(payload["pipeline"]["stages"]["postprocess"]["chunk_profile_report"].endswith("chunk_profile_report.json"))
        self.assertTrue(payload["chunk_profile_report"].endswith("chunk_profile_report.json"))
        self.assertIn("<!-- chunk -->", markdown)
        self.assertEqual(manifest["handoff_mode"], "formal_ingest")
        self.assertTrue(manifest["formal_ingest"]["rich_sidecars"]["complete"])
        self.assertEqual(manifest["postprocess_report"], "postprocess_report.json")
        self.assertEqual(manifest["chunk_profile_report"], "chunk_profile_report.json")
        self.assertTrue(package_readme_exists)
        self.assertIn("Handoff mode: `formal_ingest`", package_readme)
        self.assertIn("ragflow-kb-build inspect-handoff", package_readme)
        self.assertIn("--dry-run", package_readme)
        self.assertEqual(retrieval_hints["schema"], "ragflow_retrieval_hints_v1")
        self.assertEqual(ingest_readiness["schema"], "ragflow_doc_ingest_readiness_v1")
        self.assertEqual(ingest_readiness["status"], "ready")
        self.assertIn("status: `ready`", ingest_readiness_md)
        self.assertEqual(postprocess_report["chunk_profile_report"]["schema"], "ragflow_chunk_profile_report_v1")
        self.assertEqual(chunk_profile_report["schema"], "ragflow_chunk_profile_report_v1")
        self.assertGreaterEqual(chunk_profile_report["summary"]["marker_count"], 1)
        self.assertIn('schema: "ragflow_ingest_plan_v1"', ingest_plan)
        self.assertIn('handoff_mode: "formal_ingest"', ingest_plan)
        self.assertIn('chunk_profile_report: "chunk_profile_report.json"', ingest_plan)
        self.assertIn('ingest_readiness: "ingest_readiness_report.json"', ingest_plan)
        self.assertIn('inspect_command:', ingest_plan)
        self.assertIn('command: "ragflow-kb-build"', ingest_plan)
        self.assertNotIn("api_key", ingest_plan)
        self.assertNotIn("base_url", ingest_plan)

    def test_pipeline_dense_profile_writes_chunk_profile_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            (input_dir / "catalog.md").write_text(
                "# APOLLO Catalog\n\n"
                "Overview.\n\n"
                "<!-- page: 1 -->\n\n"
                "## Specs\n\n"
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| Accuracy | 4.0 um |\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "pipeline",
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--mode",
                    "passthrough",
                    "--postprocess-profile",
                    "chunk-markers-dense",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            chunk_profile_report = json.loads((output_dir / "chunk_profile_report.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_dir / "doc_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["pipeline"]["stages"]["postprocess"]["profile"], "chunk-markers-dense")
        self.assertEqual(payload["formal_ingest"]["chunk_markers"]["profile"], "chunk-markers-dense")
        self.assertEqual(chunk_profile_report["schema"], "ragflow_chunk_profile_report_v1")
        self.assertEqual(chunk_profile_report["profile"], "chunk-markers-dense")
        self.assertGreater(chunk_profile_report["summary"]["marker_type_counts"]["page"], 0)
        self.assertGreater(chunk_profile_report["summary"]["marker_type_counts"]["table"], 0)
        self.assertEqual(manifest["chunk_profile_report"], "chunk_profile_report.json")

    def test_pipeline_can_write_non_secret_ragflow_config_alias(self) -> None:
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
                    "pipeline",
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--mode",
                    "passthrough",
                    "--ragflow-config-alias",
                    "ragflow_config.yaml",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            alias_text = (output_dir / "ragflow_config.yaml").read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('schema: "ragflow_ingest_plan_v1"', alias_text)
        self.assertNotIn("api_key", alias_text)
        self.assertNotIn("base_url", alias_text)

    def test_pipeline_updates_runtime_report_to_formal_ingest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            fake_cli = _write_fake_mineru_cli(root / "mineru")
            input_dir.mkdir()
            (input_dir / "paper.pdf").write_bytes(b"%PDF fake cli")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "pipeline",
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--backend",
                    "mineru-cli",
                    "--mineru-cli-path",
                    str(fake_cli),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            manifest = json.loads((output_dir / "doc_manifest.json").read_text(encoding="utf-8"))
            runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["handoff_mode"], "formal_ingest")
        self.assertEqual(manifest["handoff_mode"], "formal_ingest")
        self.assertEqual(runtime_report["handoff_mode"], "formal_ingest")
        self.assertEqual(runtime_report["summary"]["handoff_mode"], "formal_ingest")
        self.assertEqual(runtime_report["handoff_advisory"][0]["code"], "inspect_and_dry_run_before_live_build")
        self.assertTrue(runtime_report["formal_ingest"]["rich_sidecars"]["complete"])

    def test_pipeline_runtime_and_hints_count_html_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            fake_cli = _write_fake_mineru_cli_with_html_table(root / "mineru")
            input_dir.mkdir()
            (input_dir / "apollo.pdf").write_bytes(b"%PDF fake cli")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "pipeline",
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--backend",
                    "mineru-cli",
                    "--mineru-cli-path",
                    str(fake_cli),
                    "--runtime-report-md",
                    "runtime_report.md",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            quality_report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
            runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
            runtime_markdown = (output_dir / "runtime_report.md").read_text(encoding="utf-8")
            retrieval_hints = json.loads((output_dir / "retrieval_hints.json").read_text(encoding="utf-8"))

        signals = quality_report["documents"][0]["quality_signals"]
        html_table = next(item for item in retrieval_hints["table_artifacts"] if item["source"] == "html_table")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["handoff_mode"], "formal_ingest")
        self.assertEqual(signals["table_count"], 1)
        self.assertEqual(signals["html_table_count"], 1)
        self.assertEqual(runtime_report["document_quality_summary"]["html_table_count"], 1)
        self.assertEqual(runtime_report["summary"]["quality_html_table_count"], 1)
        self.assertIn("quality HTML table count: `1`", runtime_markdown)
        self.assertEqual(html_table["header_preview"], ["型号", "精度", "尺寸"])
        self.assertEqual(html_table["row_count"], 2)
        self.assertEqual(html_table["column_count"], 3)

    def test_pipeline_rejects_unsafe_sidecar_name(self) -> None:
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
                    "pipeline",
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--mode",
                    "passthrough",
                    "--ingest-plan-name",
                    "../ragflow_ingest_plan.yaml",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn("relative handoff path", payload["error"])

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

    def test_postprocess_cli_writes_ragflux_like_chunk_profile_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "catalog.md"
            output = root / "catalog.clean.md"
            report = root / "postprocess_report.json"
            chunk_report = root / "chunk_profile_report.json"
            markdown.write_text(
                "# Catalog\n\n"
                "Intro.\n\n"
                "<!-- page: 1 -->\n"
                "## Specs\n\n"
                "- Install base\n"
                "- Calibrate sensor\n\n"
                "![diagram](images/apollo.png)\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "postprocess",
                    "--markdown",
                    str(markdown),
                    "--profile",
                    "chunk-markers-ragflux-like",
                    "--output",
                    str(output),
                    "--report-json",
                    str(report),
                    "--chunk-profile-report-json",
                    str(chunk_report),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            report_payload = json.loads(report.read_text(encoding="utf-8"))
            chunk_payload = json.loads(chunk_report.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report_payload["chunk_profile_report"]["schema"], "ragflow_chunk_profile_report_v1")
        self.assertEqual(chunk_payload["schema"], "ragflow_chunk_profile_report_v1")
        self.assertEqual(chunk_payload["profile"], "chunk-markers-ragflux-like")
        self.assertGreater(chunk_payload["summary"]["marker_type_counts"]["page"], 0)
        self.assertGreater(chunk_payload["summary"]["marker_type_counts"]["list"], 0)
        self.assertGreater(chunk_payload["summary"]["marker_type_counts"]["image"], 0)

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

    def test_convert_mineru_fastapi_backend_from_environment(self) -> None:
        captured: dict[str, object] = {"status_calls": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                captured["path"] = self.path
                captured["auth"] = self.headers.get("Authorization")
                captured["content_type"] = self.headers.get("Content-Type")
                captured["body"] = self.rfile.read(length)
                body = json.dumps(
                    {
                        "task_id": "task-fastapi-cli",
                        "status": "pending",
                        "status_url": f"http://127.0.0.1:{self.server.server_port}/tasks/task-fastapi-cli",
                        "result_url": f"http://127.0.0.1:{self.server.server_port}/tasks/task-fastapi-cli/result",
                    }
                ).encode("utf-8")
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/tasks/task-fastapi-cli":
                    captured["status_calls"] = int(captured["status_calls"]) + 1
                    body = json.dumps({"task_id": "task-fastapi-cli", "status": "completed"}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/tasks/task-fastapi-cli/result":
                    body = json.dumps(
                        {
                            "backend": "pipeline",
                            "version": "3.2.1",
                            "results": {
                                "paper": {
                                    "md_content": "# MinerU FastAPI\n\nConverted by fake async service.\n"
                                }
                            },
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
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
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake fastapi")
                env = _env()
                env.update(
                    {
                        "DOC_TO_MD_BACKEND": "mineru-fastapi",
                        "MINERU_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                        "MINERU_API_KEY": "fastapi-secret",
                        "MINERU_TIMEOUT": "5",
                        "MINERU_POLL_INTERVAL": "0.01",
                        "MINERU_LANGUAGE": "ch,en",
                        "MINERU_PAGE_RANGE": "2-4",
                        "MINERU_ENABLE_TABLE": "false",
                        "MINERU_IS_OCR": "true",
                        "MINERU_ENABLE_FORMULA": "false",
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

                payload = json.loads(result.stdout)
                markdown = (output_dir / "documents" / "paper.md").read_text(encoding="utf-8")
                manifest = json.loads((output_dir / "doc_manifest.json").read_text(encoding="utf-8"))
                runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertIn("# MinerU FastAPI", markdown)
        self.assertEqual(payload["handoff_mode"], "thin_preview")
        self.assertEqual(payload["handoff_advisory"][0]["severity"], "review")
        self.assertEqual(manifest["documents"][0]["markdown_path"], "documents/paper.md")
        self.assertEqual(manifest["handoff_mode"], "thin_preview")
        self.assertEqual(manifest["runtime_report"], "runtime_report.json")
        self.assertEqual(runtime_report["handoff_mode"], "thin_preview")
        self.assertEqual(runtime_report["summary"]["handoff_mode"], "thin_preview")
        self.assertEqual(runtime_report["handoff_advisory"][0]["code"], "formal_ingest_pipeline_recommended")
        self.assertEqual(runtime_report["handoff_advisory"][0]["severity"], "review")
        self.assertEqual(payload["runtime_summary"]["remote_attempts"], 1)
        self.assertEqual(runtime_report["summary"]["remote_success"], 1)
        self.assertEqual(runtime_report["remote_attempts"][0]["task_id"], "task-fastapi-cli")
        self.assertEqual(runtime_report["remote_attempts"][0]["endpoint"], "http://<redacted-host>")
        self.assertEqual(runtime_report["remote_attempts"][0]["asset_policy"]["mode"], "markdown_only")
        self.assertFalse(runtime_report["remote_attempts"][0]["asset_policy"]["requested"]["return_images"])
        self.assertEqual(captured["path"], "/tasks")
        self.assertEqual(captured["auth"], "Bearer fastapi-secret")
        self.assertIn("multipart/form-data", str(captured["content_type"]))
        body = captured["body"]
        self.assertIsInstance(body, bytes)
        self.assertIn(b'name="files"; filename="paper.pdf"', body)
        self.assertIn(b'name="lang_list"', body)
        self.assertIn(b"ch", body)
        self.assertIn(b"en", body)
        self.assertIn(b'name="parse_method"', body)
        self.assertIn(b"ocr", body)
        self.assertIn(b'name="table_enable"', body)
        self.assertIn(b"false", body)
        self.assertIn(b'name="start_page_id"', body)
        self.assertIn(b"2", body)
        self.assertIn(b'name="end_page_id"', body)
        self.assertIn(b"4", body)
        self.assertEqual(captured["status_calls"], 1)

    def test_convert_mineru_fastapi_markdown_assets_passes_quality_gate(self) -> None:
        captured: dict[str, object] = {}
        image_payload = "data:image/png;base64," + base64.b64encode(b"fake png bytes").decode("ascii")

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                captured["body"] = self.rfile.read(length)
                body = json.dumps({"task_id": "task-fastapi-assets", "status": "pending"}).encode("utf-8")
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/tasks/task-fastapi-assets":
                    body = json.dumps({"task_id": "task-fastapi-assets", "status": "completed"}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/tasks/task-fastapi-assets/result":
                    body = json.dumps(
                        {
                            "backend": "pipeline",
                            "version": "3.2.1",
                            "results": {
                                "paper": {
                                    "md_content": "# MinerU FastAPI Assets\n\n![chart](images/chart.png)\n",
                                    "images": {"images/chart.png": image_payload},
                                }
                            },
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
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
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake fastapi assets")
                env = _env()
                env.update(
                    {
                        "DOC_TO_MD_BACKEND": "mineru-fastapi",
                        "MINERU_BASE_URL": f"http://127.0.0.1:{server.server_port}",
                        "MINERU_TIMEOUT": "5",
                        "MINERU_POLL_INTERVAL": "0.01",
                        "MINERU_ASSET_MODE": "markdown_assets",
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
                runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
                image_exists = (output_dir / "documents" / "images" / "paper" / "chart.png").is_file()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(image_exists)
        self.assertIn("![chart](images/paper/chart.png)", markdown)
        self.assertEqual(quality_report["gate"]["status"], "PASS")
        self.assertEqual(manifest["quality_gate"]["status"], "PASS")
        self.assertEqual(manifest["documents"][0]["assets"]["images"][0]["path"], "documents/images/paper/chart.png")
        asset_policy = runtime_report["remote_attempts"][0]["asset_policy"]
        self.assertEqual(asset_policy["mode"], "markdown_assets")
        self.assertTrue(asset_policy["requested"]["return_images"])
        self.assertTrue(asset_policy["saved"]["images"])
        self.assertEqual(asset_policy["saved"]["image_count"], 1)
        body = captured["body"]
        self.assertIsInstance(body, bytes)
        self.assertIn(b'name="return_images"', body)
        self.assertIn(b"true", body)

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

    def test_convert_mineru_cli_timeout_writes_runtime_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            (input_dir / "ok.md").write_text("# OK\n", encoding="utf-8")
            (input_dir / "slow.pdf").write_bytes(b"%PDF slow")
            fake_cli = _write_slow_mineru_cli(root / "mineru")
            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--backend",
                    "mineru-cli",
                    "--mineru-cli-path",
                    str(fake_cli),
                    "--mineru-timeout",
                    "0.1",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_dir / "doc_manifest.json").read_text(encoding="utf-8"))
            attempt = report["process_attempts"][0]

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(payload["document_count"], 1)
        self.assertEqual(payload["runtime_summary"]["timeout"], 1)
        self.assertEqual(payload["skipped"][0]["source_path"], "slow.pdf")
        self.assertEqual(report["schema"], "ragflow_doc_runtime_report_v1")
        self.assertEqual(report["summary"]["cleanup_attempts"], 1)
        self.assertEqual(report["summary"]["leftover_processes"], 0)
        self.assertEqual(attempt["status"], "timeout")
        self.assertTrue(attempt["cleanup"]["attempted"])
        self.assertTrue(attempt["cleanup"]["process_exited"])
        self.assertEqual(attempt["cleanup"]["leftover_process_count"], 0)
        self.assertEqual(manifest["runtime_report"], "runtime_report.json")

    def test_convert_image_fallback_preserves_source_image_for_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            source_bytes = b"fake image bytes"
            (input_dir / "diagram.png").write_bytes(source_bytes)
            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--backend",
                    "remote",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            markdown = (output_dir / "documents" / "diagram.md").read_text(encoding="utf-8")
            quality_report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
            manifest = json.loads((output_dir / "doc_manifest.json").read_text(encoding="utf-8"))
            copied_images = list((output_dir / "documents" / "images").glob("diagram-*.png"))
            copied_image_bytes = copied_images[0].read_bytes() if copied_images else None

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["quality_gate"]["status"], "PASS_WITH_REVIEW")
        self.assertEqual(quality_report["gate"]["status"], "PASS_WITH_REVIEW")
        self.assertEqual(manifest["quality_gate"]["status"], "PASS_WITH_REVIEW")
        self.assertIn("Source image preserved for manual review", markdown)
        self.assertIn("![diagram](images/diagram-", markdown)
        self.assertEqual(len(copied_images), 1)
        self.assertEqual(copied_image_bytes, source_bytes)
        self.assertEqual(quality_report["documents"][0]["image_count"], 1)
        self.assertEqual(quality_report["documents"][0]["issues"][0]["issue_type"], "conversion_warning")

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

    def test_inspect_writes_redaction_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            handoff = Path(tmp) / "handoff"
            docs = handoff / "documents"
            docs.mkdir(parents=True)
            (docs / "sample.md").write_text("# Sample\n\nready\n", encoding="utf-8")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": "http://100.64.10.20/source.md?token=inspect-secret",
                                "markdown_path": "documents/sample.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            report_json = handoff / "quality_report.inspect.json"
            report_md = handoff / "quality_report.inspect.md"
            redaction_json = handoff / "quality_report.inspect.redaction.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "inspect",
                    "--doc-manifest",
                    str(manifest),
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(redaction_json),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            report_text = report_json.read_text(encoding="utf-8")
            markdown = report_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([result.stdout, report_text, markdown, redaction_text])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertNotIn("100.64.10.20", combined)
        self.assertNotIn("inspect-secret", combined)

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

    def test_split_checkpoint_resume_via_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "long.md"
            segments = root / "segments"
            checkpoint = root / "split.checkpoint.json"
            split_plan = root / "split_plan.json"
            markdown.write_text("# One\n" + ("a" * 70) + "\n# Two\n" + ("b" * 70) + "\n", encoding="utf-8")

            base_args = [
                sys.executable,
                str(CONVERT_SCRIPT),
                "split",
                "--markdown",
                str(markdown),
                "--output",
                str(segments),
                "--plan-output",
                str(split_plan),
                "--checkpoint",
                str(checkpoint),
                "--soft-max-chars",
                "50",
                "--hard-max-chars",
                "90",
                "--min-segment-chars",
                "20",
            ]
            first_result = subprocess.run(
                [*base_args, "--batch-size", "1"],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            second_result = subprocess.run(
                [*base_args, "--resume"],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )

            first_payload = json.loads(first_result.stdout)
            second_payload = json.loads(second_result.stdout)
            checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
            first_segment_exists = (segments / "long.part-001.md").exists()
            second_segment_exists = (segments / "long.part-002.md").exists()

        self.assertEqual(first_result.returncode, 0, first_result.stderr)
        self.assertEqual(second_result.returncode, 0, second_result.stderr)
        self.assertEqual(first_payload["segment_count"], 1)
        self.assertFalse(first_payload["checkpoint"]["completed"])
        self.assertEqual(first_payload["checkpoint"]["new_segment_count"], 1)
        self.assertEqual(second_payload["segment_count"], 2)
        self.assertTrue(second_payload["checkpoint"]["resume"])
        self.assertTrue(second_payload["checkpoint"]["completed"])
        self.assertEqual(second_payload["checkpoint"]["new_segment_count"], 1)
        self.assertEqual(checkpoint_payload["schema"], "ragflow_doc_split_checkpoint_v1")
        self.assertEqual(checkpoint_payload["processed_segment_ids"], ["segment-001", "segment-002"])
        self.assertTrue(checkpoint_payload["summary"]["completed"])
        self.assertTrue(first_segment_exists)
        self.assertTrue(second_segment_exists)

    def test_split_manifest_output_can_feed_kb_build_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff"
            markdown = root / "long.md"
            segments = handoff / "documents" / "segments"
            manifest_output = handoff / "doc_manifest.json"
            markdown.write_text("# One\n" + ("a" * 70) + "\n# Two\n" + ("b" * 70) + "\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "split",
                    "--markdown",
                    str(markdown),
                    "--output",
                    str(segments),
                    "--plan-output",
                    str(handoff / "segmentation_plan.json"),
                    "--manifest-output",
                    str(manifest_output),
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
            payload = json.loads(result.stdout)
            manifest_payload = json.loads(manifest_output.read_text(encoding="utf-8"))
            manifest = load_doc_manifest(manifest_output)
            docs = discover_markdown_documents(doc_manifest=manifest, manifest_base_path=manifest_output)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["split_manifest"]["document_count"], 2)
        self.assertTrue(payload["split_manifest"]["completed"])
        self.assertEqual(manifest_payload["version"], "0.1")
        self.assertEqual(manifest_payload["split"]["segment_count"], 2)
        self.assertEqual(
            [doc.path.name for doc in docs],
            ["long.part-001.md", "long.part-002.md"],
        )

    def test_postprocess_writes_redaction_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            handoff = root / "handoff"
            docs = handoff / "documents"
            docs.mkdir(parents=True)
            markdown_name = "postprocess.local-token=postprocess-secret.md"
            (docs / markdown_name).write_text("#Title\n\nline with trailing spaces  \n", encoding="utf-8")
            manifest = handoff / "doc_manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "documents": [
                            {
                                "source_path": markdown_name,
                                "markdown_path": f"documents/{markdown_name}",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            output_dir = root / "postprocessed"
            report_json = root / "postprocess_report.json"
            redaction_json = root / "postprocess_redaction.json"

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
                    str(output_dir),
                    "--report-json",
                    str(report_json),
                    "--redaction-report",
                    str(redaction_json),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            report_text = report_json.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([result.stdout, report_text, redaction_text])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertNotIn("postprocess-secret", combined)

    def test_segment_plan_and_split_write_redaction_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "long.md"
            markdown.write_text(
                "# http://segment.local/doc?token=segment-secret\n"
                + ("a" * 70)
                + "\n# Two\n"
                + ("b" * 70)
                + "\n",
                encoding="utf-8",
            )
            plan_output = root / "segmentation_plan.json"
            plan_redaction = root / "segmentation_plan_redaction.json"
            split_output = root / "segments"
            split_plan = root / "split_plan.json"
            split_redaction = root / "split_plan_redaction.json"

            plan_result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "segment-plan",
                    "--markdown",
                    str(markdown),
                    "--output",
                    str(plan_output),
                    "--redaction-report",
                    str(plan_redaction),
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
                    str(split_output),
                    "--plan-output",
                    str(split_plan),
                    "--redaction-report",
                    str(split_redaction),
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
            plan_text = plan_output.read_text(encoding="utf-8")
            plan_redaction_text = plan_redaction.read_text(encoding="utf-8")
            split_plan_text = split_plan.read_text(encoding="utf-8")
            split_redaction_text = split_redaction.read_text(encoding="utf-8")
            plan_redaction_payload = json.loads(plan_redaction_text)
            split_redaction_payload = json.loads(split_redaction_text)

        combined = "\n".join(
            [
                plan_result.stdout,
                split_result.stdout,
                plan_text,
                plan_redaction_text,
                split_plan_text,
                split_redaction_text,
            ]
        )
        self.assertEqual(plan_result.returncode, 0, plan_result.stderr)
        self.assertEqual(split_result.returncode, 0, split_result.stderr)
        self.assertEqual(plan_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertEqual(split_redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(plan_redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(plan_redaction_payload["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(split_redaction_payload["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(split_redaction_payload["rule_counts"]["private_host"], 1)
        self.assertNotIn("segment.local", combined)
        self.assertNotIn("segment-secret", combined)

    def test_convert_writes_redaction_report_for_quality_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            (input_dir / "convert.local-token=convert-secret.md").write_text("# Convert\n\nBody\n", encoding="utf-8")
            quality_md = output_dir / "quality_report.md"
            redaction_json = root / "convert_redaction.json"

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
                    "--quality-report-md",
                    str(quality_md),
                    "--redaction-report",
                    str(redaction_json),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            quality_report_text = (output_dir / "quality_report.json").read_text(encoding="utf-8")
            quality_markdown = quality_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([result.stdout, quality_report_text, quality_markdown, redaction_text])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertNotIn("convert-secret", combined)

    def test_convert_writes_redaction_report_for_runtime_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            input_dir.mkdir()
            (input_dir / "paper.pdf").write_bytes(b"%PDF fake cli redaction")
            fake_cli = _write_fake_mineru_cli(root / "mineru-token=runtime-secret")
            runtime_md = output_dir / "runtime_report.md"
            redaction_json = root / "convert_runtime_redaction.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "--input",
                    str(input_dir),
                    "--output",
                    str(output_dir),
                    "--backend",
                    "mineru-cli",
                    "--mineru-cli-path",
                    str(fake_cli),
                    "--runtime-report-md",
                    str(runtime_md),
                    "--redaction-report",
                    str(redaction_json),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            runtime_report_text = (output_dir / "runtime_report.json").read_text(encoding="utf-8")
            runtime_markdown = runtime_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([result.stdout, runtime_report_text, runtime_markdown, redaction_text])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertNotIn("runtime-secret", combined)

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
        self.assertIn("--runtime-report-name", result.stdout)
        self.assertIn("--redaction-report", result.stdout)
        self.assertIn("--no-image-fallback", result.stdout)
        self.assertIn("backend probe", result.stdout)
        self.assertIn("backend warmup", result.stdout)
        self.assertIn("segment-plan", result.stdout)
        self.assertIn("--strict", result.stdout)

    def test_backend_probe_builtin_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "backend_probe.json"
            report_md = root / "backend_probe.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "backend",
                    "probe",
                    "--backend",
                    "builtin",
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            report_payload = json.loads(report_json.read_text(encoding="utf-8"))
            markdown = report_md.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["schema"], "ragflow_doc_backend_probe_report_v1")
        self.assertEqual(payload["backends"][0]["backend"], "builtin")
        self.assertEqual(payload["backends"][0]["status"], "available")
        self.assertEqual(payload["runtime_partial_failure"]["schema"], "ragflow_runtime_partial_failure_report_v1")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["status"], "completed")
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertEqual(report_payload["summary"]["available"], 1)
        self.assertEqual(report_payload["summary"]["runtime_partial_failure_status"], "completed")
        self.assertIn("RAGFlow Doc Backend Probe", markdown)
        self.assertIn("runtime_partial_failure_status: `completed`", markdown)
        self.assertIn("runtime_failures: `0`", markdown)

    def test_backend_probe_classifies_remote_config_gaps(self) -> None:
        missing = subprocess.run(
            [sys.executable, str(CONVERT_SCRIPT), "backend", "probe", "--backend", "remote", "--json"],
            text=True,
            capture_output=True,
            check=False,
            env=_env(),
        )
        wrong_protocol = subprocess.run(
            [
                sys.executable,
                str(CONVERT_SCRIPT),
                "backend",
                "probe",
                "--backend",
                "remote",
                "--remote-url",
                "ftp://converter.example.test/convert",
                "--json",
            ],
            text=True,
            capture_output=True,
            check=False,
            env=_env(),
        )

        self.assertEqual(missing.returncode, 0, missing.stderr)
        self.assertEqual(wrong_protocol.returncode, 0, wrong_protocol.stderr)
        missing_payload = json.loads(missing.stdout)
        wrong_protocol_payload = json.loads(wrong_protocol.stdout)
        self.assertEqual(missing_payload["backends"][0]["status"], "not_configured")
        self.assertEqual(missing_payload["runtime_partial_failure"]["summary"]["status"], "skipped")
        self.assertEqual(wrong_protocol_payload["backends"][0]["status"], "wrong_protocol")
        self.assertEqual(wrong_protocol_payload["runtime_partial_failure"]["summary"]["status"], "failed")

    def test_backend_probe_writes_redaction_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report_json = root / "backend_probe.json"
            redaction_json = root / "backend_probe_redaction.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "backend",
                    "probe",
                    "--backend",
                    "mineru",
                    "--mineru-base-url",
                    "http://" + ".".join(("100", "64", "10", "20")) + ":8080/api/v1?token=fake-secret",
                    "--mineru-api-key",
                    "mineru-secret",
                    "--report-json",
                    str(report_json),
                    "--redaction-report",
                    str(redaction_json),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            report_text = report_json.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            report_payload = json.loads(report_text)
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([result.stdout, report_text, redaction_text])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(report_payload["schema"], "ragflow_doc_backend_probe_report_v1")
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["target_counts"]["explicit_secrets"], 1)
        self.assertGreaterEqual(redaction_payload["target_counts"]["private_hosts"], 1)
        self.assertNotIn("fake-secret", combined)
        self.assertNotIn("mineru-secret", combined)

    def test_backend_probe_mineru_cli_uses_configured_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake_cli = _write_fake_mineru_cli(root / "mineru")
            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "backend",
                    "probe",
                    "--backend",
                    "mineru-cli",
                    "--mineru-cli-path",
                    str(fake_cli),
                    "--json",
                    "--fail-on-unavailable",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["backends"][0]["status"], "available")

    def test_backend_probe_mineru_fastapi_available_via_cli(self) -> None:
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                captured["path"] = self.path
                captured["auth"] = self.headers.get("Authorization")
                body = json.dumps(
                    {
                        "status": "healthy",
                        "version": "3.2.1",
                        "protocol_version": 2,
                        "queued_tasks": 0,
                        "processing_tasks": 0,
                        "completed_tasks": 0,
                        "failed_tasks": 0,
                        "max_concurrent_requests": 3,
                        "processing_window_size": 64,
                        "task_retention_seconds": 86400,
                        "task_cleanup_interval_seconds": 300,
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
            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "backend",
                    "probe",
                    "--backend",
                    "mineru-fastapi",
                    "--mineru-base-url",
                    f"http://127.0.0.1:{server.server_port}",
                    "--mineru-api-key",
                    "probe-secret",
                    "--network-check",
                    "--json",
                    "--fail-on-unavailable",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["selected_backend"], "mineru-fastapi")
        self.assertEqual(payload["backends"][0]["status"], "available")
        self.assertEqual(payload["summary"]["available"], 1)
        self.assertEqual(payload["runtime_partial_failure"]["summary"]["status"], "completed")
        self.assertEqual(captured["path"], "/health")
        self.assertEqual(captured["auth"], "Bearer probe-secret")

    def test_backend_warmup_mineru_cli_writes_reports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "fixture.pdf"
            fixture.write_bytes(b"%PDF warmup")
            fake_cli = _write_fake_mineru_cli(root / "mineru")
            report_json = root / "backend_warmup.json"
            report_md = root / "backend_warmup.md"
            output_markdown = root / "warmup.md"
            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "backend",
                    "warmup",
                    "--backend",
                    "mineru-cli",
                    "--fixture",
                    str(fixture),
                    "--mineru-cli-path",
                    str(fake_cli),
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--output-markdown",
                    str(output_markdown),
                    "--json",
                    "--fail-on-failed",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            report_payload = json.loads(report_json.read_text(encoding="utf-8"))
            markdown_report = report_md.read_text(encoding="utf-8")
            converted_markdown = output_markdown.read_text(encoding="utf-8")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["schema"], "ragflow_doc_backend_warmup_report_v1")
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["fixture"]["name"], "fixture.pdf")
        self.assertEqual(payload["summary"]["process_attempts"], 1)
        self.assertEqual(payload["runtime_report"]["summary"]["success"], 1)
        self.assertEqual(report_payload["output"]["markdown_name"], "warmup.md")
        self.assertIn("RAGFlow Doc Backend Warmup", markdown_report)
        self.assertIn("# MinerU CLI", converted_markdown)

    def test_backend_warmup_writes_redaction_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "warmup.local-token=warmup-secret.pdf"
            fixture.write_bytes(b"%PDF warmup")
            fake_cli = _write_fake_mineru_cli(root / "mineru")
            report_json = root / "backend_warmup.json"
            report_md = root / "backend_warmup.md"
            redaction_json = root / "backend_warmup_redaction.json"
            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "backend",
                    "warmup",
                    "--backend",
                    "mineru-cli",
                    "--fixture",
                    str(fixture),
                    "--mineru-cli-path",
                    str(fake_cli),
                    "--mineru-base-url",
                    "http://warmup.local:8080/api/v1?token=warmup-secret",
                    "--remote-api-key",
                    "warmup-secret",
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(redaction_json),
                    "--json",
                    "--fail-on-failed",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            report_text = report_json.read_text(encoding="utf-8")
            markdown = report_md.read_text(encoding="utf-8")
            redaction_text = redaction_json.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction_text)

        combined = "\n".join([result.stdout, report_text, markdown, redaction_text])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["summary"]["redaction_count"], 2)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["assignment_secret"], 1)
        self.assertGreaterEqual(redaction_payload["rule_counts"]["private_host"], 1)
        self.assertNotIn("warmup.local", combined)
        self.assertNotIn("warmup-secret", combined)

    def test_backend_warmup_fail_on_failed_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = root / "fixture.pdf"
            fixture.write_bytes(b"%PDF warmup missing backend")
            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "backend",
                    "warmup",
                    "--backend",
                    "remote",
                    "--fixture",
                    str(fixture),
                    "--json",
                    "--fail-on-failed",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(payload["status"], "failed")
        self.assertIn("remote backend requires --remote-url", payload["error"])


if __name__ == "__main__":
    unittest.main()
