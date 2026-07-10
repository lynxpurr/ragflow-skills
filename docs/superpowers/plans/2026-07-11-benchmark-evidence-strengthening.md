# Benchmark Evidence Strengthening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the normalized benchmark artifact contract, add an offline multi-subset portfolio report, and establish a reproducible Open RAG plus FinanceBench evidence path without live RAGFlow mutation.

**Architecture:** Extend the existing `benchmark import/sample/preflight` lifecycle with optional attribution and selection artifacts, then add a standalone explicit-input `tools/benchmark_portfolio.py` aggregator. Synthetic fixtures and release gates prove behavior in the repository; real PDFs and raw dataset rows remain in a repository-external private run root and are summarized only through sanitized artifacts.

**Tech Stack:** Python 3.11 standard library, existing `ragflow_skill_runtime.benchmark_governance`, `argparse`, JSON/Markdown reports, shared report sanitizer, pytest, schema identity, consumer acceptance, strict-vendor platform smoke, release hygiene.

Status: ready for implementation
Design source: `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`

---

### Task 1: Add Source Attribution And Selection Contracts

**Files:**
- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_benchmark_governance.py`

- [ ] **Step 1: Write failing import-contract tests**

Add `test_import_benchmark_preserves_source_attribution_and_selection_report` using a
temporary query/qrels/QA set plus these two inputs:

```python
source_attribution.write_text(
    json.dumps(
        {
            "schema": "ragflow_benchmark_source_attribution_v1",
            "dataset_name": "finance-table-synthetic",
            "upstream_projects": ["public-project-label"],
            "license": "CC-BY-NC-4.0",
            "selected_source_ids": ["filing-001"],
            "source_hashes": ["sha256:" + "1" * 64],
            "authorship": "human",
        }
    ),
    encoding="utf-8",
)
selection_report.write_text(
    json.dumps(
        {
            "schema": "ragflow_benchmark_selection_report_v1",
            "subset_id": "finance-table-synthetic-v1",
            "selection_criteria": ["table evidence", "numeric evidence"],
            "query_types": ["table_lookup", "numeric_reasoning"],
            "modalities": ["table", "text"],
            "excluded_case_counts": {"missing_public_source": 1},
            "decision_tier": "exploratory",
        }
    ),
    encoding="utf-8",
)
```

Call `import_benchmark_dataset(..., source_attribution_path=source_attribution,
selection_report_path=selection_report)` and assert:

```python
manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
assert manifest["artifacts"]["source_attribution"] == "source_attribution.json"
assert manifest["artifacts"]["selection_report"] == "selection_report.json"
assert json.loads((output / "source_attribution.json").read_text())["license"] == "CC-BY-NC-4.0"
assert json.loads((output / "selection_report.json").read_text())["decision_tier"] == "exploratory"
```

- [ ] **Step 2: Write fail-closed validation tests**

Add independent tests for:

- wrong `source_attribution` schema;
- empty license;
- empty selected-source IDs, invalid authorship, or malformed `sha256:` labels;
- wrong `selection_report` schema;
- empty `selection_criteria`;
- invalid `decision_tier`;
- private paths, private endpoints, credential-shaped values, or raw evidence text in
  either normalized artifact;
- legacy imports with neither optional artifact still succeeding unchanged.

- [ ] **Step 3: Run the new tests and verify RED**

Run:

```bash
python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_benchmark_governance.py \
  -k 'source_attribution or selection_report' -q
```

Expected: FAIL because the new function arguments, schemas, and manifest artifacts do
not exist.

- [ ] **Step 4: Implement the artifact validators and import support**

Add constants:

```python
BENCHMARK_SOURCE_ATTRIBUTION_SCHEMA = "ragflow_benchmark_source_attribution_v1"
BENCHMARK_SELECTION_REPORT_SCHEMA = "ragflow_benchmark_selection_report_v1"
BENCHMARK_DECISION_TIERS = {
    "smoke",
    "exploratory",
    "promotion_candidate",
    "regression_baseline",
}
```

Extend `import_benchmark_dataset`:

```python
def import_benchmark_dataset(
    *,
    queries_path: str | Path,
    qrels_path: str | Path,
    output_dir: str | Path,
    name: str = "benchmark",
    description: str = "",
    qa_path: str | Path | None = None,
    source_attribution_path: str | Path | None = None,
    selection_report_path: str | Path | None = None,
    checkpoint_path: str | Path | None = None,
    resume: bool = False,
    batch_size: int | None = None,
) -> dict[str, Any]:
```

Implement private JSON-object loaders that enforce the schemas and required fields. Pass
the normalized objects into `_write_benchmark_artifacts`, write the two optional files,
and add their relative names to `manifest["artifacts"]`. Include their inputs in source
hash/checkpoint binding so resume fails if attribution or selection changes. Add compact
public-safe summary fields for attribution schema, selection schema, subset ID, license,
and decision tier so the existing Markdown renderer can expose the contract without
embedding source paths or raw selection content.

- [ ] **Step 5: Run focused runtime tests to GREEN**

Run:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_benchmark_governance.py -q
```

