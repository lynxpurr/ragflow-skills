# Marker-Aware Candidate Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backward-compatible, deterministic `file / markers / auto` Markdown boundary engine for offline candidate chunk snapshots, with HTML-table atomicity, stable provenance, explainable fallback, and no live RAGFlow behavior.

**Architecture:** Extend the shared HTML-table parser with structural diagnostics, then let `benchmark_governance.snapshot_chunks` classify Markdown inputs and make per-document boundary decisions. Marker-derived ordinals use `source_chunk_id`, snapshot/report metadata lives under an additive `boundary` object, the low-level default remains `file`, and CLI/report/docs changes reuse the existing `snapshot-chunks` surface.

**Tech Stack:** Python 3.11 standard library, `html.parser.HTMLParser`, existing `NormalizedChunk` and stable-hash helpers, `argparse`, JSON/Markdown reports, pytest, schema identity, release hygiene, consumer acceptance, and strict-vendor smoke.

Design source: `docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md`

Safety boundary: offline files and neutral fixtures only. Do not call RAGFlow, acquire private benchmark sources, run DeepDoc, invoke an LLM/RAGAS backend, change Stage 8C, or claim marker-derived chunks are server-observed.

---

## File Map

- `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/html_tables.py`: expose balanced/unbalanced table structure and fenced-code lines while preserving `parse_html_tables()`.
- `packages/ragflow-skill-runtime/tests/test_html_tables.py`: focused parser diagnostics.
- `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py`: marker splitting, auto selection, provenance, boundary report, and Markdown rendering.
- `packages/ragflow-skill-runtime/tests/test_benchmark_governance.py`: runtime TDD and synthetic evidence mapping.
- `skills/ragflow-kb-build/scripts/build.py`: CLI option and forwarding.
- `packages/ragflow-skill-runtime/tests/test_kb_build_cli.py`: CLI, Markdown, and redaction coverage.
- `skills/ragflow-kb-build/SKILL.md`: concise user guidance.
- `docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md`: verified progress tracking.
- `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`: sanitized status while the expected-chunk row remains open.

### Task 1: Expose HTML Table Structural Diagnostics

**Files:**
- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/html_tables.py`
- Create: `packages/ragflow-skill-runtime/tests/test_html_tables.py`

- [x] **Step 1: Write failing tests**

Create:

```python
from __future__ import annotations

import unittest

from ragflow_skill_runtime import html_tables


class HtmlTableAnalysisTests(unittest.TestCase):
    def test_analysis_reports_balanced_ranges_and_fenced_lines(self) -> None:
        text = (
            "```html\n<table><tr><td>literal</td></tr></table>\n```\n"
            "<TABLE data-note=\">\"><tr><td>A</td></tr></TABLE>\n"
            "<table/>\n"
        )
        analysis = html_tables.analyze_html_table_structure(text)
        self.assertTrue(analysis.balanced)
        self.assertEqual(analysis.fenced_line_numbers, (1, 2, 3))
        self.assertEqual([(item.line_start, item.line_end) for item in analysis.tables], [(4, 4), (5, 5)])

    def test_analysis_reports_unclosed_and_unexpected_close_tags(self) -> None:
        analysis = html_tables.analyze_html_table_structure("</table>\n<table><tr><td>open\n")
        self.assertFalse(analysis.balanced)
        self.assertEqual(analysis.unclosed_table_count, 1)
        self.assertEqual(analysis.unexpected_close_count, 1)
```

- [x] **Step 2: Verify RED**

Run:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_html_tables.py -q
```

Expected: FAIL because `analyze_html_table_structure` is absent.

- [x] **Step 3: Implement the minimal structural API**

Add:

