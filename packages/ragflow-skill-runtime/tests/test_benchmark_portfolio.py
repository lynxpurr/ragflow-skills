from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.benchmark_governance import import_benchmark_dataset, preflight_benchmark_dataset


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from benchmark_portfolio import (  # noqa: E402
    CONFIG_SCHEMA,
    REPORT_SCHEMA,
    BenchmarkPortfolioError,
    build_benchmark_portfolio,
    render_markdown,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class BenchmarkPortfolioTests(unittest.TestCase):
    def _make_subset(
        self,
        root: Path,
        *,
        subset_id: str,
        dataset: str,
        query_type: str,
        modalities: list[str],
        expected_terms: list[str],
        negative: bool = False,
        include_validation: bool = False,
    ) -> dict[str, Path]:
        source_root = root / f"{subset_id}-source"
        output = root / subset_id
        queries = source_root / "queries.json"
        qrels = source_root / "qrels.json"
        qa = source_root / "qa.json"
        attribution = source_root / "source_attribution.json"
        selection = source_root / "selection_report.json"
        query_metadata = {
            "type": query_type,
            "expected_modalities": modalities,
            **({"negative_case": True} if negative else {}),
        }
        _write_json(
            queries,
            {
                "queries": [
                    {
                        "id": f"{subset_id}-q1",
                        "question": "Which synthetic evidence is relevant?",
                        "expected_terms": expected_terms,
                        "metadata": query_metadata,
                    }
                ]
            },
        )
        _write_json(
            qrels,
            {
                "qrels": [
                    {
                        "query_id": f"{subset_id}-q1",
                        "expected_documents": [f"{subset_id}.md"],
                        "expected_chunks": ["sha256:" + "a" * 64],
                        "metadata": {"expected_modalities": modalities},
                    }
                ]
            },
        )
        _write_json(
            qa,
            {
                "schema": "ragflow_grounded_qa_v1",
                "items": [{"query_id": f"{subset_id}-q1", "answer": "synthetic answer"}],
            },
        )
        _write_json(
            attribution,
            {
                "schema": "ragflow_benchmark_source_attribution_v1",
                "dataset_name": dataset,
                "upstream_projects": ["public-project-label"],
                "license": "CC-BY-NC-4.0",
                "selected_source_ids": [f"{subset_id}-source"],
                "source_hashes": ["sha256:" + "1" * 64],
                "authorship": "human",
            },
        )
        _write_json(
            selection,
            {
                "schema": "ragflow_benchmark_selection_report_v1",
                "subset_id": subset_id,
                "selection_criteria": ["synthetic evidence coverage"],
                "query_types": [query_type],
                "modalities": modalities,
                "excluded_case_counts": {},
                "decision_tier": "exploratory",
            },
        )
        import_benchmark_dataset(
            queries_path=queries,
            qrels_path=qrels,
            qa_path=qa,
            source_attribution_path=attribution,
            selection_report_path=selection,
            output_dir=output,
            name=subset_id,
        )
        preflight = preflight_benchmark_dataset(manifest_path=output / "manifest.json")
        _write_json(output / "preflight.json", preflight)
        if include_validation:
            _write_json(
                output / "validation.json",
                {
                    "schema": "ragflow_validation_report_v1",
                    "ok": True,
                    "benchmark": {
                        "metrics": {
                            "empty_result_rate": 0.0,
                            "wrong_document_rate": 0.0,
                            "tag_pollution_rate": 0.0,
                            "strict_chunk_recall_at_k": 1.0,
                            "expected_term_recall_at_k": 1.0,
                            "table_term_recall_at_k": 1.0,
                        }
                    },
                },
            )
        return {
            "root": output,
            "manifest": output / "manifest.json",
            "source_attribution": output / "source_attribution.json",
            "selection_report": output / "selection_report.json",
            "preflight_report": output / "preflight.json",
            "validation_report": output / "validation.json",
        }

    @staticmethod
    def _subset_config(paths: dict[str, Path], *, subset_id: str, dataset: str) -> dict[str, object]:
        root = paths["root"]
        config: dict[str, object] = {
            "id": subset_id,
            "dataset": dataset,
            "license": "CC-BY-NC-4.0",
            "decision_tier": "exploratory",
            "sample_types": ["extractable_pdf", "complex_table"],
            "manifest": str(paths["manifest"].relative_to(root.parent)),
            "source_attribution": str(paths["source_attribution"].relative_to(root.parent)),
            "selection_report": str(paths["selection_report"].relative_to(root.parent)),
            "preflight_report": str(paths["preflight_report"].relative_to(root.parent)),
        }
        if paths["validation_report"].exists():
            config["validation_report"] = str(paths["validation_report"].relative_to(root.parent))
        return config

    def _write_portfolio_config(
        self,
        root: Path,
        subsets: list[dict[str, object]],
        *,
        schema: str = "ragflow_benchmark_portfolio_config_v1",
    ) -> Path:
        path = root / "portfolio.json"
        _write_json(
            path,
            {
                "schema": schema,
                "portfolio_id": "open-rag-finance-synthetic-v1",
                "subsets": subsets,
            },
        )
        return path

    def test_builds_two_subset_portfolio_from_explicit_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            open_rag = self._make_subset(
                root,
                subset_id="open-rag-seed-v1",
                dataset="open-rag-synthetic",
                query_type="mixed_table_plus_image",
                modalities=["mixed", "table", "image"],
                expected_terms=["caption evidence"],
            )
            finance = self._make_subset(
                root,
                subset_id="finance-table-v1",
                dataset="finance-table-synthetic",
                query_type="numeric_reasoning",
                modalities=["table", "text"],
                expected_terms=["42 percent"],
                negative=True,
                include_validation=True,
            )
            config_path = self._write_portfolio_config(
                root,
                [
                    self._subset_config(open_rag, subset_id="open-rag-seed-v1", dataset="open-rag-synthetic"),
                    self._subset_config(finance, subset_id="finance-table-v1", dataset="finance-table-synthetic"),
                ],
            )

            report = build_benchmark_portfolio(config_path)
            markdown = render_markdown(report)

        self.assertEqual(report["schema"], REPORT_SCHEMA)
        self.assertEqual(report["config_schema"], CONFIG_SCHEMA)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["summary"]["subset_count"], 2)
        self.assertEqual(report["summary"]["dataset_count"], 2)
        self.assertEqual(report["summary"]["query_count"], 2)
        self.assertEqual(report["summary"]["judged_query_count"], 2)
        self.assertEqual(report["summary"]["qa_count"], 2)
        self.assertEqual(report["coverage"]["expected_term_query_count"], 2)
        self.assertEqual(report["coverage"]["expected_chunk_query_count"], 2)
        self.assertGreater(report["coverage"]["table_numeric_query_count"], 0)
        self.assertEqual(report["coverage"]["negative_unanswerable_query_count"], 1)
        self.assertEqual(report["assessment"]["status"], "ready_with_review")
        self.assertIn("missing_observed_validation", report["assessment"]["reasons"])
        self.assertEqual(report["safety"]["ragflow_calls"], 0)
        self.assertFalse(report["safety"]["writes_live_ragflow"])
        self.assertNotIn(str(root), json.dumps(report, ensure_ascii=False))
        self.assertNotIn(str(root), markdown)
        self.assertIn("# RAGFlow Benchmark Portfolio", markdown)

    def test_rejects_invalid_config_contracts(self) -> None:
        invalid_cases = (
            ("wrong schema", "wrong", None, "schema"),
            ("duplicate subset ids", CONFIG_SCHEMA, "duplicate", "duplicate"),
            ("unsupported tier", CONFIG_SCHEMA, "tier", "decision_tier"),
        )
        for label, schema, mutation, expected_error in invalid_cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                subset = self._make_subset(
                    root,
                    subset_id="subset-v1",
                    dataset="dataset-synthetic",
                    query_type="fact",
                    modalities=["text"],
                    expected_terms=["alpha"],
                )
                subset_config = self._subset_config(subset, subset_id="subset-v1", dataset="dataset-synthetic")
                configs = [subset_config]
                if mutation == "duplicate":
                    configs.append(dict(subset_config))
                if mutation == "tier":
                    subset_config["decision_tier"] = "default_profile"
                config_path = self._write_portfolio_config(root, configs, schema=schema)

                with self.assertRaisesRegex(BenchmarkPortfolioError, expected_error):
                    build_benchmark_portfolio(config_path)

    def test_rejects_missing_or_disagreeing_required_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subset = self._make_subset(
                root,
                subset_id="subset-v1",
                dataset="dataset-synthetic",
                query_type="fact",
                modalities=["text"],
                expected_terms=["alpha"],
            )
            missing_manifest = self._subset_config(subset, subset_id="subset-v1", dataset="dataset-synthetic")
            missing_manifest["manifest"] = "missing/manifest.json"
            missing_config = self._write_portfolio_config(root, [missing_manifest])
            with self.assertRaisesRegex(BenchmarkPortfolioError, "manifest"):
                build_benchmark_portfolio(missing_config)

            copied_attribution = root / "copied_source_attribution.json"
            copied_attribution.write_text(subset["source_attribution"].read_text(encoding="utf-8"), encoding="utf-8")
            disagreement = self._subset_config(subset, subset_id="subset-v1", dataset="dataset-synthetic")
            disagreement["source_attribution"] = copied_attribution.name
            disagreement_config = self._write_portfolio_config(root, [disagreement])
            with self.assertRaisesRegex(BenchmarkPortfolioError, "manifest.*source_attribution"):
                build_benchmark_portfolio(disagreement_config)

    def test_rejects_license_disagreement_and_unreadable_optional_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subset = self._make_subset(
                root,
                subset_id="subset-v1",
                dataset="dataset-synthetic",
                query_type="fact",
                modalities=["text"],
                expected_terms=["alpha"],
            )
            wrong_license = self._subset_config(subset, subset_id="subset-v1", dataset="dataset-synthetic")
            wrong_license["license"] = "Apache-2.0"
            config_path = self._write_portfolio_config(root, [wrong_license])
            with self.assertRaisesRegex(BenchmarkPortfolioError, "license"):
                build_benchmark_portfolio(config_path)

            unreadable = self._subset_config(subset, subset_id="subset-v1", dataset="dataset-synthetic")
            invalid_report = root / "invalid-validation.json"
            invalid_report.write_text("not-json", encoding="utf-8")
            unreadable["validation_report"] = invalid_report.name
            config_path = self._write_portfolio_config(root, [unreadable])
            with self.assertRaisesRegex(BenchmarkPortfolioError, "validation_report"):
                build_benchmark_portfolio(config_path)

    def test_failed_preflight_or_missing_qrels_blocks_assessment(self) -> None:
        for mode in ("failed_preflight", "missing_qrels"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                subset = self._make_subset(
                    root,
                    subset_id="subset-v1",
                    dataset="dataset-synthetic",
                    query_type="fact",
                    modalities=["text"],
                    expected_terms=["alpha"],
                )
                if mode == "failed_preflight":
                    preflight = json.loads(subset["preflight_report"].read_text(encoding="utf-8"))
                    preflight["ok"] = False
                    preflight.setdefault("issues", []).append({"severity": "error", "code": "fixture_failure"})
                    _write_json(subset["preflight_report"], preflight)
                else:
                    (subset["root"] / "qrels.json").unlink()
                config_path = self._write_portfolio_config(
                    root,
                    [self._subset_config(subset, subset_id="subset-v1", dataset="dataset-synthetic")],
                )

                report = build_benchmark_portfolio(config_path)

            self.assertFalse(report["ok"])
            self.assertEqual(report["assessment"]["status"], "blocked")
            self.assertTrue(report["assessment"]["reasons"])

    def test_cli_writes_public_safe_json_markdown_and_redaction_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            private_host = "portfolio.internal.local"
            subset = self._make_subset(
                root,
                subset_id="subset-v1",
                dataset="dataset-synthetic",
                query_type="numeric_reasoning",
                modalities=["table"],
                expected_terms=["42 percent"],
                include_validation=True,
            )
            validation = json.loads(subset["validation_report"].read_text(encoding="utf-8"))
            validation["endpoint"] = f"http://{private_host}:9380/api"
            _write_json(subset["validation_report"], validation)
            config_path = self._write_portfolio_config(
                root,
                [self._subset_config(subset, subset_id="subset-v1", dataset="dataset-synthetic")],
            )
            report_json = root / "portfolio-report.json"
            report_md = root / "portfolio-report.md"
            redaction = root / "portfolio-report.redaction.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools" / "benchmark_portfolio.py"),
                    "--config",
                    str(config_path),
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(redaction),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            combined = "\n".join(
                [
                    result.stdout,
                    result.stderr,
                    report_json.read_text(encoding="utf-8") if report_json.exists() else "",
                    report_md.read_text(encoding="utf-8") if report_md.exists() else "",
                    redaction.read_text(encoding="utf-8") if redaction.exists() else "",
                ]
            )
            redaction_payload = json.loads(redaction.read_text(encoding="utf-8")) if redaction.exists() else {}

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn(str(root), combined)
        self.assertNotIn(private_host, combined)
        self.assertEqual(redaction_payload["schema"], "ragflow_report_redaction_report_v1")

    def test_repository_fixture_replay_is_deterministic_and_public_safe(self) -> None:
        fixtures = ROOT / "packages" / "ragflow-skill-runtime" / "tests" / "fixtures" / "benchmark_evidence"
        build_script = ROOT / "skills" / "ragflow-kb-build" / "scripts" / "build.py"
        portfolio_script = ROOT / "tools" / "benchmark_portfolio.py"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            open_rag = root / "open-rag"
            finance = root / "finance"
            sample = root / "open-rag-sample"
            commands = [
                [
                    sys.executable,
                    str(build_script),
                    "benchmark",
                    "import",
                    "--queries",
                    str(fixtures / "open_rag_queries.json"),
                    "--qrels",
                    str(fixtures / "open_rag_qrels.json"),
                    "--qa",
                    str(fixtures / "open_rag_qa.json"),
                    "--source-attribution",
                    str(fixtures / "open_rag_source_attribution.json"),
                    "--selection-report",
                    str(fixtures / "open_rag_selection_report.json"),
                    "--output",
                    str(open_rag),
                    "--name",
                    "open-rag-synthetic-v1",
                    "--report-md",
                    str(root / "open-rag-import.md"),
                    "--redaction-report",
                    str(root / "open-rag-import.redaction.json"),
                    "--json",
                ],
                [
                    sys.executable,
                    str(build_script),
                    "benchmark",
                    "preflight",
                    "--manifest",
                    str(open_rag / "manifest.json"),
                    "--report-json",
                    str(root / "open-rag-preflight.json"),
                    "--report-md",
                    str(root / "open-rag-preflight.md"),
                    "--redaction-report",
                    str(root / "open-rag-preflight.redaction.json"),
                    "--json",
                ],
                [
                    sys.executable,
                    str(build_script),
                    "benchmark",
                    "sample",
                    "--manifest",
                    str(open_rag / "manifest.json"),
                    "--output",
                    str(sample),
                    "--name",
                    "open-rag-synthetic-sample-v1",
                    "--size",
                    "2",
                    "--strategy",
                    "stratified",
                    "--seed",
                    "7",
                    "--report-json",
                    str(root / "open-rag-sample.json"),
                    "--report-md",
                    str(root / "open-rag-sample.md"),
                    "--redaction-report",
                    str(root / "open-rag-sample.redaction.json"),
                    "--json",
                ],
                [
                    sys.executable,
                    str(build_script),
                    "benchmark",
                    "import",
                    "--queries",
                    str(fixtures / "finance_queries.json"),
                    "--qrels",
                    str(fixtures / "finance_qrels.json"),
                    "--qa",
                    str(fixtures / "finance_qa.json"),
                    "--source-attribution",
                    str(fixtures / "finance_source_attribution.json"),
                    "--selection-report",
                    str(fixtures / "finance_selection_report.json"),
                    "--output",
                    str(finance),
                    "--name",
                    "finance-synthetic-v1",
                    "--report-md",
                    str(root / "finance-import.md"),
                    "--redaction-report",
                    str(root / "finance-import.redaction.json"),
                    "--json",
                ],
                [
                    sys.executable,
                    str(build_script),
                    "benchmark",
                    "preflight",
                    "--manifest",
                    str(finance / "manifest.json"),
                    "--report-json",
                    str(root / "finance-preflight.json"),
                    "--report-md",
                    str(root / "finance-preflight.md"),
                    "--redaction-report",
                    str(root / "finance-preflight.redaction.json"),
                    "--json",
                ],
            ]
            results = [
                subprocess.run(command, text=True, capture_output=True, check=False, cwd=ROOT)
                for command in commands
            ]
            for result in results:
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            config_path = root / "portfolio-config.json"
            shutil.copyfile(fixtures / "portfolio_config.example.json", config_path)
            portfolio_json = root / "portfolio.json"
            portfolio_md = root / "portfolio.md"
            portfolio_redaction = root / "portfolio.redaction.json"
            portfolio_result = subprocess.run(
                [
                    sys.executable,
                    str(portfolio_script),
                    "--config",
                    str(config_path),
                    "--report-json",
                    str(portfolio_json),
                    "--report-md",
                    str(portfolio_md),
                    "--redaction-report",
                    str(portfolio_redaction),
                ],
                text=True,
                capture_output=True,
                check=False,
                cwd=ROOT,
            )
            self.assertEqual(portfolio_result.returncode, 0, portfolio_result.stdout + portfolio_result.stderr)

            sample_selection = json.loads((sample / "selection_report.json").read_text(encoding="utf-8"))
            sample_qa = json.loads((sample / "qa.json").read_text(encoding="utf-8"))
            portfolio = json.loads(portfolio_json.read_text(encoding="utf-8"))
            selected_ids = sample_selection["selected_query_ids"]
            qa_query_ids = sorted(item["query_id"] for item in sample_qa["items"])
            public_text = "\n".join(
                [result.stdout + result.stderr for result in results]
                + [
                    portfolio_result.stdout,
                    portfolio_result.stderr,
                    *(path.read_text(encoding="utf-8") for path in root.glob("*.json")),
                    *(path.read_text(encoding="utf-8") for path in root.glob("*.md")),
                ]
            )

        self.assertEqual(sample_selection["parent_subset_id"], "open-rag-synthetic-v1")
        self.assertEqual(sample_selection["sampling"], {"strategy": "stratified", "seed": 7, "size": 2})
        self.assertEqual(selected_ids, sorted(selected_ids))
        self.assertEqual(len(selected_ids), 2)
        self.assertEqual(qa_query_ids, selected_ids)
        self.assertEqual(portfolio["summary"]["subset_count"], 2)
        self.assertEqual(portfolio["summary"]["query_count"], 6)
        self.assertEqual(portfolio["summary"]["qa_count"], 6)
        self.assertEqual(portfolio["coverage"]["expected_term_query_count"], 6)
        self.assertGreater(portfolio["coverage"]["table_numeric_query_count"], 0)
        self.assertEqual(portfolio["coverage"]["negative_unanswerable_query_count"], 1)
        self.assertEqual(portfolio["assessment"]["status"], "ready_with_review")
        self.assertEqual(portfolio["safety"]["ragflow_calls"], 0)
        self.assertNotIn(str(root), public_text)


if __name__ == "__main__":
    unittest.main()