Expected: PASS.

### Task 2: Preserve Provenance During Deterministic Sampling

**Files:**
- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_benchmark_governance.py`

- [ ] **Step 1: Write a failing sample-provenance test**

Create an imported benchmark with both new artifacts, then call
`sample_benchmark_dataset(..., name="finance-table-synthetic-sample-v1",
strategy="stratified", seed=7)`. Assert the sample:

```python
sample_manifest = json.loads((sample_root / "manifest.json").read_text())
sample_selection = json.loads((sample_root / "selection_report.json").read_text())
assert sample_manifest["artifacts"]["source_attribution"] == "source_attribution.json"
assert sample_manifest["artifacts"]["selection_report"] == "selection_report.json"
assert sample_selection["subset_id"] == "finance-table-synthetic-sample-v1"
assert sample_selection["parent_subset_id"] == "finance-table-synthetic-v1"
assert sample_selection["sampling"] == {"strategy": "stratified", "seed": 7, "size": 2}
assert sample_selection["selected_query_ids"] == sorted(sample_selection["selected_query_ids"])
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_benchmark_governance.py \
  -k sample_preserves_attribution -q
```

Expected: FAIL because `resolve_benchmark_artifacts` and sampling do not resolve or write
the new artifacts.

- [ ] **Step 3: Extend artifact resolution and derived selection output**

Extend `resolve_benchmark_artifacts` to return `source_attribution` and
`selection_report`. Preserve the attribution object unchanged. Derive a new selection
report with the same schema, a `parent_subset_id`, the deterministic sampling block, and
sorted selected query IDs. Use the sample `name` as the new `subset_id` so the derived
subset never reuses the parent identity. Extend `sample_benchmark_dataset` with optional explicit
attribution/selection paths for the existing no-manifest input mode. When a manifest is
used, resolve both artifacts from the manifest; do not require duplicate CLI arguments.
Do not copy excluded raw cases or source text.

- [ ] **Step 4: Run import/sample/preflight tests**

Run:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_benchmark_governance.py -q
```

Expected: PASS.

### Task 3: Expose Backward-Compatible CLI Inputs

**Files:**
- Modify: `skills/ragflow-kb-build/scripts/build.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_kb_build_cli.py`
- Modify: `skills/ragflow-kb-build/SKILL.md`

- [ ] **Step 1: Write failing CLI tests**

Extend the benchmark import/sample subprocess coverage to pass:

```text
--source-attribution ./source_attribution.json
--selection-report ./selection_report.json
```

Assert the output manifest references both files, generated Markdown lists their schema
and decision tier, and the redaction sidecar removes any temporary input path. Add one
legacy CLI test proving the options remain optional.

- [ ] **Step 2: Run focused CLI tests and verify RED**

Run:

```bash
python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_kb_build_cli.py \
  -k 'benchmark_import or benchmark_sample' -q
```

Expected: FAIL because the options are unknown.

- [ ] **Step 3: Add CLI parser and sanitizer wiring**

Add `--source-attribution` and `--selection-report` to `benchmark import` and to the
explicit-input mode of `benchmark sample`. Forward them to runtime functions and include
them in `input_paths`/`context_json_paths` for report sanitization. Manifest-based sample
commands continue to inherit both artifacts from `manifest.json`. Update the concise
public skill examples without adding a real endpoint, source path, or dataset identifier.

- [ ] **Step 4: Run runtime and CLI tests**

Run:

```bash
python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_benchmark_governance.py \
  packages/ragflow-skill-runtime/tests/test_kb_build_cli.py \
  -k 'benchmark_import or benchmark_sample or source_attribution or selection_report' -q
```

Expected: PASS.

### Task 4: Implement The Offline Portfolio Report