```python
@dataclass(frozen=True)
class HtmlTableAnalysis:
    tables: tuple[HtmlTableArtifact, ...]
    balanced: bool
    unclosed_table_count: int
    unexpected_close_count: int
    fenced_line_numbers: tuple[int, ...]


def _masked_fenced_code_with_lines(text: str) -> tuple[str, tuple[int, ...]]:
    masked: list[str] = []
    fenced: list[int] = []
    in_fence = False
    for line_number, line in enumerate(text.splitlines(), start=1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            masked.append("")
            fenced.append(line_number)
        elif in_fence:
            masked.append("")
            fenced.append(line_number)
        else:
            masked.append(line)
    return "\n".join(masked), tuple(fenced)
```

Initialize `unexpected_table_close_count = 0` on `_HtmlTableParser`. Increment it for an unmatched `</table>`. Add:

```python
def analyze_html_table_structure(text: str) -> HtmlTableAnalysis:
    masked, fenced = _masked_fenced_code_with_lines(text)
    parser = _HtmlTableParser()
    parser.feed(masked)
    parser.close()
    unclosed = len(parser._stack)
    parser.finish(final_line=max(1, len(masked.splitlines())))
    unexpected = parser.unexpected_table_close_count
    return HtmlTableAnalysis(
        tables=tuple(sorted(parser.tables, key=lambda item: (item.line_start, item.line_end))),
        balanced=unclosed == 0 and unexpected == 0,
        unclosed_table_count=unclosed,
        unexpected_close_count=unexpected,
        fenced_line_numbers=fenced,
    )


def parse_html_tables(text: str) -> list[HtmlTableArtifact]:
    return list(analyze_html_table_structure(text).tables)
```

- [x] **Step 4: Verify GREEN and legacy consumers**

```bash
python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_html_tables.py \
  packages/ragflow-skill-runtime/tests/test_doc_convert.py \
  packages/ragflow-skill-runtime/tests/test_handoff.py -q
```

Expected: PASS with unchanged legacy table counts.

- [x] **Step 5: Commit**

```bash
git add packages/ragflow-skill-runtime/src/ragflow_skill_runtime/html_tables.py packages/ragflow-skill-runtime/tests/test_html_tables.py
git commit -m "feat(runtime): expose HTML table structure diagnostics"
```

### Task 2: Add Marker Splitting And Offline Provenance

**Files:**
- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_benchmark_governance.py`

- [ ] **Step 1: Add and run a legacy characterization test**

```python
def test_snapshot_markdown_legacy_default_keeps_one_chunk(self) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / "source.md"
        output = root / "snapshot.json"
        source.write_text("alpha\n<!-- chunk -->\nbeta\n", encoding="utf-8")
        snapshot_chunks(input_path=source, output_path=output, include_content=True)
        payload = json.loads(output.read_text(encoding="utf-8"))
    self.assertEqual(payload["summary"]["chunk_count"], 1)
    self.assertIn("<!-- chunk -->", payload["chunks"][0]["content"])
```

Run the named test and expect PASS before production changes.

- [ ] **Step 2: Write the failing marker-mode test**

Use a document with narrative text, a marker inside a complete HTML table, and a final narrative chunk. Call:

```python
report = snapshot_chunks(
    input_path=source,
    output_path=output,
    include_content=True,
    markdown_boundary_mode="markers",
)
```

Assert three chunks whose `source_chunk_id` values share one
`marker-<12-hex-document-key>-` prefix and end in `0001` through `0003`, no candidate
`chunk_id`, aliases containing the source IDs, one complete table chunk, zero visible
delimiters, and one suppressed table boundary.

In the same RED phase, add `test_marker_snapshot_maps_grounded_evidence`. It creates
temporary narrative/table Markdown, a content-bearing marker snapshot, and two exact
grounded-QA spans. It calls `map_grounded_qa_evidence` and asserts full mapping coverage,
two mapped spans, two qrels-template rows, and only `sha256:` expected chunks.

- [ ] **Step 3: Verify RED**

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_benchmark_governance.py -k markers_split_and_preserve_source_identity -q
```

Expected: FAIL because `markdown_boundary_mode` is unknown.

- [ ] **Step 4: Implement the marker result and source ID contract**

Import `analyze_html_table_structure` and add:

