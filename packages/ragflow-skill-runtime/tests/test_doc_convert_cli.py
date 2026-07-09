from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ragflow_skill_runtime.kb_build import discover_markdown_documents
from ragflow_skill_runtime.manifests import load_doc_manifest


ROOT = Path(__file__).resolve().parents[3]
RUNTIME_SRC = ROOT / "packages" / "ragflow-skill-runtime" / "src"
CONVERT_SCRIPT = ROOT / "skills" / "ragflow-doc-to-md" / "scripts" / "convert.py"
DOC_TO_MD_ENV_VARS = {
    "RAGFLOW_CONFIG",
    "DOC_TO_MD_BACKEND",
    "DOC_TO_MD_TABLE_QUALITY",
    "DOC_TO_MD_ALLOW_TABLE_QUALITY_FALLBACK",
    "MINERU_API_KEY",
    "MINERU_BASE_URL",
    "MINERU_CLI_PATH",
    "MINERU_CLI_BACKEND",
    "MINERU_FASTAPI_BACKEND",
    "MINERU_FASTAPI_SERVER_URL",
    "MINERU_TIMEOUT",
    "MINERU_POLL_INTERVAL",
    "MINERU_VERIFY_SSL",
    "MINERU_LANGUAGE",
    "MINERU_PAGE_RANGE",
    "MINERU_ENABLE_TABLE",
    "MINERU_IS_OCR",
    "MINERU_ENABLE_FORMULA",
    "MINERU_ASSET_MODE",
    "MINERU_V4_MODEL_VERSION",
    "MINERU_V4_RESULT_MODE",
    "MINERU_V4_DATA_ID_PREFIX",
}


def _env() -> dict[str, str]:
    env = os.environ.copy()
    for name in DOC_TO_MD_ENV_VARS:
        env.pop(name, None)
    env["RAGFLOW_SKILL_RUNTIME_PATH"] = str(RUNTIME_SRC)
    return env