**Files:**
- Create: `tools/benchmark_portfolio.py`
- Create: `packages/ragflow-skill-runtime/tests/test_benchmark_portfolio.py`

- [ ] **Step 1: Write the main failing portfolio test**

Create two synthetic normalized subset directories and a config:

```python
config = {
    "schema": "ragflow_benchmark_portfolio_config_v1",
    "portfolio_id": "open-rag-finance-table-v1",
    "subsets": [
        {
            "id": "open-rag-seed-v1",
            "dataset": "open-rag-synthetic",
            "license": "CC-BY-NC-4.0",
            "decision_tier": "exploratory",
            "sample_types": ["extractable_pdf", "complex_table"],
            "manifest": str(open_rag_root / "manifest.json"),
            "source_attribution": str(open_rag_root / "source_attribution.json"),
            "selection_report": str(open_rag_root / "selection_report.json"),
            "preflight_report": str(open_rag_root / "preflight.json"),
        },
        {
            "id": "finance-table-v1",
            "dataset": "finance-table-synthetic",
            "license": "CC-BY-NC-4.0",
            "decision_tier": "exploratory",
            "sample_types": ["complex_table"],
            "manifest": str(finance_root / "manifest.json"),
            "source_attribution": str(finance_root / "source_attribution.json"),
            "selection_report": str(finance_root / "selection_report.json"),
            "preflight_report": str(finance_root / "preflight.json"),
            "validation_report": str(finance_root / "validation.json"),
        },
    ],
}
```

Assert `build_benchmark_portfolio(config_path)` returns:

```python
assert report["schema"] == "ragflow_benchmark_portfolio_v1"
assert report["ok"] is True
assert report["summary"]["subset_count"] == 2
assert report["summary"]["dataset_count"] == 2
assert report["coverage"]["expected_term_query_count"] > 0
assert report["coverage"]["table_numeric_query_count"] > 0
assert report["assessment"]["status"] == "ready_with_review"
assert report["safety"]["ragflow_calls"] == 0
assert report["safety"]["writes_live_ragflow"] is False
```

Also assert the report JSON and Markdown contain no absolute temporary root.

- [ ] **Step 2: Add fail-closed tests**

Cover:

- wrong config schema;
- duplicate subset IDs;
- missing manifest;
- unsupported decision tier;
- config/license disagreement with `source_attribution.json`;
- config artifact paths disagreeing with the files referenced by `manifest.json`;
- unreadable preflight/validation report;
- private root and fake endpoint removed from JSON, Markdown, and redaction sidecar;
- missing live validation produces `ready_with_review`, not `blocked` and not `ready`;
- a failed preflight or missing qrels produces `blocked`.

- [ ] **Step 3: Run the new test file and verify RED**