```python
MARKDOWN_BOUNDARY_MODES = {"file", "markers", "auto"}
CANONICAL_CHUNK_DELIMITER = "<!-- chunk -->"


@dataclass(frozen=True)
class _MarkdownBoundaryResult:
    chunks: tuple[NormalizedChunk, ...]
    effective_mode: str
    decision_code: str
    selection_checks: tuple[dict[str, Any], ...]
    source_marker_count: int
    suppressed_table_boundary_count: int
    ignored_fenced_marker_count: int


def _source_chunk_id(chunk: NormalizedChunk) -> str | None:
    value = chunk.raw.get("source_chunk_id") if isinstance(chunk.raw, Mapping) else None
    return value if isinstance(value, str) and value else None
```

Split with `text.splitlines(keepends=True)`. A boundary is only `line.strip() == CANONICAL_CHUNK_DELIMITER`. Retain fenced markers, remove table markers without flushing, suppress whitespace-normalized empty segments, derive `document_key = hashlib.sha256(relative_posix_path.encode("utf-8")).hexdigest()[:12]`, and create chunks as:

```python
NormalizedChunk(
    content=content,
    document_name=path.name,
    document_id=str(path),
    raw={"source_chunk_id": f"marker-{document_key}-{index:04d}"},
)
```

Update aliases, snapshot items, runtime labels, and summary coverage to use `source_chunk_id` without changing `chunk_id` semantics.

- [ ] **Step 5: Verify GREEN**

Run both legacy and marker tests; expect PASS.

- [ ] **Step 6: Add RED edge tests, then implement only their behavior**

Cover leading/trailing/adjacent markers, whitespace-only segments, inline noncanonical marker text, fenced marker literals, attributed/mixed-case/self-closing tables, unbalanced tables, and repeated stable hashes. Run:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_benchmark_governance.py -k 'marker or forced_markers' -q
```

Expected first run: FAIL on missing edge behavior. After minimal corrections: PASS.

- [ ] **Step 7: Commit**

```bash
git add packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py packages/ragflow-skill-runtime/tests/test_benchmark_governance.py
git commit -m "feat(benchmark): add marker-aware candidate snapshots"
```

### Task 3: Add Per-Document Auto Selection And Boundary Metadata

**Files:**
- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_benchmark_governance.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_schema_identity_check.py`

- [ ] **Step 1: Write failing auto tests**

Cover successful `markers_selected`, all four ordered fallback codes, forced-mode errors, JSON rejection, and a directory with one marker file plus one marker-free file. Assert the directory result is:

```python
{
    "requested_mode": "auto",
    "effective_mode": "mixed",
    "document_mode_counts": {"file": 1, "markers": 1},
    "decision_code_counts": {"markers_selected": 1, "no_canonical_markers": 1},
}
```

Also assert candidate/offline scope, `observed_ragflow_chunks=False`, and all three zero-call/write counters.

- [ ] **Step 2: Verify RED**

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_benchmark_governance.py -k 'snapshot_markdown_auto or directory_mixed or json_rejects_markdown_boundary' -q
```

Expected: FAIL because auto aggregation is absent.

- [ ] **Step 3: Implement deterministic aggregation**

Classify input as Markdown file, Markdown directory, or JSON before parsing. Reject `markers/auto` for JSON. Evaluate Markdown per document, require every document to pass forced `markers`, and aggregate:

```python
boundary = {
    "requested_mode": requested_mode,
    "effective_mode": effective_mode,
    "evidence_scope": "candidate_offline",
    "observed_ragflow_chunks": False,
    "ragflow_calls": 0,
    "writes_live_ragflow": False,
    "script_owned_llm_calls": 0,
    "document_count": len(results),
    "document_mode_counts": dict(sorted(Counter(item.effective_mode for item in results).items())),
    "decision_code_counts": dict(sorted(Counter(item.decision_code for item in results).items())),
    "source_marker_count": sum(item.source_marker_count for item in results),
    "emitted_candidate_chunk_count": sum(len(item.chunks) for item in results if item.effective_mode == "markers"),
    "suppressed_table_boundary_count": sum(item.suppressed_table_boundary_count for item in results),
    "ignored_fenced_marker_count": sum(item.ignored_fenced_marker_count for item in results),
    "selection_check_counts": _selection_check_counts(results),
}
```

Store the same object in snapshot and report. Use `mixed` only as an aggregate effective mode. Do not add document names or paths to `boundary`.

- [ ] **Step 4: Verify GREEN and additive schema compatibility**

Add a test loading a snapshot containing `boundary` through `load_chunk_snapshot`. Run:

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_benchmark_governance.py packages/ragflow-skill-runtime/tests/test_schema_identity_check.py -q
python3 tools/schema_identity_check.py --report-json /tmp/marker-snapshot-schema.json >/tmp/marker-snapshot-schema.stdout
```