def _write_adaptive_compare_run(
    root: Path,
    *,
    primary_language: str,
    language_source: str,
    fastapi_backend: str,
    profile_id: str,
    quality_status: str,
    marker_count: int,
    image_count: int,
    renamed_count: int,
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "document_features.json").write_text(
        json.dumps(
            {
                "schema": "ragflow_document_features_v1",
                "summary": {
                    "document_count": 1,
                    "primary_language": primary_language,
                    "language_source_counts": {language_source: 1},
                    "scanned_or_low_text_pdf_count": 1,
                    "sample_table_count": 1,
                    "sample_html_table_count": 1,
                    "sample_image_ref_count": image_count,
                },
                "documents": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "pipeline_decision.json").write_text(
        json.dumps(
            {
                "schema": "ragflow_pipeline_decision_v1",
                "confidence": "review",
                "signals": {
                    "primary_language": primary_language,
                    "inspected_primary_language": primary_language,
                    "language_source": language_source,
                },
                "recommendation": {
                    "backend": "mineru-fastapi",
                    "table_quality": "standard",
                    "postprocess_profile": "chunk-markers-dense",
                    "mineru_fastapi_backend": fastapi_backend,
                    "mineru_asset_mode": "markdown_assets",
                    "kb_profile": {"id": profile_id},
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "adaptive_summary.json").write_text(
        json.dumps(
            {
                "schema": "ragflow_adaptive_pipeline_summary_v1",
                "ok": True,
                "pipeline_exit_code": 0,
                "decision_confidence": "review",
                "recommended_profile_id": profile_id,
                "quality_gate_status": quality_status,
                "ingest_readiness_status": "ready_with_review",
                "post_conversion_profile_id": profile_id,
                "warnings": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "quality_report.json").write_text(
        json.dumps(
            {
                "schema": "doc_quality_report_v1",
                "gate": {"status": quality_status},
                "documents": [
                    {
                        "quality_signals": {
                            "chunk_marker_table_atomicity": {
                                "chunk_marker_count": marker_count,
                                "marker_inside_table_count": 0,
                                "unbalanced_fragment_count": 0,
                            }
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "chunk_profile_report.json").write_text(
        json.dumps(
            {
                "schema": "ragflow_chunk_profile_report_v1",
                "summary": {
                    "marker_count": marker_count,
                    "preferred_boundary_alignment_ratio": 1.0,
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "runtime_report.json").write_text(
        json.dumps(
            {
                "schema": "ragflow_doc_runtime_report_v1",
                "remote_attempts": [
                    {
                        "asset_policy": {
                            "saved": {
                                "image_count": image_count,
                                "image_naming": {"renamed_count": renamed_count},
                            }
                        }
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


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


def _write_retained_package_fixture(root: Path) -> Path:
    retained_parent = root / "ragflux-retained"
    retained = retained_parent / "ragflow_input"
    images = retained / "images"
    raw = retained / "raw" / "layout"
    images.mkdir(parents=True)
    raw.mkdir(parents=True)
    (images / "chart.png").write_bytes(b"retained chart")
    (retained / "apollo.md").write_text(
        "# APOLLO Catalog\n\n"
        "<!-- chunk -->\n\n"
        "APOLLO accuracy is 4.0 um.\n\n"
        "![Chart](images/chart.png)\n\n"
        "| Field | Value |\n"
        "| --- | --- |\n"
        "| Accuracy | 4.0 um |\n",
        encoding="utf-8",
    )
    (retained / "quality_report.json").write_text(
        json.dumps({"schema": "doc_quality_report_v1", "gate": {"status": "PASS"}}),
        encoding="utf-8",
    )
    (retained / "retrieval_hints.json").write_text(
        json.dumps(
            {
                "schema": "ragflow_retrieval_hints_v1",
                "section_boundaries": [{"title": "APOLLO Catalog"}],
                "preferred_boundaries": [{"reason": "chunk_marker_boundary"}],
                "keyword_candidates": [{"term": "APOLLO"}],
                "question_candidates": [{"question": "What is the accuracy?"}],
                "table_artifacts": [{"source": "markdown_table"}],
                "image_artifacts": [{"path": "images/chart.png"}],
            }
        ),
        encoding="utf-8",
    )
    (retained / "ragflow_config.yaml").write_text("chunk_size: 512\n", encoding="utf-8")
    (raw / "ignored-private-source.md").write_text("# Ignored\n\nDo not count this.\n", encoding="utf-8")
    (raw / "ignored-cache.png").write_bytes(b"ignored image cache")
    return retained_parent


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
            formal_manifest = json.loads((output_dir / "formal_handoff_manifest.json").read_text(encoding="utf-8"))
            readme_exists = (output_dir / "package_readme.md").exists()

        self.assertEqual(convert_result.returncode, 0, convert_result.stderr)
        self.assertEqual(package_result.returncode, 0, package_result.stderr)
        payload = json.loads(package_result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["package"]["schema"], "ragflow_handoff_package_v1")
        self.assertEqual(payload["package"]["asset_semantic_count"], 1)
        self.assertEqual(payload["package"]["ingest_readiness_status"], "ready_with_review")
        self.assertEqual(payload["package"]["formal_handoff_manifest_schema"], "ragflow_formal_handoff_manifest_v1")
        self.assertEqual(payload["package"]["formal_handoff_package_hash"], formal_manifest["package_hash"])
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
        self.assertEqual(formal_manifest["schema"], "ragflow_formal_handoff_manifest_v1")
        self.assertEqual(formal_manifest["source_document_count"], 1)
        self.assertIn("retrieval_hints", formal_manifest["schema_versions"])
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
            formal_manifest = json.loads((output_dir / "formal_handoff_manifest.json").read_text(encoding="utf-8"))
            postprocess_report = json.loads((output_dir / "postprocess_report.json").read_text(encoding="utf-8"))
            chunk_profile_report = json.loads((output_dir / "chunk_profile_report.json").read_text(encoding="utf-8"))
            quality_report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
            runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
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
        self.assertTrue(payload["formal_ingest"]["formal_handoff_manifest"]["generated"])
        self.assertEqual(
            payload["formal_ingest"]["formal_handoff_manifest"]["schema"],
            "ragflow_formal_handoff_manifest_v1",
        )
        self.assertEqual(payload["quality_gate"]["status"], "PASS")
        self.assertEqual(payload["pipeline"]["stages"]["postprocess"]["profile"], "chunk-markers-dense")
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
        self.assertEqual(formal_manifest["schema"], "ragflow_formal_handoff_manifest_v1")
        self.assertEqual(formal_manifest["schema_versions"]["ragflow_ingest_plan"], "ragflow_ingest_plan_v1")
        self.assertEqual(payload["handoff_package"]["formal_handoff_package_hash"], formal_manifest["package_hash"])
        self.assertIn("status: `ready`", ingest_readiness_md)
        self.assertEqual(postprocess_report["chunk_profile_report"]["schema"], "ragflow_chunk_profile_report_v1")
        self.assertEqual(chunk_profile_report["schema"], "ragflow_chunk_profile_report_v1")
        self.assertGreaterEqual(chunk_profile_report["summary"]["marker_count"], 1)
        quality_atomicity = quality_report["documents"][0]["quality_signals"]["chunk_marker_table_atomicity"]
        self.assertEqual(quality_atomicity["chunk_marker_count"], chunk_profile_report["summary"]["marker_count"])
        self.assertEqual(runtime_report["document_quality_summary"]["table_count"], 0)
        self.assertIn('schema: "ragflow_ingest_plan_v1"', ingest_plan)
        self.assertIn('handoff_mode: "formal_ingest"', ingest_plan)
        self.assertIn('chunk_profile_report: "chunk_profile_report.json"', ingest_plan)
        self.assertIn('ingest_readiness: "ingest_readiness_report.json"', ingest_plan)
        self.assertIn('formal_handoff_manifest: "formal_handoff_manifest.json"', ingest_plan)
        self.assertIn('inspect_command:', ingest_plan)
        self.assertIn('command: "ragflow-kb-build"', ingest_plan)
        self.assertNotIn("api_key", ingest_plan)
        self.assertNotIn("base_url", ingest_plan)

    def test_pipeline_passthrough_materializes_relative_markdown_images(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            input_dir = root / "input"
            output_dir = root / "handoff"
            image_dir = input_dir / "images"
            image_dir.mkdir(parents=True)
            (image_dir / "chart.png").write_bytes(b"fake chart")
            input_dir.mkdir(exist_ok=True)
            (input_dir / "alpha.md").write_text(
                "# Alpha\n\nDedao-style chart.\n\n![Chart](images/chart.png)\n",
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
                    "--no-recursive",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            materialized_image = output_dir / "documents" / "images" / "chart.png"
            materialized_image_exists = materialized_image.is_file()
            materialized_image_bytes = materialized_image.read_bytes() if materialized_image_exists else b""
            markdown = (output_dir / "documents" / "alpha.md").read_text(encoding="utf-8")
            quality_report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
            retrieval_hints = json.loads((output_dir / "retrieval_hints.json").read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertTrue(materialized_image_exists)
        self.assertEqual(materialized_image_bytes, b"fake chart")
        self.assertIn("![Chart](images/chart.png)", markdown)
        self.assertEqual(payload["quality_gate"]["status"], "PASS")
        self.assertEqual(quality_report["gate"]["status"], "PASS")
        self.assertEqual(retrieval_hints["asset_semantics"]["summary"]["image_count"], 1)
        self.assertTrue(any(item.get("path") == "documents/images/chart.png" for item in retrieval_hints["image_artifacts"]))

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

    def test_compare_retained_package_cli_writes_static_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            retained = _write_retained_package_fixture(root)
            input_dir = root / "input"
            output_dir = root / "replacement-handoff"
            input_dir.mkdir()
            (input_dir / "apollo.md").write_text(
                "# APOLLO Catalog\n\n"
                "APOLLO accuracy is 4.0 um.\n\n"
                "| Field | Value |\n"
                "| --- | --- |\n"
                "| Accuracy | 4.0 um |\n",
                encoding="utf-8",
            )
            pipeline_result = subprocess.run(
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
            report_json = root / "handoff_comparison.json"
            report_md = root / "handoff_comparison.md"
            compare_result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "compare-retained-package",
                    "--retained-package",
                    str(retained),
                    "--replacement-handoff",
                    str(output_dir),
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
            payload = json.loads(compare_result.stdout)
            report = json.loads(report_json.read_text(encoding="utf-8"))
            markdown = report_md.read_text(encoding="utf-8")

        self.assertEqual(pipeline_result.returncode, 0, pipeline_result.stderr)
        self.assertEqual(compare_result.returncode, 0, compare_result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["schema"], "ragflow_handoff_comparison_v1")
        self.assertEqual(report["schema"], "ragflow_handoff_comparison_v1")
        self.assertEqual(report["static_comparison"]["retained_package"]["effective_root"], "ragflow_input")
        self.assertEqual(report["static_comparison"]["retained_package"]["markdown"]["markdown_file_count"], 1)
        self.assertEqual(report["static_comparison"]["retained_package"]["images"]["local_image_file_count"], 1)
        self.assertIn("quality_metrics", report["static_comparison"])
        self.assertIn("cleaned_handoff", report["static_comparison"]["quality_metrics"])
        self.assertEqual(report["live_evidence"]["paired_live_ab"]["status"], "not_run")
        self.assertFalse(report["live_evidence"]["paired_live_ab"]["executed"])
        self.assertEqual(report["safety"]["live_ragflow_mutation"], "not_performed")
        self.assertIn("RAGFlow Handoff Comparison", markdown)
        self.assertIn("Cleanup Quality Metrics", markdown)
        self.assertIn("strict_paired_live_ab_not_run", markdown)

    def test_compare_adaptive_summaries_cli_writes_sanitized_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            baseline = root / "private-home" / "baseline-run"
            candidate = root / "private-home" / "candidate-run"
            _write_adaptive_compare_run(
                baseline,
                primary_language="zh",
                language_source="filename_hint",
                fastapi_backend="pipeline",
                profile_id="table-atomic-zh-4096",
                quality_status="PASS_WITH_REVIEW",
                marker_count=32,
                image_count=21,
                renamed_count=12,
            )
            _write_adaptive_compare_run(
                candidate,
                primary_language="en",
                language_source="inspect_source",
                fastapi_backend="hybrid-auto-engine",
                profile_id="table-atomic-en-4096",
                quality_status="BLOCKED",
                marker_count=12,
                image_count=21,
                renamed_count=4,
            )
            report_json = root / "private-home" / "adaptive_compare.json"
            report_md = root / "private-home" / "adaptive_compare.md"
            redaction = root / "private-home" / "adaptive_compare.redaction.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "compare-adaptive-summaries",
                    "--baseline",
                    str(baseline),
                    "--candidate",
                    str(candidate),
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            payload = json.loads(result.stdout)
            report = json.loads(report_json.read_text(encoding="utf-8"))
            markdown = report_md.read_text(encoding="utf-8")
            redaction_payload = json.loads(redaction.read_text(encoding="utf-8"))
            combined = "\n".join([result.stdout, report_json.read_text(encoding="utf-8"), markdown])

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["schema"], "ragflow_adaptive_summary_comparison_v1")
        self.assertEqual(report["schema"], "ragflow_adaptive_summary_comparison_v1")
        self.assertEqual(report["summary"]["status"], "review")
        self.assertTrue(report["summary"]["language_source_changed"])
        self.assertTrue(report["summary"]["backend_changed"])
        self.assertTrue(report["summary"]["quality_gate_changed"])
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(redaction_payload["summary"]["redaction_count"], 1)
        self.assertIn("RAGFlow Adaptive Summary Comparison", markdown)
        self.assertIn("Build And Query Outcomes", markdown)
        self.assertNotIn(str(root), combined)
        self.assertIn("<redacted:config-path>", combined)

    def test_compare_retained_package_redaction_omits_private_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            retained = _write_retained_package_fixture(root)
            replacement = root / "replacement-handoff"
            docs = replacement / "documents"
            docs.mkdir(parents=True)
            (docs / "apollo.md").write_text("# APOLLO Catalog\n\nAPOLLO accuracy is 4.0 um.\n", encoding="utf-8")
            (replacement / "doc_manifest.json").write_text(
                json.dumps(
                    {
                        "version": "0.1",
                        "source_root": ".",
                        "handoff_mode": "formal_ingest",
                        "quality_report": "quality_report.json",
                        "quality_gate": {"status": "PASS"},
                        "documents": [{"source_path": "private-source.pdf", "markdown_path": "documents/apollo.md"}],
                    }
                ),
                encoding="utf-8",
            )
            (replacement / "quality_report.json").write_text(
                json.dumps({"schema": "doc_quality_report_v1", "gate": {"status": "PASS"}}),
                encoding="utf-8",
            )
            report_json = root / "private-home" / "handoff_comparison.json"
            report_md = root / "private-home" / "handoff_comparison.md"
            redaction = root / "private-home" / "handoff_comparison.redaction.json"
            compare_result = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_SCRIPT),
                    "compare-retained-package",
                    "--retained-package",
                    str(retained),
                    "--replacement-handoff",
                    str(replacement),
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(redaction),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=_env(),
            )
            combined = "\n".join(
                [
                    compare_result.stdout,
                    report_json.read_text(encoding="utf-8"),
                    report_md.read_text(encoding="utf-8"),
                    redaction.read_text(encoding="utf-8"),
                ]
            )

        self.assertEqual(compare_result.returncode, 0, compare_result.stderr)
        self.assertNotIn(str(root), combined)
        self.assertNotIn("ignored-private-source", combined)
        self.assertNotIn("private-source.pdf", combined)

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
        performance = runtime_report["performance"]
        stage_names = {item["stage"] for item in performance["stage_timings"]}
        self.assertTrue({"conversion", "postprocess", "package", "hints", "ingest_plan"}.issubset(stage_names))
        standard_stages = {item["standard_stage"] for item in performance["stage_timings"]}
        self.assertTrue({"conversion", "postprocess", "packaging"}.issubset(standard_stages))
        self.assertTrue(all("category" in item for item in performance["stage_timings"]))
        self.assertEqual(performance["runtime_context"]["configured_backend"], "mineru-cli")
        self.assertEqual(performance["runtime_context"]["pipeline_mode"], "formal_ingest")
        self.assertFalse(performance["runtime_context"]["persistent_mineru_reused"])
        self.assertTrue(performance["runtime_context"]["local_process_startup_included"])
        self.assertEqual(performance["runtime_context"]["model_initialization_included"], "not_reported_by_backend")
        self.assertGreater(runtime_report["summary"]["stage_timing_count"], 0)

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
        self.assertIn("## Performance Telemetry", runtime_markdown)
        self.assertIn("| postprocess | chunk-markers-dense | success |", runtime_markdown)
        self.assertIn("cold_warm: `cold_local_process`", runtime_markdown)
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

    def test_postprocess_cli_accepts_pandoc_epub_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "pandoc.md"
            output = root / "clean.md"
            report = root / "postprocess_report.json"
            markdown.write_text(
                "# Title {#title}\n\n"
                "::: {.section}\n"
                "[Noisy]{style=\"color: red\"} []{#anchor}\n"
                ":::\n",
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
                    "pandoc-epub",
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
            cleaned = output.read_text(encoding="utf-8") if output.exists() else ""
            report_payload = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        self.assertIn("# Title", cleaned)
        self.assertNotIn("style=", cleaned)
        self.assertGreater(report_payload["summary"]["rule_counts"]["pandoc_epub.fenced_div_markers"], 0)

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
                        "MINERU_FASTAPI_BACKEND": "hybrid-auto-engine",
                        "MINERU_FASTAPI_SERVER_URL": "https://vlm.example.internal/v1",
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
        self.assertEqual(runtime_report["remote_attempts"][0]["mineru_fastapi_backend"], "hybrid-auto-engine")
        self.assertEqual(runtime_report["remote_attempts"][0]["requested_mineru_fastapi_backend"], "hybrid-auto-engine")
        self.assertEqual(runtime_report["remote_attempts"][0]["mineru_fastapi_server_url"], "https://<redacted-host>/v1")
        runtime_context = runtime_report["performance"]["runtime_context"]
        self.assertEqual(runtime_context["mineru_fastapi_backend"], "hybrid-auto-engine")
        self.assertTrue(runtime_context["mineru_fastapi_server_url_configured"])
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
        self.assertIn(b'name="backend"', body)
        self.assertIn(b"hybrid-auto-engine", body)
        self.assertIn(b'name="server_url"', body)
        self.assertIn(b"https://vlm.example.internal/v1", body)
        self.assertIn(b'name="table_enable"', body)
        self.assertIn(b"false", body)
        self.assertIn(b'name="start_page_id"', body)
        self.assertIn(b"2", body)
        self.assertIn(b'name="end_page_id"', body)
        self.assertIn(b"4", body)
        self.assertEqual(captured["status_calls"], 1)

    def test_convert_mineru_v4_backend_from_environment(self) -> None:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr("full.md", "# MinerU v4 CLI\n\nConverted by fake platform API.\n")
        zip_payload = zip_buffer.getvalue()
        captured: dict[str, object] = {"poll_calls": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                captured["path"] = self.path
                captured["auth"] = self.headers.get("Authorization")
                captured["body"] = json.loads(self.rfile.read(length).decode("utf-8"))
                raw = json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "batch_id": "batch-v4-cli",
                            "file_urls": [
                                f"http://127.0.0.1:{self.server.server_port}/upload/paper.pdf?token=object-secret"
                            ],
                        },
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_PUT(self) -> None:  # noqa: N802
                captured["upload_auth"] = self.headers.get("Authorization")
                captured["upload_body"] = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(200)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/api/v4/extract-results/batch/batch-v4-cli":
                    captured["poll_calls"] = int(captured["poll_calls"]) + 1
                    raw = json.dumps(
                        {
                            "code": 0,
                            "data": {
                                "extract_result": [
                                    {
                                        "file_name": "paper.pdf",
                                        "state": "completed",
                                        "full_zip_url": f"http://127.0.0.1:{self.server.server_port}/result.zip?download=secret",
                                    }
                                ]
                            },
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if self.path == "/result.zip?download=secret":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(len(zip_payload)))
                    self.end_headers()
                    self.wfile.write(zip_payload)
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
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake v4 cli")
                env = _env()
                env.update(
                    {
                        "DOC_TO_MD_BACKEND": "mineru-v4",
                        "MINERU_BASE_URL": f"http://127.0.0.1:{server.server_port}/api/v4",
                        "MINERU_API_KEY": "v4-secret",
                        "MINERU_TIMEOUT": "5",
                        "MINERU_POLL_INTERVAL": "0.01",
                        "MINERU_LANGUAGE": "en",
                        "MINERU_PAGE_RANGE": "1-2",
                        "MINERU_ENABLE_TABLE": "false",
                        "MINERU_IS_OCR": "true",
                        "MINERU_ENABLE_FORMULA": "false",
                        "MINERU_V4_MODEL_VERSION": "MinerU-HTML",
                        "MINERU_V4_RESULT_MODE": "full_zip",
                        "MINERU_V4_DATA_ID_PREFIX": "case",
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
                        "--json",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=env,
                )

                payload = json.loads(result.stdout)
                markdown = (output_dir / "documents" / "paper.md").read_text(encoding="utf-8")
                runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertIn("# MinerU v4 CLI", markdown)
        self.assertEqual(captured["path"], "/api/v4/file-urls/batch")
        self.assertEqual(captured["auth"], "Bearer v4-secret")
        self.assertIsNone(captured["upload_auth"])
        self.assertEqual(captured["upload_body"], b"%PDF fake v4 cli")
        request_body = captured["body"]
        self.assertIsInstance(request_body, dict)
        self.assertEqual(request_body["model_version"], "MinerU-HTML")
        self.assertEqual(request_body["language"], "en")
        self.assertEqual(request_body["enable_table"], False)
        self.assertNotIn("is_ocr", request_body)
        self.assertEqual(request_body["enable_formula"], False)
        self.assertEqual(request_body["files"][0]["data_id"], "case-paper")
        self.assertEqual(request_body["files"][0]["is_ocr"], True)
        self.assertEqual(request_body["files"][0]["page_ranges"], "1-2")
        attempt = runtime_report["remote_attempts"][0]
        self.assertEqual(attempt["backend"], "mineru-v4")
        self.assertEqual(attempt["batch_id"], "batch-v4-cli")
        self.assertEqual(attempt["effective_mineru_v4_model_version"], "MinerU-HTML")
        self.assertEqual(attempt["artifact_summary"]["markdown_entry"], "full.md")
        context = runtime_report["performance"]["runtime_context"]
        self.assertEqual(context["mineru_v4_model_version"], "MinerU-HTML")
        self.assertEqual(context["mineru_v4_result_mode"], "full_zip")
        self.assertEqual(captured["poll_calls"], 1)

    def test_table_quality_high_maps_v4_to_vlm_model(self) -> None:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as archive:
            archive.writestr("full.md", "# V4 Table\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n")
        zip_payload = zip_buffer.getvalue()
        captured: dict[str, object] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                captured["body"] = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))).decode("utf-8"))
                raw = json.dumps(
                    {
                        "code": 0,
                        "data": {
                            "batch_id": "batch-v4-table",
                            "file_urls": [f"http://127.0.0.1:{self.server.server_port}/upload"],
                        },
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_PUT(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                self.send_response(200)
                self.end_headers()

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/api/v4/extract-results/batch/batch-v4-table":
                    raw = json.dumps(
                        {
                            "code": 0,
                            "data": {
                                "extract_result": [
                                    {
                                        "file_name": "paper.pdf",
                                        "state": "success",
                                        "full_zip_url": f"http://127.0.0.1:{self.server.server_port}/result.zip",
                                    }
                                ]
                            },
                        }
                    ).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if self.path == "/result.zip":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(len(zip_payload)))
                    self.end_headers()
                    self.wfile.write(zip_payload)
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
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake v4 table")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(CONVERT_SCRIPT),
                        "--input",
                        str(input_dir),
                        "--output",
                        str(output_dir),
                        "--backend",
                        "mineru-platform",
                        "--mineru-base-url",
                        f"http://127.0.0.1:{server.server_port}",
                        "--mineru-api-key",
                        "v4-secret",
                        "--mineru-timeout",
                        "5",
                        "--mineru-poll-interval",
                        "0.01",
                        "--table-quality",
                        "high",
                        "--json",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=_env(),
                )
                payload = json.loads(result.stdout)
                runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["table_quality"]["configured_backend"], "mineru-platform")
        self.assertEqual(payload["table_quality"]["effective_mineru_v4_model_version"], "vlm")
        self.assertTrue(payload["table_quality"]["high_accuracy_model_requested"])
        request_body = captured["body"]
        self.assertIsInstance(request_body, dict)
        self.assertEqual(request_body["model_version"], "vlm")
        attempt = runtime_report["remote_attempts"][0]
        self.assertEqual(attempt["backend"], "mineru-v4")
        self.assertEqual(attempt["effective_mineru_v4_model_version"], "vlm")
        context = runtime_report["performance"]["runtime_context"]
        self.assertEqual(context["mineru_v4_model_version"], "vlm")

    def test_backend_probe_mineru_v4_is_protocol_limited_without_network(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                str(CONVERT_SCRIPT),
                "backend",
                "probe",
                "--backend",
                "mineru-v4",
                "--mineru-base-url",
                "https://mineru.example.test/api/v4",
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

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["selected_backend"], "mineru-v4")
        self.assertEqual(payload["backends"][0]["status"], "available")
        self.assertTrue(any("protocol-limited" in reason for reason in payload["backends"][0]["reasons"]))
        network_checks = [item for item in payload["backends"][0]["checks"] if item["name"] == "network_check"]
        self.assertTrue(network_checks[0]["skipped"])

    def test_table_quality_auto_promotes_fastapi_pdf_to_high_accuracy_backend(self) -> None:
        captured: dict[str, object] = {"body": b""}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                captured["body"] = self.rfile.read(length)
                body = json.dumps({"task_id": "task-table-auto", "status": "pending"}).encode("utf-8")
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/tasks/task-table-auto":
                    body = json.dumps({"task_id": "task-table-auto", "status": "completed"}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/tasks/task-table-auto/result":
                    body = json.dumps(
                        {"results": {"paper": {"md_content": "# Auto Table\n\n<table><tr><td>A</td></tr></table>\n"}}}
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
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake table auto")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(CONVERT_SCRIPT),
                        "--input",
                        str(input_dir),
                        "--output",
                        str(output_dir),
                        "--backend",
                        "mineru-fastapi",
                        "--mineru-base-url",
                        f"http://127.0.0.1:{server.server_port}",
                        "--mineru-timeout",
                        "5",
                        "--mineru-poll-interval",
                        "0.01",
                        "--table-quality",
                        "auto",
                        "--json",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=_env(),
                )
                payload = json.loads(result.stdout)
                runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["table_quality"]["mode"], "auto")
        self.assertTrue(payload["table_quality"]["auto_triggered"])
        self.assertEqual(payload["table_quality"]["effective_mineru_fastapi_backend"], "hybrid-auto-engine")
        body = captured["body"]
        self.assertIsInstance(body, bytes)
        self.assertIn(b'name="backend"', body)
        self.assertIn(b"hybrid-auto-engine", body)
        context = runtime_report["performance"]["runtime_context"]
        self.assertEqual(context["table_quality"], "auto")
        self.assertTrue(context["table_quality_auto_triggered"])
        self.assertTrue(context["table_quality_high_accuracy_requested"])
        self.assertFalse(context["table_quality_degraded"])
        self.assertEqual(runtime_report["remote_attempts"][0]["mineru_fastapi_backend"], "hybrid-auto-engine")

    def test_table_quality_high_preserves_explicit_pipeline_backend(self) -> None:
        captured: dict[str, object] = {"body": b""}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                captured["body"] = self.rfile.read(length)
                body = json.dumps({"task_id": "task-table-pipeline", "status": "pending"}).encode("utf-8")
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/tasks/task-table-pipeline":
                    body = json.dumps({"task_id": "task-table-pipeline", "status": "completed"}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/tasks/task-table-pipeline/result":
                    body = json.dumps(
                        {"results": {"paper": {"md_content": "# Explicit Pipeline\n\n<table><tr><td>A</td></tr></table>\n"}}}
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
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake explicit pipeline")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(CONVERT_SCRIPT),
                        "--input",
                        str(input_dir),
                        "--output",
                        str(output_dir),
                        "--backend",
                        "mineru-fastapi",
                        "--mineru-base-url",
                        f"http://127.0.0.1:{server.server_port}",
                        "--mineru-timeout",
                        "5",
                        "--mineru-poll-interval",
                        "0.01",
                        "--table-quality",
                        "high",
                        "--mineru-fastapi-backend",
                        "pipeline",
                        "--json",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=_env(),
                )
                payload = json.loads(result.stdout)
                runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["table_quality"]["mode"], "high")
        self.assertEqual(payload["table_quality"]["effective_mineru_fastapi_backend"], "pipeline")
        self.assertFalse(payload["table_quality"]["high_accuracy_backend_requested"])
        self.assertEqual(payload["table_quality"]["reason"], "forced_high_accuracy_explicit_backend_preserved")
        body = captured["body"]
        self.assertIsInstance(body, bytes)
        self.assertIn(b'name="backend"', body)
        self.assertIn(b"pipeline", body)
        self.assertNotIn(b"hybrid-auto-engine", body)
        self.assertEqual(runtime_report["remote_attempts"][0]["mineru_fastapi_backend"], "pipeline")
        warnings = runtime_report["performance"]["slow_path_warnings"]
        self.assertTrue(any(item["code"] == "explicit_backend_preserved" for item in warnings))

    def test_table_quality_high_can_fallback_to_pipeline_after_backend_unsupported(self) -> None:
        captured_bodies: list[bytes] = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length)
                captured_bodies.append(body)
                if b"hybrid-auto-engine" in body:
                    raw = json.dumps({"detail": "backend hybrid-auto-engine is unsupported"}).encode("utf-8")
                    self.send_response(422)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                raw = json.dumps({"task_id": "task-table-pipeline", "status": "pending"}).encode("utf-8")
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/tasks/task-table-pipeline":
                    raw = json.dumps({"task_id": "task-table-pipeline", "status": "completed"}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                if self.path == "/tasks/task-table-pipeline/result":
                    raw = json.dumps({"results": {"paper": {"md_content": "# Pipeline Fallback\n"}}}).encode("utf-8")
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
                root = Path(tmp)
                input_dir = root / "input"
                output_dir = root / "handoff"
                input_dir.mkdir()
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake table fallback")
                result = subprocess.run(
                    [
                        sys.executable,
                        str(CONVERT_SCRIPT),
                        "--input",
                        str(input_dir),
                        "--output",
                        str(output_dir),
                        "--backend",
                        "mineru-fastapi",
                        "--mineru-base-url",
                        f"http://127.0.0.1:{server.server_port}",
                        "--mineru-timeout",
                        "5",
                        "--mineru-poll-interval",
                        "0.01",
                        "--table-quality",
                        "high",
                        "--json",
                    ],
                    text=True,
                    capture_output=True,
                    check=False,
                    env=_env(),
                )
                payload = json.loads(result.stdout)
                markdown = (output_dir / "documents" / "paper.md").read_text(encoding="utf-8")
                runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
                quality_report = json.loads((output_dir / "quality_report.json").read_text(encoding="utf-8"))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# Pipeline Fallback", markdown)
        self.assertEqual(len(captured_bodies), 2)
        self.assertIn(b"hybrid-auto-engine", captured_bodies[0])
        self.assertIn(b"pipeline", captured_bodies[1])
        self.assertEqual(payload["table_quality"]["fallback_count"], 1)
        self.assertTrue(payload["table_quality"]["table_quality_degraded"])
        self.assertEqual(payload["table_quality"]["fallback_events"][0]["reason"], "backend_unsupported")
        self.assertEqual(runtime_report["summary"]["remote_attempts"], 2)
        self.assertEqual(runtime_report["summary"]["remote_failed"], 1)
        self.assertEqual(runtime_report["summary"]["remote_success"], 1)
        self.assertEqual(runtime_report["remote_attempts"][0]["http_status"], 422)
        self.assertEqual(runtime_report["remote_attempts"][1]["mineru_fastapi_backend"], "pipeline")
        context = runtime_report["performance"]["runtime_context"]
        self.assertEqual(context["table_quality"], "high")
        self.assertTrue(context["table_quality_degraded"])
        self.assertEqual(context["table_quality_fallback_count"], 1)
        self.assertEqual(context["table_quality_fallback_events"][0]["status"], "fallback_succeeded")
        issues = quality_report["documents"][0]["issues"]
        self.assertTrue(any("table_quality_degraded" in item["message"] for item in issues))

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
        asset_timing = next(
            item
            for item in runtime_report["performance"]["stage_timings"]
            if item["stage"] == "asset" and item["operation"] == "remote_asset_materialization"
        )
        self.assertEqual(asset_timing["standard_stage"], "asset_planning")
        self.assertEqual(asset_timing["included_in_stage"], "conversion")
        self.assertFalse(asset_timing["counts_toward_total"])
        self.assertIsNotNone(asset_timing["duration_ms"])
        self.assertTrue(runtime_report["performance"]["runtime_context"]["persistent_mineru_reused"])
        self.assertFalse(runtime_report["performance"]["runtime_context"]["local_process_startup_included"])
        body = captured["body"]
        self.assertIsInstance(body, bytes)
        self.assertIn(b'name="return_images"', body)
        self.assertIn(b"true", body)

    def test_convert_mineru_fastapi_markdown_assets_renames_hash_images(self) -> None:
        opaque_name = "bf6c1779f2d8366285acc1e7fe5f21c6eccde9622f2c600842b9975bc4cdb9c2.jpg"
        image_payload = "data:image/jpeg;base64," + base64.b64encode(b"fake jpg bytes").decode("ascii")

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                body = json.dumps({"task_id": "task-hash-assets", "status": "pending"}).encode("utf-8")
                self.send_response(202)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/tasks/task-hash-assets":
                    body = json.dumps({"task_id": "task-hash-assets", "status": "completed"}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if self.path == "/tasks/task-hash-assets/result":
                    body = json.dumps(
                        {
                            "results": {
                                "paper": {
                                    "md_content": (
                                        "# APOLLO\n\n"
                                        "## PC-DMIS PRO\n\n"
                                        f"PC-DMIS PRO overview ![](images/{opaque_name})\n"
                                    ),
                                    "images": {f"images/{opaque_name}": image_payload},
                                }
                            }
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
                (input_dir / "paper.pdf").write_bytes(b"%PDF fake fastapi hash assets")
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
                manifest = json.loads((output_dir / "doc_manifest.json").read_text(encoding="utf-8"))
                runtime_report = json.loads((output_dir / "runtime_report.json").read_text(encoding="utf-8"))
                renamed_images = sorted((output_dir / "documents" / "images" / "paper").iterdir())
                renamed_name = renamed_images[0].name if renamed_images else ""
                renamed_bytes = renamed_images[0].read_bytes() if renamed_images else b""
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(renamed_images), 1)
        self.assertTrue(renamed_name.startswith("image-001_image_pc-dmis-pro-overview"))
        self.assertNotIn(opaque_name, markdown)
        self.assertIn(f"images/paper/{renamed_name}", markdown)
        self.assertEqual(renamed_bytes, b"fake jpg bytes")
        expected_asset_path = f"documents/images/paper/{renamed_name}"
        self.assertEqual(manifest["documents"][0]["assets"]["images"][0]["path"], expected_asset_path)
        asset_policy = runtime_report["remote_attempts"][0]["asset_policy"]
        self.assertEqual(asset_policy["saved"]["image_paths"], [f"images/paper/{renamed_name}"])
        self.assertEqual(asset_policy["saved"]["image_assets"][0]["path"], f"images/paper/{renamed_name}")
        self.assertEqual(asset_policy["saved"]["image_naming"]["renamed_count"], 1)

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
        failure = report["performance"]["failure_classification"]
        self.assertEqual(failure["timeout_count"], 1)
        self.assertEqual(report["summary"]["timeout_failure_count"], 1)
        timeout_stage = next(
            item
            for item in report["performance"]["stage_timings"]
            if item.get("source_path") == "slow.pdf"
        )
        self.assertEqual(timeout_stage["status"], "timeout")
        self.assertEqual(report["performance"]["runtime_context"]["cold_warm"], "cold_local_process")

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