Run:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_benchmark_portfolio.py -q
```

Expected: collection/import failure because the tool does not exist.

- [ ] **Step 4: Implement the report builder and Markdown renderer**

Define:

```python
CONFIG_SCHEMA = "ragflow_benchmark_portfolio_config_v1"
REPORT_SCHEMA = "ragflow_benchmark_portfolio_v1"
DECISION_TIERS = {"smoke", "exploratory", "promotion_candidate", "regression_baseline"}
ASSESSMENTS = {"ready", "ready_with_review", "blocked"}
```

Implement `build_benchmark_portfolio`, `render_markdown`, and CLI flags:

```text
--config
--report-json
--report-md
--redaction-report
```

Read only explicitly named files. Emit canonical SHA-256 digests for inputs, but publish
only artifact basenames and approved source hashes. Resolve relative subset artifact paths
against the portfolio config directory. Follow the existing repository-tool bootstrap by
adding `packages/ragflow-skill-runtime/src` to `sys.path` before importing the shared
sanitizer. Use `sanitize_report_payload` with every config/input/output path supplied as
redaction context and with private hosts derived from URLs discovered in explicit input
objects. Keep declared expected-chunk coverage separate from observed strict chunk-recall
metrics supplied by validation reports.

- [ ] **Step 5: Run compile and focused tests to GREEN**

Run:

```bash
python3 -m py_compile tools/benchmark_portfolio.py
python3 -m pytest packages/ragflow-skill-runtime/tests/test_benchmark_portfolio.py -q
```

Expected: PASS.

### Task 5: Add Schema, Report, And Release Governance

**Files:**
- Modify: `tools/schema_identity_check.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_schema_identity_check.py`
- Modify: `tools/consumer_acceptance.py`
- Modify: `tools/platform_smoke_matrix.py`
- Verify: `tools/report_surface_inventory.py`
- Verify: `tools/runtime_resilience_inventory.py`
- Verify: `tools/generated_markdown_audit.py`
- Verify: `packages/ragflow-skill-runtime/tests/test_report_surface_inventory.py`
- Verify: `packages/ragflow-skill-runtime/tests/test_runtime_resilience_inventory.py`
- Verify: `packages/ragflow-skill-runtime/tests/test_generated_markdown_audit.py`

- [ ] **Step 1: Add schema identity entries and failing tests**

Register:

```text
benchmark_source_attribution -> ragflow_benchmark_source_attribution_v1
benchmark_selection_report   -> ragflow_benchmark_selection_report_v1
benchmark_portfolio_config   -> ragflow_benchmark_portfolio_config_v1
benchmark_portfolio          -> ragflow_benchmark_portfolio_v1
```

Use source roots in `benchmark_governance.py` or `tools/benchmark_portfolio.py` and
coverage roots in their focused tests. Extend the schema-identity unit test to assert all
four keys.

- [ ] **Step 2: Add acceptance and strict-vendor smoke fixtures**

Use tiny synthetic JSON only. In consumer acceptance and strict-vendor smoke, verify the
public benchmark CLI changes only:

- benchmark import accepts attribution/selection artifacts;
- benchmark sample preserves attribution and derives selection evidence;
- import/sample Markdown and redaction sidecars remain public-safe.

Keep the standalone portfolio tool in focused repository tests rather than release-archive
consumer acceptance: it is not packaged as a public skill command. Verify separately that
the installed/public command count remains 104, the report inventory has zero
`needs_redaction` entries, the runtime inventory has zero candidates, and the generated
Markdown audit remains healthy.

- [ ] **Step 3: Run focused governance tests**

Run:

```bash
python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_schema_identity_check.py \
  packages/ragflow-skill-runtime/tests/test_consumer_acceptance.py \
  packages/ragflow-skill-runtime/tests/test_platform_smoke_matrix.py \
  packages/ragflow-skill-runtime/tests/test_report_surface_inventory.py \
  packages/ragflow-skill-runtime/tests/test_runtime_resilience_inventory.py \
  packages/ragflow-skill-runtime/tests/test_generated_markdown_audit.py -q
```

Expected: PASS.

- [ ] **Step 4: Run direct governance tools**

Run:

```bash
python3 tools/schema_identity_check.py \
  --report-json /tmp/benchmark-evidence-schema-identity.json
python3 tools/report_surface_inventory.py \
  --report-json /tmp/benchmark-evidence-report-inventory.json
python3 tools/runtime_resilience_inventory.py \
  --report-json /tmp/benchmark-evidence-runtime-inventory.json
python3 tools/generated_markdown_audit.py \
  --report-json /tmp/benchmark-evidence-generated-markdown.json
python3 tools/release_hygiene_check.py \
  >/tmp/benchmark-evidence-release-hygiene.json