Expected: PASS and schema report `ok=true`; do not create a new schema identity.

- [ ] **Step 5: Commit**

```bash
git add packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py packages/ragflow-skill-runtime/tests/test_benchmark_governance.py packages/ragflow-skill-runtime/tests/test_schema_identity_check.py
git commit -m "feat(benchmark): add automatic snapshot boundary decisions"
```

### Task 4: Expose CLI Mode And Markdown Explanation

**Files:**
- Modify: `skills/ragflow-kb-build/scripts/build.py`
- Modify: `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py`
- Modify: `packages/ragflow-skill-runtime/tests/test_kb_build_cli.py`
- Modify: `skills/ragflow-kb-build/SKILL.md`

- [ ] **Step 1: Write failing CLI tests**

Test successful `--markdown-boundary-mode auto` with snapshot JSON, report JSON, Markdown, and redaction sidecar. Assert `## Boundary Decision`, requested/effective modes, redaction `ok`, and content only when `--include-content` is passed. Test JSON input with `markers` returns non-zero and a clear Markdown-only error. Test help lists `file`, `markers`, and `auto`.

- [ ] **Step 2: Verify RED**

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_kb_build_cli.py -k 'snapshot_chunks and markdown_boundary' -q
```

Expected: FAIL because the option is unknown.

- [ ] **Step 3: Implement CLI forwarding**

Add:

```python
parser.add_argument(
    "--markdown-boundary-mode",
    choices=("file", "markers", "auto"),
    default="file",
    help="Markdown-only boundary policy: compatible whole-file, forced markers, or deterministic auto",
)
```

Forward it from `_run_snapshot_chunks()`.

- [ ] **Step 4: Render boundary metadata**

In `render_benchmark_governance_markdown()` add a `## Boundary Decision` section. Render scalar safety/mode/count fields in fixed order and render the three count mappings with `json.dumps(..., sort_keys=True)`. Do not render paths or chunk content.

- [ ] **Step 5: Update public guidance**

Add:

```bash
python scripts/build.py snapshot-chunks --input ./handoff/documents --output ./run/candidate_chunk_snapshot.json --markdown-boundary-mode auto --report-md ./run/candidate_chunk_snapshot.md
```

Explain `auto` as guided offline choice, `file` as legacy-compatible, `markers` as expert fail-closed, and all three as non-observed/offline.

- [ ] **Step 6: Verify GREEN and inventories**

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_kb_build_cli.py packages/ragflow-skill-runtime/tests/test_report_surface_inventory.py packages/ragflow-skill-runtime/tests/test_runtime_resilience_inventory.py -k 'snapshot_chunks or snapshot-chunks' -q
```

Expected: PASS. Change inventory counts only if output categories or schema identities actually changed.

- [ ] **Step 7: Commit**

```bash
git add skills/ragflow-kb-build/scripts/build.py skills/ragflow-kb-build/SKILL.md packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py packages/ragflow-skill-runtime/tests/test_kb_build_cli.py
git commit -m "feat(kb-build): expose automatic snapshot boundaries"
```

### Task 5: Verify Synthetic Evidence Mapping And Reproducibility

**Files:**
- Modify: `packages/ragflow-skill-runtime/tests/test_benchmark_governance.py`

- [ ] **Step 1: Extend the previously RED end-to-end test with reproducibility assertions**

Run the Task 2 evidence-mapping test once before adding these assertions to confirm its
original mapping path is already green. Then add a second snapshot generation and assert
identical ordered `(stable_hash, source_chunk_id, content)` tuples, identical boundary
objects, and `observed_ragflow_chunks=False`.

- [ ] **Step 2: Verify the new reproducibility assertion is meaningful**

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_benchmark_governance.py -k marker_snapshot_maps_grounded_evidence -q
```

