from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

from ragflow_skill_runtime.canonical_table_equivalence import (
    CANONICAL_TABLE_EQUIVALENCE_SCHEMA,
    CANONICAL_TABLE_VLM_REQUEST_SCHEMA,
    CANONICAL_TABLE_VLM_REVIEW_SCHEMA,
    compare_canonical_markdown_to_html,
    create_table_vlm_request,
    review_table_vlm_candidate,
)


MARKDOWN = (
    "# Limits\n\n"
    "| Model | Limits / Min | Limits / Max |\n"
    "| --- | --- | --- |\n"
    "| A | 1 mm | 2 mm |\n"
    "| A |  | 3 mm* |\n"
)

HTML = (
    "<table>\n"
    "<thead>\n"
    "<tr><th rowspan=\"2\">Model</th><th colspan=\"2\">Limits</th></tr>\n"
    "<tr><th>Min</th><th>Max</th></tr>\n"
    "</thead>\n"
    "<tbody>\n"
    "<tr><td rowspan=\"2\">A</td><td>1 mm</td><td>2 mm</td></tr>\n"
    "<tr><td></td><td>3 mm*</td></tr>\n"
    "</tbody>\n"
    "</table>\n"
)

ROOT = Path(__file__).resolve().parents[3]


def _load_module(name: str, relative_path: str) -> ModuleType:
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CanonicalTableEquivalenceTests(unittest.TestCase):
    def test_html_rowspan_and_colspan_normalize_to_canonical_markdown_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "canonical.md"
            derived_html = root / "derived.html"
            markdown.write_text(MARKDOWN, encoding="utf-8")
            derived_html.write_text(HTML, encoding="utf-8")

            report = compare_canonical_markdown_to_html(
                canonical_markdown_path=markdown,
                derived_html_path=derived_html,
            )

        self.assertEqual(report["schema"], CANONICAL_TABLE_EQUIVALENCE_SCHEMA)
        self.assertTrue(report["ok"])
        self.assertEqual(report["status"], "equivalent")
        self.assertEqual(report["summary"]["equivalent_table_count"], 1)
        self.assertEqual(report["tables"][0]["canonical_matrix"]["headers"], [
            "Model",
            "Limits / Min",
            "Limits / Max",
        ])
        self.assertEqual(report["tables"][0]["derived_matrix"]["rows"][1], ["A", "", "3 mm*"])
        self.assertGreater(report["tables"][0]["derived_merge_evidence"]["merged_cell_count"], 0)
        self.assertEqual(report["tables"][0]["merge_relation_comparison"]["status"], "normalized_equivalent")

    def test_cell_difference_blocks_equivalence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "canonical.md"
            derived_html = root / "derived.html"
            markdown.write_text(MARKDOWN, encoding="utf-8")
            derived_html.write_text(HTML.replace("3 mm*", "4 mm*"), encoding="utf-8")

            report = compare_canonical_markdown_to_html(
                canonical_markdown_path=markdown,
                derived_html_path=derived_html,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "blocked")
        self.assertIn("cell_value_mismatch", {item["code"] for item in report["findings"]})

    def test_empty_inputs_do_not_create_vacuous_equivalence_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "canonical.md"
            derived_html = root / "derived.html"
            markdown.write_text("# No table\n", encoding="utf-8")
            derived_html.write_text("<p>No table</p>\n", encoding="utf-8")

            report = compare_canonical_markdown_to_html(
                canonical_markdown_path=markdown,
                derived_html_path=derived_html,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(
            {item["code"] for item in report["findings"]},
            {"canonical_table_missing", "derived_table_missing"},
        )

    def test_vlm_request_and_matching_advisory_candidate_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "canonical.md"
            crop = root / "table-crop.png"
            request_path = root / "request.json"
            candidate_path = root / "candidate.json"
            markdown.write_text(MARKDOWN, encoding="utf-8")
            crop.write_bytes(b"exact source table crop")
            request = create_table_vlm_request(
                canonical_markdown_path=markdown,
                canonical_table_index=1,
                source_crop_path=crop,
                source_reference="page:1 table:1",
                table_id="table-001",
            )
            request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
            candidate = {
                "schema": "ragflow_canonical_table_vlm_candidate_v1",
                "advisory": True,
                "generated": True,
                "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                "table_id": "table-001",
                "source_crop_sha256": hashlib.sha256(crop.read_bytes()).hexdigest(),
                "provenance": {
                    "provider_label": "external-reviewer",
                    "model_label": "reviewed-model",
                    "operation": "table_extraction",
                },
                "matrix": {
                    "headers": ["Model", "Limits / Min", "Limits / Max"],
                    "rows": [["A", "1 mm", "2 mm"], ["A", "", "3 mm*"]],
                    "merged_cells": [],
                },
            }
            candidate_path.write_text(json.dumps(candidate, indent=2) + "\n", encoding="utf-8")

            review = review_table_vlm_candidate(
                request_path=request_path,
                candidate_path=candidate_path,
                canonical_markdown_path=markdown,
            )

        self.assertEqual(request["schema"], CANONICAL_TABLE_VLM_REQUEST_SCHEMA)
        self.assertFalse(request["llm_invoked"])
        self.assertEqual(request["summary"]["script_owned_llm_calls"], 0)
        self.assertEqual(review["schema"], CANONICAL_TABLE_VLM_REVIEW_SCHEMA)
        self.assertTrue(review["ok"])
        self.assertEqual(review["status"], "accepted_advisory")
        self.assertTrue(review["candidate"]["advisory"])
        self.assertFalse(review["policy"]["candidate_can_overwrite_canonical"])

    def test_vlm_candidate_mismatch_or_private_literal_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "canonical.md"
            crop = root / "table-crop.png"
            request_path = root / "request.json"
            candidate_path = root / "candidate.json"
            markdown.write_text(MARKDOWN, encoding="utf-8")
            crop.write_bytes(b"exact source table crop")
            request = create_table_vlm_request(
                canonical_markdown_path=markdown,
                canonical_table_index=1,
                source_crop_path=crop,
                source_reference="page:1 table:1",
                table_id="table-001",
            )
            request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
            candidate_path.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_canonical_table_vlm_candidate_v1",
                        "advisory": True,
                        "generated": True,
                        "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                        "table_id": "table-001",
                        "source_crop_sha256": hashlib.sha256(crop.read_bytes()).hexdigest(),
                        "provenance": {
                            "provider_label": "https://private.example.internal",
                            "model_label": "reviewed-model",
                            "operation": "table_extraction",
                        },
                        "matrix": {
                            "headers": ["Model", "Limits / Min", "Limits / Max"],
                            "rows": [["A", "1 mm", "9 mm"]],
                            "merged_cells": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            review = review_table_vlm_candidate(
                request_path=request_path,
                candidate_path=candidate_path,
                canonical_markdown_path=markdown,
            )

        self.assertFalse(review["ok"])
        self.assertEqual(review["status"], "blocked")
        codes = {item["code"] for item in review["findings"]}
        self.assertIn("candidate_matrix_mismatch", codes)
        self.assertIn("private_literal", codes)

    def test_vlm_candidate_rejects_nested_private_literals_and_malformed_matrix_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "canonical.md"
            crop = root / "table-crop.png"
            request_path = root / "request.json"
            candidate_path = root / "candidate.json"
            markdown.write_text(MARKDOWN, encoding="utf-8")
            crop.write_bytes(b"exact source table crop")
            request = create_table_vlm_request(
                canonical_markdown_path=markdown,
                canonical_table_index=1,
                source_crop_path=crop,
                source_reference="page:1 table:1",
                table_id="table-001",
            )
            request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
            candidate_path.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_canonical_table_vlm_candidate_v1",
                        "advisory": True,
                        "generated": True,
                        "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                        "table_id": "table-001",
                        "source_crop_sha256": hashlib.sha256(crop.read_bytes()).hexdigest(),
                        "provenance": {
                            "provider_label": "external-reviewer",
                            "model_label": "reviewed-model",
                            "operation": "table_extraction",
                            "details": {"endpoint": "https://private.example.internal"},
                        },
                        "matrix": {
                            "headers": ["Model", "Limits / Min", "Limits / Max"],
                            "rows": [["A", 1, "2 mm"]],
                            "merged_cells": [
                                {"row": True, "column": 1, "rowspan": 1, "colspan": 1}
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            review = review_table_vlm_candidate(
                request_path=request_path,
                candidate_path=candidate_path,
                canonical_markdown_path=markdown,
            )

        self.assertFalse(review["ok"])
        codes = {item["code"] for item in review["findings"]}
        self.assertIn("private_literal", codes)
        self.assertIn("candidate_matrix_invalid", codes)
        self.assertIn("candidate_merge_evidence_invalid", codes)

    def test_vlm_review_rejects_tampered_request_bindings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "canonical.md"
            crop = root / "table-crop.png"
            request_path = root / "request.json"
            candidate_path = root / "candidate.json"
            markdown.write_text(MARKDOWN, encoding="utf-8")
            crop.write_bytes(b"exact source table crop")
            request = create_table_vlm_request(
                canonical_markdown_path=markdown,
                canonical_table_index=1,
                source_crop_path=crop,
                source_reference="page:1 table:1",
                table_id="table-001",
            )
            request["source_reference"] = "page:2 table:9"
            request["canonical"]["table_fragment_sha256"] = "f" * 64
            request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
            candidate_path.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_canonical_table_vlm_candidate_v1",
                        "advisory": True,
                        "generated": True,
                        "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                        "table_id": "table-001",
                        "source_crop_sha256": hashlib.sha256(crop.read_bytes()).hexdigest(),
                        "provenance": {
                            "provider_label": "external-reviewer",
                            "model_label": "reviewed-model",
                            "operation": "table_extraction",
                        },
                        "matrix": {
                            "headers": ["Model", "Limits / Min", "Limits / Max"],
                            "rows": [["A", "1 mm", "2 mm"], ["A", "", "3 mm*"]],
                            "merged_cells": [],
                        },
                    }
                ),
                encoding="utf-8",
            )

            review = review_table_vlm_candidate(
                request_path=request_path,
                candidate_path=candidate_path,
                canonical_markdown_path=markdown,
            )

        self.assertFalse(review["ok"])
        codes = {item["code"] for item in review["findings"]}
        self.assertIn("vlm_request_hash_mismatch", codes)
        self.assertIn("stale_canonical_fragment", codes)


class CanonicalTableEvidenceCliTests(unittest.TestCase):
    def test_compare_mode_writes_json_markdown_redaction_and_stdout(self) -> None:
        cli = _load_module(
            "canonical_table_evidence_cli_test",
            "skills/ragflow-canonical-review/scripts/table_evidence.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "canonical.md"
            derived_html = root / "derived.html"
            report_json = root / "table-equivalence.json"
            report_md = root / "table-equivalence.md"
            redaction = root / "table-equivalence.redaction.json"
            markdown.write_text(MARKDOWN, encoding="utf-8")
            derived_html.write_text(HTML, encoding="utf-8")
            stdout = io.StringIO()

            with contextlib.redirect_stdout(stdout):
                code = cli.main(
                    [
                        "--mode",
                        "compare",
                        "--canonical-markdown",
                        str(markdown),
                        "--derived-html",
                        str(derived_html),
                        "--report-json",
                        str(report_json),
                        "--report-md",
                        str(report_md),
                        "--redaction-report",
                        str(redaction),
                        "--json",
                    ]
                )

            payload = json.loads(report_json.read_text(encoding="utf-8"))
            sidecar = json.loads(redaction.read_text(encoding="utf-8"))
            markdown_report = report_md.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertTrue(json.loads(stdout.getvalue())["ok"])
        self.assertEqual(payload["schema"], CANONICAL_TABLE_EQUIVALENCE_SCHEMA)
        self.assertIn("# Canonical Table Evidence", markdown_report)
        self.assertEqual(sidecar["schema"], "ragflow_report_redaction_report_v1")

    def test_vlm_request_and_review_modes_preserve_no_llm_boundary(self) -> None:
        cli = _load_module(
            "canonical_table_evidence_vlm_cli_test",
            "skills/ragflow-canonical-review/scripts/table_evidence.py",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            markdown = root / "canonical.md"
            crop = root / "table-crop.png"
            request_path = root / "request.json"
            candidate_path = root / "candidate.json"
            review_path = root / "review.json"
            markdown.write_text(MARKDOWN, encoding="utf-8")
            crop.write_bytes(b"exact source table crop")

            request_code = cli.main(
                [
                    "--mode",
                    "vlm-request",
                    "--canonical-markdown",
                    str(markdown),
                    "--canonical-table-index",
                    "1",
                    "--source-crop",
                    str(crop),
                    "--source-reference",
                    "page:1 table:1",
                    "--table-id",
                    "table-001",
                    "--report-json",
                    str(request_path),
                ]
            )
            candidate_path.write_text(
                json.dumps(
                    {
                        "schema": "ragflow_canonical_table_vlm_candidate_v1",
                        "advisory": True,
                        "generated": True,
                        "request_sha256": hashlib.sha256(request_path.read_bytes()).hexdigest(),
                        "table_id": "table-001",
                        "source_crop_sha256": hashlib.sha256(crop.read_bytes()).hexdigest(),
                        "provenance": {
                            "provider_label": "external-reviewer",
                            "model_label": "reviewed-model",
                            "operation": "table_extraction",
                        },
                        "matrix": {
                            "headers": ["Model", "Limits / Min", "Limits / Max"],
                            "rows": [["A", "1 mm", "2 mm"], ["A", "", "3 mm*"]],
                            "merged_cells": [],
                        },
                    }
                ),
                encoding="utf-8",
            )
            review_code = cli.main(
                [
                    "--mode",
                    "vlm-review",
                    "--canonical-markdown",
                    str(markdown),
                    "--request",
                    str(request_path),
                    "--candidate",
                    str(candidate_path),
                    "--report-json",
                    str(review_path),
                ]
            )
            request = json.loads(request_path.read_text(encoding="utf-8"))
            review = json.loads(review_path.read_text(encoding="utf-8"))

        self.assertEqual(request_code, 0)
        self.assertEqual(review_code, 0)
        self.assertFalse(request["llm_invoked"])
        self.assertEqual(request["summary"]["script_owned_llm_calls"], 0)
        self.assertEqual(review["status"], "accepted_advisory")
        self.assertFalse(review["policy"]["candidate_can_overwrite_canonical"])


if __name__ == "__main__":
    unittest.main()