```

Expected: schema identity and release hygiene `ok=true`; both public inventories remain
at 104 commands with zero candidate/needs-redaction findings.

### Task 6: Add Synthetic Evidence Fixtures And Hermes L0 Replay

**Files:**
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/open_rag_queries.json`
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/open_rag_qrels.json`
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/open_rag_qa.json`
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/finance_queries.json`
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/finance_qrels.json`
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/finance_qa.json`
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/open_rag_source_attribution.json`
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/open_rag_selection_report.json`
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/finance_source_attribution.json`
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/finance_selection_report.json`
- Create: `packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/portfolio_config.example.json`
- Create: `docs/39-benchmark-evidence-strengthening-hermes-test.md`

- [ ] **Step 1: Add neutral fixture content**

Use fake public labels and no copied dataset text. Include:

- text, table, numeric, mixed-modality, and negative query metadata;
- expected terms such as `alpha revenue`, `42 percent`, and `caption evidence`;
- fake stable chunk hashes using `sha256:` plus 64 repeated hex characters;
- document labels such as `filing-a.md` and `paper-a.md`;
- `CC-BY-NC-4.0` as a license label without a private source path.
- a portfolio config with paths relative to the config file:

```json
{
  "schema": "ragflow_benchmark_portfolio_config_v1",
  "portfolio_id": "open-rag-finance-synthetic-v1",
  "subsets": [
    {
      "id": "open-rag-synthetic-v1",
      "dataset": "open-rag-synthetic",
      "license": "CC-BY-NC-4.0",
      "decision_tier": "exploratory",
      "sample_types": ["extractable_pdf", "complex_table"],
      "manifest": "open-rag/manifest.json",
      "source_attribution": "open-rag/source_attribution.json",
      "selection_report": "open-rag/selection_report.json",
      "preflight_report": "open-rag-preflight.json"
    },
    {
      "id": "finance-synthetic-v1",
      "dataset": "finance-table-synthetic",
      "license": "CC-BY-NC-4.0",
      "decision_tier": "exploratory",
      "sample_types": ["complex_table"],
      "manifest": "finance/manifest.json",
      "source_attribution": "finance/source_attribution.json",
      "selection_report": "finance/selection_report.json",
      "preflight_report": "finance-preflight.json"
    }
  ]
}
```

- [ ] **Step 2: Add a repository-only replay test**

Extend `test_benchmark_portfolio.py` to copy the example config into a temporary run root,
then invoke import, preflight, sample, and portfolio generation from the fixtures. Assert
deterministic counts, QA preservation/filtering, derived selection provenance, and that
every output is public-safe.

- [ ] **Step 3: Run the complete synthetic chain**

Use `/tmp/ragflow-benchmark-evidence-synthetic-20260711` as the run root and execute:

```bash
python3 skills/ragflow-kb-build/scripts/build.py benchmark import \
  --queries packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/open_rag_queries.json \
  --qrels packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/open_rag_qrels.json \
  --qa packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/open_rag_qa.json \
  --source-attribution packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/open_rag_source_attribution.json \
  --selection-report packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/open_rag_selection_report.json \
  --output /tmp/ragflow-benchmark-evidence-synthetic-20260711/open-rag
python3 skills/ragflow-kb-build/scripts/build.py benchmark preflight \
  --manifest /tmp/ragflow-benchmark-evidence-synthetic-20260711/open-rag/manifest.json \
  --report-json /tmp/ragflow-benchmark-evidence-synthetic-20260711/open-rag-preflight.json
python3 skills/ragflow-kb-build/scripts/build.py benchmark sample \
  --manifest /tmp/ragflow-benchmark-evidence-synthetic-20260711/open-rag/manifest.json \
  --output /tmp/ragflow-benchmark-evidence-synthetic-20260711/open-rag-sample \
  --size 2 \
  --strategy stratified \
  --seed 7 \
  --report-json /tmp/ragflow-benchmark-evidence-synthetic-20260711/open-rag-sample.json \
  --report-md /tmp/ragflow-benchmark-evidence-synthetic-20260711/open-rag-sample.md \
  --redaction-report /tmp/ragflow-benchmark-evidence-synthetic-20260711/open-rag-sample.redaction.json
python3 skills/ragflow-kb-build/scripts/build.py benchmark import \
  --queries packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/finance_queries.json \
  --qrels packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/finance_qrels.json \
  --qa packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/finance_qa.json \
  --source-attribution packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/finance_source_attribution.json \
  --selection-report packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/finance_selection_report.json \
  --output /tmp/ragflow-benchmark-evidence-synthetic-20260711/finance
python3 skills/ragflow-kb-build/scripts/build.py benchmark preflight \
  --manifest /tmp/ragflow-benchmark-evidence-synthetic-20260711/finance/manifest.json \
  --report-json /tmp/ragflow-benchmark-evidence-synthetic-20260711/finance-preflight.json
cp packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/portfolio_config.example.json \
  /tmp/ragflow-benchmark-evidence-synthetic-20260711/portfolio-config.json
python3 tools/benchmark_portfolio.py \
  --config /tmp/ragflow-benchmark-evidence-synthetic-20260711/portfolio-config.json \
  --report-json /tmp/ragflow-benchmark-evidence-synthetic-20260711/portfolio.json \
  --report-md /tmp/ragflow-benchmark-evidence-synthetic-20260711/portfolio.md \
  --redaction-report /tmp/ragflow-benchmark-evidence-synthetic-20260711/portfolio.redaction.json