Expected: PASS when the runtime is deterministic. To prove the assertion is not vacuous,
temporarily compare the first tuple with reversed second-run order and verify the test
fails, then restore the correct assertion and rerun to PASS. Do not commit the temporary
mutation.

- [ ] **Step 3: Apply the smallest correction if the restored assertion fails**

Do not weaken exact-span matching and do not use content previews for full evidence. Re-run the test and expect PASS.

- [ ] **Step 4: Run all focused tests**

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests/test_html_tables.py packages/ragflow-skill-runtime/tests/test_benchmark_governance.py packages/ragflow-skill-runtime/tests/test_kb_build_cli.py packages/ragflow-skill-runtime/tests/test_schema_identity_check.py packages/ragflow-skill-runtime/tests/test_report_surface_inventory.py packages/ragflow-skill-runtime/tests/test_runtime_resilience_inventory.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add packages/ragflow-skill-runtime/tests/test_benchmark_governance.py
git commit -m "test(benchmark): prove marker snapshot evidence mapping"
```

### Task 6: Run Full Validation And Calibrate Documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md`
- Modify: `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`

- [ ] **Step 1: Compile and run the complete runtime suite**

```bash
python3 -m py_compile packages/ragflow-skill-runtime/src/ragflow_skill_runtime/html_tables.py packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py skills/ragflow-kb-build/scripts/build.py
python3 -m pytest packages/ragflow-skill-runtime/tests -q
```

Expected: exit 0 and zero failed tests.

- [ ] **Step 2: Run schema, hygiene, and diff gates**

```bash
git diff --check
python3 tools/schema_identity_check.py --report-json /tmp/marker-snapshot-final-schema.json >/tmp/marker-snapshot-final-schema.stdout
python3 tools/release_hygiene_check.py >/tmp/marker-snapshot-final-hygiene.json
```

Expected: both reports `ok=true`, zero failed identities, zero findings.

- [ ] **Step 3: Run release-facing acceptance sequentially**

```bash
python3 tools/manifest_schema_check.py
python3 tools/build_release.py --check
python3 tools/export_release_archives.py
python3 tools/consumer_acceptance.py --work-dir /tmp/marker-snapshot-consumer --overwrite
python3 tools/platform_smoke_matrix.py --profile strict-vendor-env --work-dir /tmp/marker-snapshot-platform
```

Expected: every command exits 0. Do not run release artifact commands in parallel.

- [ ] **Step 4: Update progress without closing gated rows**

Mark design A-F rows complete only after the corresponding command evidence is green. Leave G private evidence and H default promotion unchecked. In `docs/38`, record public offline implementation and synthetic mapping metrics, but keep the expected-chunk row open because private Open RAG/FinanceBench mapping, qrels approval, and observed validation were not performed.

- [ ] **Step 5: Validate docs safety**

```bash
git diff --check
rg -n "/home/|192\\.168|127\\.0\\.0\\.1|/tmp/|api[_-]?key|bearer|token|dataset_id|document_id|kb:" docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md || true
python3 tools/release_hygiene_check.py >/tmp/marker-snapshot-docs-hygiene.json
```

Expected: only benign field-name hits after manual review; hygiene `ok=true`, zero findings.

- [ ] **Step 6: Commit docs and verify branch**

```bash
git add docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md
git commit -m "docs: record marker snapshot offline validation"
git status --short --branch
git log -7 --oneline
```

Expected: clean implementation branch. Do not push unless explicitly requested.