```

Expected: all commands exit 0, the portfolio is `ready_with_review`, and redaction has
zero unresolved findings.

- [ ] **Step 4: Write the Hermes instruction**

Authorize repository-only L0 replay of focused tests and the synthetic chain. Require a
repository-external run root, initial/final `git status`, separate tool/prose sensitive
scans, and zero RAGFlow/LLM calls. Require `approval_required` for any source download,
private-source conversion, RAGFlow HTTP call, DeepDoc, or live mutation.

### Task 7: Execute The Private-Source Offline Evidence Fill

**Files:**
- Update after evidence: `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`
- Update after evidence: `docs/35-standard-benchmark-dataset-integration-plan.md`
- Update only when rows close: `docs/32-retirement-transition-action-plan.md`
- Update only when a closeout decision changes: `docs/16-system-closeout-report.md`

- [ ] **Step 1: Prepare the repository-external source layout**

Use this exact private root layout; do not create it inside the repository:

```text
/tmp/ragflow-benchmark-evidence-private-20260711/
  private-conversion.yaml
  sources/open-rag/
  sources/financebench/
  normalized/open-rag/
  normalized/financebench/
  handoffs/open-rag/
  handoffs/financebench/
  reports/
  transition-runs/run-001/
  transition-runs/run-002/
  transition-runs/run-003/
  transition-runs/run-004/
  transition-runs/run-005/
```

Stop with `private_source_fill_required` if the operator has not supplied reviewed public
source inputs. Do not download or invent source evidence inside the implementation turn.

- [ ] **Step 2: Strengthen the Open RAG subset offline**

Preserve existing query IDs, add reviewed expected terms, source section/page metadata,
and negative coverage where the selected public records support it. Run import, preflight,
deterministic sample, and portfolio generation. Do not claim expected-chunk coverage
unless a reviewed chunk snapshot exists.

After the reviewed source artifacts exist, run:

```bash
python3 skills/ragflow-kb-build/scripts/build.py benchmark import \
  --queries /tmp/ragflow-benchmark-evidence-private-20260711/normalized/open-rag/queries.source.json \
  --qrels /tmp/ragflow-benchmark-evidence-private-20260711/normalized/open-rag/qrels.source.json \
  --qa /tmp/ragflow-benchmark-evidence-private-20260711/normalized/open-rag/qa.source.json \
  --source-attribution /tmp/ragflow-benchmark-evidence-private-20260711/normalized/open-rag/source_attribution.source.json \
  --selection-report /tmp/ragflow-benchmark-evidence-private-20260711/normalized/open-rag/selection_report.source.json \
  --output /tmp/ragflow-benchmark-evidence-private-20260711/normalized/open-rag/benchmark
python3 skills/ragflow-kb-build/scripts/build.py benchmark preflight \
  --manifest /tmp/ragflow-benchmark-evidence-private-20260711/normalized/open-rag/benchmark/manifest.json \
  --report-json /tmp/ragflow-benchmark-evidence-private-20260711/reports/open-rag-preflight.json
python3 skills/ragflow-kb-build/scripts/build.py benchmark sample \
  --manifest /tmp/ragflow-benchmark-evidence-private-20260711/normalized/open-rag/benchmark/manifest.json \
  --output /tmp/ragflow-benchmark-evidence-private-20260711/normalized/open-rag/sample \
  --size 5 \
  --strategy stratified \
  --seed 7 \
  --report-json /tmp/ragflow-benchmark-evidence-private-20260711/reports/open-rag-sample.json \
  --report-md /tmp/ragflow-benchmark-evidence-private-20260711/reports/open-rag-sample.md \
  --redaction-report /tmp/ragflow-benchmark-evidence-private-20260711/reports/open-rag-sample.redaction.json
```

Expected: the normalized subset preserves the existing stable query IDs, the sample is
deterministic, and no strict chunk metric is claimed without a reviewed snapshot-backed
validation report.

- [ ] **Step 3: Build the FinanceBench offline slice**

Select one filing and bounded questions from the operator-prepared public sample. Create
attribution, selection, queries, qrels, and QA artifacts; run formal conversion,
`inspect-handoff`, benchmark import/preflight, and KB `--dry-run`. Do not call RAGFlow to
build, parse, query, or obtain a live chunk snapshot. A reviewed offline handoff-derived
snapshot may be used only to strengthen evidence without any RAGFlow HTTP call.

Use the fixed private root from Step 1. When a reviewed conversion config is available at
`/tmp/ragflow-benchmark-evidence-private-20260711/private-conversion.yaml`, run:

```bash
python3 skills/ragflow-doc-to-md/scripts/convert.py pipeline \
  --input /tmp/ragflow-benchmark-evidence-private-20260711/sources/financebench \
  --output /tmp/ragflow-benchmark-evidence-private-20260711/handoffs/financebench \
  --config /tmp/ragflow-benchmark-evidence-private-20260711/private-conversion.yaml \
  --backend auto \
  --table-quality high \
  --redaction-report /tmp/ragflow-benchmark-evidence-private-20260711/reports/financebench-convert.redaction.json \
  --json
python3 skills/ragflow-kb-build/scripts/build.py inspect-handoff \
  --handoff /tmp/ragflow-benchmark-evidence-private-20260711/handoffs/financebench \
  --report-json /tmp/ragflow-benchmark-evidence-private-20260711/reports/financebench-handoff.json \
  --report-md /tmp/ragflow-benchmark-evidence-private-20260711/reports/financebench-handoff.md \
  --redaction-report /tmp/ragflow-benchmark-evidence-private-20260711/reports/financebench-handoff.redaction.json \
  --json
python3 skills/ragflow-kb-build/scripts/build.py \
  --doc-manifest /tmp/ragflow-benchmark-evidence-private-20260711/handoffs/financebench/doc_manifest.json \
  --retrieval-hints /tmp/ragflow-benchmark-evidence-private-20260711/handoffs/financebench/retrieval_hints.json \
  --ingest-plan /tmp/ragflow-benchmark-evidence-private-20260711/handoffs/financebench/ragflow_ingest_plan.yaml \
  --kb-name benchmark-finance-dry-run \
  --profile skills/ragflow-kb-build/templates/default-en-768.json \
  --dry-run \
  --json \
  >/tmp/ragflow-benchmark-evidence-private-20260711/reports/financebench-build-dry-run.json
python3 skills/ragflow-kb-build/scripts/build.py benchmark import \
  --queries /tmp/ragflow-benchmark-evidence-private-20260711/normalized/financebench/queries.source.json \
  --qrels /tmp/ragflow-benchmark-evidence-private-20260711/normalized/financebench/qrels.source.json \
  --qa /tmp/ragflow-benchmark-evidence-private-20260711/normalized/financebench/qa.source.json \
  --source-attribution /tmp/ragflow-benchmark-evidence-private-20260711/normalized/financebench/source_attribution.source.json \
  --selection-report /tmp/ragflow-benchmark-evidence-private-20260711/normalized/financebench/selection_report.source.json \
  --output /tmp/ragflow-benchmark-evidence-private-20260711/normalized/financebench/benchmark
python3 skills/ragflow-kb-build/scripts/build.py benchmark preflight \
  --manifest /tmp/ragflow-benchmark-evidence-private-20260711/normalized/financebench/benchmark/manifest.json \
  --report-json /tmp/ragflow-benchmark-evidence-private-20260711/reports/financebench-preflight.json
```

Expected: conversion either succeeds or produces a classified service/input failure;
`inspect-handoff`, dry-run, import, and preflight run only after the handoff/source inputs
exist. A classified conversion failure does not close the FinanceBench row; stop, retain
the public-safe failure class, and leave the step unchecked. None of these commands may
call RAGFlow.

- [ ] **Step 4: Produce the initial two-subset portfolio**

Run `tools/benchmark_portfolio.py` over both normalized subsets. Require table/numeric and
expected-term coverage, source attribution, selection evidence, and explicit missing-live
evidence. Retain only sanitized JSON/Markdown/redaction reports for public status updates.

Write the explicit config to
`/tmp/ragflow-benchmark-evidence-private-20260711/reports/portfolio-config.json`, with
paths relative to that file or absolute paths under the fixed private root, then run:

```bash
python3 tools/benchmark_portfolio.py \
  --config /tmp/ragflow-benchmark-evidence-private-20260711/reports/portfolio-config.json \
  --report-json /tmp/ragflow-benchmark-evidence-private-20260711/reports/portfolio.json \
  --report-md /tmp/ragflow-benchmark-evidence-private-20260711/reports/portfolio.md \
  --redaction-report /tmp/ragflow-benchmark-evidence-private-20260711/reports/portfolio.redaction.json
```

Expected: missing observed validation remains `ready_with_review`; the portfolio must not
present itself as a Level 3 retrieval regression baseline until it references pinned
per-subset benchmark validation reports usable by `benchmark trend` and `benchmark delta`.

- [ ] **Step 5: Aggregate transition observation evidence when available**

Require five reviewed, public-safe run roots under the fixed `transition-runs` layout. If
any run is missing or not meaningful, record `transition_observation_fill_required` and
leave the corresponding `docs/32` rows open. Otherwise run:

```bash
python3 tools/field_trial_metrics.py \
  /tmp/ragflow-benchmark-evidence-private-20260711/transition-runs/run-001 \
  /tmp/ragflow-benchmark-evidence-private-20260711/transition-runs/run-002 \
  /tmp/ragflow-benchmark-evidence-private-20260711/transition-runs/run-003 \
  /tmp/ragflow-benchmark-evidence-private-20260711/transition-runs/run-004 \
  /tmp/ragflow-benchmark-evidence-private-20260711/transition-runs/run-005 \
  --report-json /tmp/ragflow-benchmark-evidence-private-20260711/reports/transition-summary.json \
  --report-md /tmp/ragflow-benchmark-evidence-private-20260711/reports/transition-summary.md \
  --redaction-report /tmp/ragflow-benchmark-evidence-private-20260711/reports/transition-summary.redaction.json
```

Expected: the summary reports at least five meaningful runs, exposes missing sample
classes without inventing evidence, and has zero unresolved redaction findings.

### Task 8: Final Validation And Documentation Closeout

**Files:**
- Modify: `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`
- Modify as justified by evidence: `docs/32-retirement-transition-action-plan.md`
- Modify as justified by evidence: `docs/35-standard-benchmark-dataset-integration-plan.md`
- Modify as justified by evidence: `docs/16-system-closeout-report.md`
- Verify: `docs/36-ragflow-kb-parameter-materialization-plan.md`

- [ ] **Step 1: Run focused and full runtime validation**

Run:

```bash
python3 -m py_compile \
  packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py \
  skills/ragflow-kb-build/scripts/build.py \
  tools/benchmark_portfolio.py
python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_benchmark_governance.py \
  packages/ragflow-skill-runtime/tests/test_benchmark_portfolio.py \
  packages/ragflow-skill-runtime/tests/test_validation.py \
  packages/ragflow-skill-runtime/tests/test_schema_identity_check.py -q
python3 -m pytest packages/ragflow-skill-runtime/tests -q
```

Expected: all pass.

- [ ] **Step 2: Run release-facing validation sequentially**

Run:

```bash
git diff --check
python3 tools/manifest_schema_check.py
python3 tools/schema_identity_check.py \
  --report-json /tmp/benchmark-evidence-final-schema-identity.json
python3 tools/release_hygiene_check.py \
  >/tmp/benchmark-evidence-final-release-hygiene.json
python3 tools/build_release.py --check
python3 tools/export_release_archives.py
python3 tools/consumer_acceptance.py \
  --work-dir /tmp/benchmark-evidence-final-consumer --overwrite
python3 tools/platform_smoke_matrix.py \
  --profile strict-vendor-env \
  --work-dir /tmp/benchmark-evidence-final-platform
```

Expected: all pass with no hygiene findings and the public command inventory unchanged at
104.

- [ ] **Step 3: Update owning docs without over-closing gates**

Mark only implemented and verified public-offline rows complete in `docs/38`. Update
`docs/32` only for evidence actually produced. Record Stage 6/7 progress in `docs/35`.
Keep all `docs/36` Stage 8C, live, DeepDoc, and post-materialization rows open unless a
new pinned writable contract and separately approved live run exist.

- [ ] **Step 4: Run final safety and checklist review**

Run:

```bash
git status --short --branch
git diff --stat
git diff --check
git ls-files --others --exclude-standard
rg -n "/home/|192\\.168|127\\.0\\.0\\.1|/tmp/|api[_-]?key|bearer|token|dataset_id|document_id|kb:" \
  docs/03-development-plan.md \
  docs/16-system-closeout-report.md \
  docs/32-retirement-transition-action-plan.md \
  docs/35-standard-benchmark-dataset-integration-plan.md \
  docs/36-ragflow-kb-parameter-materialization-plan.md \
  docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md \
  docs/39-benchmark-evidence-strengthening-hermes-test.md \
  docs/superpowers/plans/2026-07-11-benchmark-evidence-strengthening.md || true
```

Review every hit manually. Do not stage, commit, push, run live RAGFlow, or close gated
rows unless the user explicitly requests the action and its prerequisites are satisfied.
