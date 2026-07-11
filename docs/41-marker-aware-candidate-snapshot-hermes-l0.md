# Hermes L0 Test For Marker-Aware Candidate Snapshots

Status: independent Hermes L0 replay passed and maintainer-accepted
Date: 2026-07-11
Owning plan: `docs/40-marker-aware-evidence-validation-and-promotion-plan.md`

**Goal:** Independently replay the committed marker-aware candidate snapshot and grounded
QA mapping path without network access, private data, RAGFlow, MinerU, LLMs, or repository
modification.

**Architecture:** Hermes runs focused tests and public CLI commands from one clean,
committed checkout. It creates only the exact neutral fixture set defined in this
instruction under a unique repository-external run root, verifies deterministic outputs
and fail-closed behavior, scans generated reports and agent prose separately, and proves
that the repository state is unchanged.

**Tech stack:** Python 3, pytest, `ragflow-kb-build snapshot-chunks`,
`ragflow-kb-build qa map-evidence`, JSON, Markdown, redaction sidecars, and Git read-only
state checks.

---

## Purpose And Authority

This instruction is the L0 execution companion to `docs/40`. It validates only the
public offline marker-aware implementation that already exists in the repository. It
does not authorize private benchmark evidence, observed RAGFlow evidence, live mutation,
or a default change.

Maximum authority: L0 repository-only neutral replay.

Authorized:

- read the current committed repository and committed tests;
- run the focused Python tests and public offline CLI commands named below;
- create the exact synthetic fixtures defined below under one unique external run root;
- write snapshots, reports, redaction sidecars, command logs, and the final report only
  under that run root;
- inspect Git state using read-only commands.

Not authorized:

- network access or any RAGFlow HTTP/API call, including read-only calls;
- Open RAG, FinanceBench, or any other private source or artifact access;
- RAGFlow dataset/KB creation, upload, parse, query, snapshot, update, delete, or cleanup;
- MinerU, DeepDoc, native-PDF conversion, or service probes;
- script-owned LLM or RAGAS calls;
- Stage 8C or any default/profile/parameter promotion;
- changing `.gitignore` or any other repository file;
- creating repository-local fixtures, reports, caches, worktrees, or temporary roots;
- `git add`, `git commit`, `git push`, branch changes, stash, reset, checkout, clean, or
  any other Git mutation;
- copying raw content-bearing snapshots into public docs or agent prose.

If a prohibited action appears necessary, stop with one exact code:
`approval_required:L1_private_candidate`,
`approval_required:L2_read_only_ragflow`,
`approval_required:L3_disposable_live`, or
`approval_required:L4_promotion_decision`. Do not broaden L0, repair the repository, or
substitute a private/live input.

## Expected Evidence Contract

The replay must prove all of the following:

- omitted mode and explicit `file` both preserve one-file/one-chunk behavior;
- forced `markers` creates deterministic chunks and keeps RAGFlow-facing `chunk_id`
  unset;
- `auto` selects `markers` or falls back to `file` with stable reason codes;
- a directory containing marker-safe and marker-free documents reports aggregate
  `mixed` mode;
- `.md` and `.markdown` inputs work;
- equal basenames in different directories retain distinct `source_chunk_id` prefixes
  and document coverage identities;
- empty directories and unsafe forced-marker directories fail closed;
- nested, mixed-case, attributed, same-line, and self-closing HTML table shapes remain
  atomic;
- a marker inside a balanced HTML table is suppressed rather than splitting the table;
- long-fence marker literals remain content and are counted as ignored fenced markers;
- unbalanced HTML tables fail in `markers` and fall back in `auto` with
  `unbalanced_html_table`;
- repeated snapshots reproduce ordered chunk content, stable hashes, source IDs, and
  boundary decisions;
- grounded spans from the exact committed synthetic fixture specification in this
  document map to `sha256:` expected chunks with full coverage;
- JSON, Markdown, and redaction sidecars are present and public-safe;
- all L0 safety counters remain zero/false;
- initial and final Git commit and worktree state are identical.

The `boundary` object must contain and validate these core fields:

```text
requested_mode
effective_mode
evidence_scope
observed_ragflow_chunks
ragflow_calls
writes_live_ragflow
script_owned_llm_calls
document_mode_counts
decision_code_counts
selection_check_counts
```

These are core assertions, not an exhaustive field whitelist. Marker, emitted-chunk,
table-suppression, fenced-marker, and document counts must also be reviewed for the
fixed fixture set.

## Copy-Paste Hermes Task

Send the following block to Hermes from the repository root after this instruction is
committed. Hermes must follow it literally and must not invent replacement fixtures.

````text
请在当前 ragflow-skills 仓库执行 marker-aware candidate snapshot 的独立 Hermes L0
复验。最大权限仅为 L0：仓库内已提交代码/测试加仓库外中性临时 fixture。禁止联网，
禁止读取任何私有 Open RAG/FinanceBench source 或 artifact，禁止任何 RAGFlow HTTP，
禁止 MinerU/DeepDoc，禁止 KB/dataset 操作，禁止脚本自有 LLM/RAGAS，禁止 Stage 8C，
禁止改变默认值，禁止修改仓库。

先读取：
- docs/40-marker-aware-evidence-validation-and-promotion-plan.md
- docs/41-marker-aware-candidate-snapshot-hermes-l0.md
- docs/superpowers/specs/2026-07-11-marker-aware-candidate-snapshot-design.md

### 1. Pin And Verify The Initial Repository State

Run from the repository root:

```bash
git status --short --branch
git status --porcelain=v1 --untracked-files=all
git rev-parse HEAD
git diff --check
BASE_HEAD="$(git rev-parse HEAD)"
export BASE_HEAD
```

Record the current commit as `BASE_HEAD`. The porcelain output must be empty. If it is
not empty, return `approval_required:dirty_worktree` and stop. Do not clean, stash,
reset, checkout, overwrite, or ignore the changes.

Execute steps 1-13 in one persistent shell session. If the agent interface launches a
fresh shell for each command, re-export the same `BASE_HEAD`, `RUN_LABEL`, `RUN_ROOT`,
`TMPDIR`, and `PYTHONDONTWRITEBYTECODE` values before every block; never create a second
run root partway through the replay.

Do not modify `.gitignore` or any repository file. Do not run `git add`, `git commit`,
`git push`, branch mutation, worktree creation, stash, reset, checkout, or clean.

### 2. Create One External Run Root

Create one unique external run root and keep its full path out of the final report:

```bash
set -euo pipefail
RUN_LABEL="ragflow-marker-aware-hermes-l0-$(date -u +%Y%m%dT%H%M%SZ)"
RUN_ROOT="$(mktemp -d -t "${RUN_LABEL}.XXXXXX")"
export RUN_LABEL RUN_ROOT
mkdir -p "$RUN_ROOT/artifacts" "$RUN_ROOT/fixtures" "$RUN_ROOT/logs" \
  "$RUN_ROOT/negative" "$RUN_ROOT/reports" "$RUN_ROOT/tmp"
export TMPDIR="$RUN_ROOT/tmp"
export PYTHONDONTWRITEBYTECODE=1
printf '%s\n' "$BASE_HEAD" > "$RUN_ROOT/base-head.txt"
```

All generated files, pytest state, logs, and final prose must stay under `RUN_ROOT`.
Use `pytest -p no:cacheprovider`; do not create repository-local pytest or bytecode
caches.

### 3. Create Only The Committed Synthetic Fixture Specification

Run this exact block. Do not change the text, add private material, download data, or
substitute another fixture:

```bash
python3 - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["RUN_ROOT"])
fixtures = root / "fixtures"
documents = fixtures / "documents"
(documents / "a").mkdir(parents=True)
(documents / "b").mkdir(parents=True)
(fixtures / "empty").mkdir()
(fixtures / "forced-directory").mkdir()

(documents / "a" / "source.md").write_text(
    "The narrative evidence is exact.\n"
    "<!-- chunk -->\n"
    "<TABLE data-note=\">\"><tr><td>Outer table starts.\n"
    "<table class=\"inner\"><tr><td>The nested table evidence is exact.</td></tr></table>\n"
    "<!-- chunk -->\n"
    "Outer table ends.</td></tr></TABLE>\n"
    "<!-- chunk -->\n"
    "````md\n"
    "```\n"
    "<!-- chunk -->\n"
    "```\n"
    "````\n"
    "The fenced marker remains literal.\n",
    encoding="utf-8",
)
(documents / "b" / "source.md").write_text(
    "The duplicate basename alpha evidence is exact.\n"
    "<!-- chunk -->\n"
    "The duplicate basename beta evidence is exact.\n",
    encoding="utf-8",
)
(documents / "plain.markdown").write_text(
    "This marker-free Markdown document must fall back to file mode.\n",
    encoding="utf-8",
)
(fixtures / "extension.markdown").write_text(
    "Extension alpha.\n<!-- chunk -->\n"
    "<TaBlE/><TABLE class=\"single\"><tr><td>The same-line table evidence is exact."
    "</td></tr></TABLE>\n",
    encoding="utf-8",
)
(fixtures / "unbalanced.md").write_text(
    "Unbalanced alpha.\n<!-- chunk -->\n<table><tr><td>open\n",
    encoding="utf-8",
)
(fixtures / "insufficient.md").write_text(
    "<!-- chunk -->\nOnly one non-empty segment.\n",
    encoding="utf-8",
)
(fixtures / "forced-directory" / "safe.md").write_text(
    "Safe alpha.\n<!-- chunk -->\nSafe beta.\n",
    encoding="utf-8",
)
(fixtures / "forced-directory" / "unsafe.md").write_text(
    "This document has no canonical marker.\n",
    encoding="utf-8",
)
(fixtures / "chunks.json").write_text(
    json.dumps({"chunks": [{"content": "JSON input is not a Markdown boundary input."}]}),
    encoding="utf-8",
)
(fixtures / "qa.json").write_text(
    json.dumps(
        {
            "schema": "ragflow_grounded_qa_v1",
            "items": [
                {
                    "id": "qa-narrative",
                    "query_id": "q-narrative",
                    "question": "Which narrative evidence is exact?",
                    "answer": "The narrative evidence is exact.",
                    "evidence": [
                        {
                            "document": "source.md",
                            "text": "The narrative evidence is exact.",
                        }
                    ],
                },
                {
                    "id": "qa-table",
                    "query_id": "q-table",
                    "question": "Which nested table evidence is exact?",
                    "answer": "The nested table evidence is exact.",
                    "evidence": [
                        {
                            "document": "source.md",
                            "text": "The nested table evidence is exact.",
                        }
                    ],
                },
            ],
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY
```

These are the only content-bearing inputs authorized in L0. They are defined by this
committed instruction and created outside the repository.

### 4. Run Focused Tests Without Repository Caches

```bash
python3 -m pytest -p no:cacheprovider \
  packages/ragflow-skill-runtime/tests/test_benchmark_governance.py \
  -k 'snapshot_markdown or marker_snapshot_maps_grounded_evidence or snapshot_json_rejects_markdown_boundary_modes or chunk_snapshot_loader_accepts_additive_boundary_object' \
  -q | tee "$RUN_ROOT/logs/benchmark-governance-tests.txt"

python3 -m pytest -p no:cacheprovider \
  packages/ragflow-skill-runtime/tests/test_kb_build_cli.py \
  -k 'snapshot_chunks_markdown_boundary or snapshot_chunks_help_lists_markdown_boundary_modes or qa_validate_subcommand_via_build_script' \
  -q | tee "$RUN_ROOT/logs/kb-build-cli-tests.txt"
```

Both commands must exit zero. Record the actual pass counts; do not hardcode a count in
the final report because later test additions may change collection totals.

### 5. Replay Legacy And Explicit File Modes

```bash
python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/documents/a/source.md" \
  --output "$RUN_ROOT/artifacts/legacy-default.snapshot.json" \
  --include-content \
  --report-json "$RUN_ROOT/reports/legacy-default.report.json" \
  --report-md "$RUN_ROOT/reports/legacy-default.report.md" \
  --redaction-report "$RUN_ROOT/reports/legacy-default.redaction.json" \
  --json > "$RUN_ROOT/logs/legacy-default.stdout.json"

python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/documents/a/source.md" \
  --output "$RUN_ROOT/artifacts/explicit-file.snapshot.json" \
  --include-content \
  --markdown-boundary-mode file \
  --report-json "$RUN_ROOT/reports/explicit-file.report.json" \
  --report-md "$RUN_ROOT/reports/explicit-file.report.md" \
  --redaction-report "$RUN_ROOT/reports/explicit-file.redaction.json" \
  --json > "$RUN_ROOT/logs/explicit-file.stdout.json"
```

### 6. Replay Forced Markers And Automatic Directory Selection

```bash
python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/documents/a/source.md" \
  --output "$RUN_ROOT/artifacts/markers.snapshot.json" \
  --include-content \
  --markdown-boundary-mode markers \
  --report-json "$RUN_ROOT/reports/markers.report.json" \
  --report-md "$RUN_ROOT/reports/markers.report.md" \
  --redaction-report "$RUN_ROOT/reports/markers.redaction.json" \
  --json > "$RUN_ROOT/logs/markers.stdout.json"

python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/documents" \
  --output "$RUN_ROOT/artifacts/auto-directory.snapshot.json" \
  --include-content \
  --markdown-boundary-mode auto \
  --report-json "$RUN_ROOT/reports/auto-directory.report.json" \
  --report-md "$RUN_ROOT/reports/auto-directory.report.md" \
  --redaction-report "$RUN_ROOT/reports/auto-directory.redaction.json" \
  --json > "$RUN_ROOT/logs/auto-directory.stdout.json"

python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/documents" \
  --output "$RUN_ROOT/artifacts/auto-directory-repeat.snapshot.json" \
  --include-content \
  --markdown-boundary-mode auto \
  --report-json "$RUN_ROOT/reports/auto-directory-repeat.report.json" \
  --report-md "$RUN_ROOT/reports/auto-directory-repeat.report.md" \
  --redaction-report "$RUN_ROOT/reports/auto-directory-repeat.redaction.json" \
  --json > "$RUN_ROOT/logs/auto-directory-repeat.stdout.json"

python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/extension.markdown" \
  --output "$RUN_ROOT/artifacts/extension.snapshot.json" \
  --include-content \
  --markdown-boundary-mode auto \
  --report-json "$RUN_ROOT/reports/extension.report.json" \
  --report-md "$RUN_ROOT/reports/extension.report.md" \
  --redaction-report "$RUN_ROOT/reports/extension.redaction.json" \
  --json > "$RUN_ROOT/logs/extension.stdout.json"
```

### 7. Replay Automatic Fail-Closed Fallbacks

```bash
python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/unbalanced.md" \
  --output "$RUN_ROOT/artifacts/unbalanced-auto.snapshot.json" \
  --include-content \
  --markdown-boundary-mode auto \
  --report-json "$RUN_ROOT/reports/unbalanced-auto.report.json" \
  --report-md "$RUN_ROOT/reports/unbalanced-auto.report.md" \
  --redaction-report "$RUN_ROOT/reports/unbalanced-auto.redaction.json" \
  --json > "$RUN_ROOT/logs/unbalanced-auto.stdout.json"

python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/insufficient.md" \
  --output "$RUN_ROOT/artifacts/insufficient-auto.snapshot.json" \
  --include-content \
  --markdown-boundary-mode auto \
  --report-json "$RUN_ROOT/reports/insufficient-auto.report.json" \
  --report-md "$RUN_ROOT/reports/insufficient-auto.report.md" \
  --redaction-report "$RUN_ROOT/reports/insufficient-auto.redaction.json" \
  --json > "$RUN_ROOT/logs/insufficient-auto.stdout.json"
```

### 8. Run Grounded QA Evidence Mapping

Use only the exact `qa.json` generated in step 3:

```bash
python3 skills/ragflow-kb-build/scripts/build.py qa map-evidence \
  --qa "$RUN_ROOT/fixtures/qa.json" \
  --chunk-snapshot "$RUN_ROOT/artifacts/markers.snapshot.json" \
  --output "$RUN_ROOT/artifacts/evidence-map.json" \
  --report-json "$RUN_ROOT/reports/evidence-map.report.json" \
  --report-md "$RUN_ROOT/reports/evidence-map.report.md" \
  --redaction-report "$RUN_ROOT/reports/evidence-map.redaction.json" \
  --json > "$RUN_ROOT/logs/evidence-map.stdout.json"
```

### 9. Run Required Negative Cases

Each command below must return nonzero. Keep raw error output private under `RUN_ROOT`.

```bash
set +e
python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/unbalanced.md" \
  --output "$RUN_ROOT/negative/unbalanced-markers.snapshot.json" \
  --markdown-boundary-mode markers --json \
  > "$RUN_ROOT/negative/unbalanced-markers.out" 2>&1
UNBALANCED_MARKERS_RC=$?

python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/empty" \
  --output "$RUN_ROOT/negative/empty-directory.snapshot.json" \
  --markdown-boundary-mode auto --json \
  > "$RUN_ROOT/negative/empty-directory.out" 2>&1
EMPTY_DIRECTORY_RC=$?

python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/forced-directory" \
  --output "$RUN_ROOT/negative/unsafe-directory.snapshot.json" \
  --markdown-boundary-mode markers --json \
  > "$RUN_ROOT/negative/unsafe-directory.out" 2>&1
UNSAFE_DIRECTORY_RC=$?

python3 skills/ragflow-kb-build/scripts/build.py snapshot-chunks \
  --input "$RUN_ROOT/fixtures/chunks.json" \
  --output "$RUN_ROOT/negative/json-auto.snapshot.json" \
  --markdown-boundary-mode auto --json \
  > "$RUN_ROOT/negative/json-auto.out" 2>&1
JSON_AUTO_RC=$?
set -e

printf '%s\n' "$UNBALANCED_MARKERS_RC" > "$RUN_ROOT/negative/unbalanced-markers.rc"
printf '%s\n' "$EMPTY_DIRECTORY_RC" > "$RUN_ROOT/negative/empty-directory.rc"
printf '%s\n' "$UNSAFE_DIRECTORY_RC" > "$RUN_ROOT/negative/unsafe-directory.rc"
printf '%s\n' "$JSON_AUTO_RC" > "$RUN_ROOT/negative/json-auto.rc"

test "$UNBALANCED_MARKERS_RC" -ne 0
test "$EMPTY_DIRECTORY_RC" -ne 0
test "$UNSAFE_DIRECTORY_RC" -ne 0
test "$JSON_AUTO_RC" -ne 0
```

Confirm the private error logs contain these stable failure classes respectively:

```text
unbalanced_html_table
did not contain any Markdown files
no_canonical_markers
requires a Markdown file or Markdown directory
```

Do not copy full temporary paths from those logs into the final report.

### 10. Verify Deterministic Output And Safety Fields

Run this exact verification block:

```bash
python3 - <<'PY'
import json
import os
from pathlib import Path

root = Path(os.environ["RUN_ROOT"])

def load(relative):
    return json.loads((root / relative).read_text(encoding="utf-8"))

legacy = load("artifacts/legacy-default.snapshot.json")
explicit_file = load("artifacts/explicit-file.snapshot.json")
markers = load("artifacts/markers.snapshot.json")
marker_report = load("reports/markers.report.json")
auto = load("artifacts/auto-directory.snapshot.json")
auto_repeat = load("artifacts/auto-directory-repeat.snapshot.json")
auto_report = load("reports/auto-directory.report.json")
extension = load("artifacts/extension.snapshot.json")
extension_report = load("reports/extension.report.json")
unbalanced = load("artifacts/unbalanced-auto.snapshot.json")
insufficient = load("artifacts/insufficient-auto.snapshot.json")
evidence_map = load("artifacts/evidence-map.json")
evidence_report = load("reports/evidence-map.report.json")

assert legacy["summary"]["chunk_count"] == 1
assert explicit_file["summary"]["chunk_count"] == 1
assert legacy["boundary"]["requested_mode"] == "file"
assert explicit_file["boundary"]["requested_mode"] == "file"
assert legacy["boundary"]["effective_mode"] == "file"
assert explicit_file["boundary"]["effective_mode"] == "file"
assert legacy["chunks"][0]["stable_hash"] == explicit_file["chunks"][0]["stable_hash"]

required_boundary_fields = {
    "requested_mode",
    "effective_mode",
    "evidence_scope",
    "observed_ragflow_chunks",
    "ragflow_calls",
    "writes_live_ragflow",
    "script_owned_llm_calls",
    "document_mode_counts",
    "decision_code_counts",
    "selection_check_counts",
}
assert required_boundary_fields <= set(markers["boundary"])
assert markers["summary"]["chunk_count"] == 3
assert markers["boundary"]["requested_mode"] == "markers"
assert markers["boundary"]["effective_mode"] == "markers"
assert markers["boundary"]["evidence_scope"] == "candidate_offline"
assert markers["boundary"]["observed_ragflow_chunks"] is False
assert markers["boundary"]["ragflow_calls"] == 0
assert markers["boundary"]["writes_live_ragflow"] is False
assert markers["boundary"]["script_owned_llm_calls"] == 0
assert markers["boundary"]["decision_code_counts"] == {"markers_selected": 1}
assert markers["boundary"]["document_mode_counts"] == {"markers": 1}
assert markers["boundary"]["source_marker_count"] == 4
assert markers["boundary"]["suppressed_table_boundary_count"] == 1
assert markers["boundary"]["ignored_fenced_marker_count"] == 1
assert markers["boundary"]["emitted_candidate_chunk_count"] == 3
assert marker_report["summary"]["possible_split_table_chunk_count"] == 0

joined_marker_content = "\n".join(item["content"] for item in markers["chunks"])
assert "<TABLE data-note=\">\">" in joined_marker_content
assert "<table class=\"inner\">" in joined_marker_content
assert "Outer table ends.</td></tr></TABLE>" in joined_marker_content
assert "<!-- chunk -->" in joined_marker_content
assert all("chunk_id" not in item for item in markers["chunks"])
assert all(item["source_chunk_id"] in item["aliases"] for item in markers["chunks"])

assert auto["boundary"]["effective_mode"] == "mixed"
assert auto["boundary"]["document_count"] == 3
assert auto["boundary"]["document_mode_counts"] == {"file": 1, "markers": 2}
assert auto["boundary"]["decision_code_counts"] == {
    "markers_selected": 2,
    "no_canonical_markers": 1,
}
assert auto["boundary"]["selection_check_counts"] == {
    "balanced_html_table": {"failed": 0, "passed": 3},
    "canonical_markers_available": {"failed": 1, "passed": 2},
    "sufficient_nonempty_chunks": {"failed": 1, "passed": 2},
}
assert auto["summary"]["document_count"] == 3
assert len(auto["document_coverage"]) == 3
assert len({item["document_id"] for item in auto["document_coverage"]}) == 3
assert auto_report["summary"]["possible_split_table_chunk_count"] == 0

source_ids = [
    item["source_chunk_id"]
    for item in auto["chunks"]
    if item.get("source_chunk_id")
]
assert len(source_ids) == 5
assert len({value.rsplit("-", 1)[0] for value in source_ids}) == 2

semantic = lambda payload: [
    (item["stable_hash"], item.get("source_chunk_id"), item["content"])
    for item in payload["chunks"]
]
assert semantic(auto) == semantic(auto_repeat)
assert auto["boundary"] == auto_repeat["boundary"]

assert extension["boundary"]["effective_mode"] == "markers"
assert extension["summary"]["chunk_count"] == 2
assert extension_report["summary"]["possible_split_table_chunk_count"] == 0
assert "<TaBlE/><TABLE class=\"single\">" in "\n".join(
    item["content"] for item in extension["chunks"]
)
assert unbalanced["boundary"]["effective_mode"] == "file"
assert unbalanced["boundary"]["decision_code_counts"] == {"unbalanced_html_table": 1}
assert insufficient["boundary"]["effective_mode"] == "file"
assert insufficient["boundary"]["decision_code_counts"] == {
    "insufficient_nonempty_chunks": 1
}

assert evidence_map["schema"] == "ragflow_grounded_qa_evidence_map_v1"
assert evidence_map["summary"]["evidence_mapping_coverage"] == 1.0
assert evidence_map["summary"]["mapped_span_count"] == 2
assert len(evidence_map["qrels_template"]["qrels"]) == 2
assert all(
    value.startswith("sha256:")
    for item in evidence_map["items"]
    for value in item["expected_chunks"]
)
assert evidence_report["summary"]["evidence_mapping_coverage"] == 1.0

for path in sorted((root / "reports").glob("*.redaction.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)

print("marker-aware L0 semantic verification: PASS")
PY
```

### 11. Scan Tool Reports Separately

Scan only shareable JSON/Markdown reports and redaction sidecars under
`$RUN_ROOT/reports`. Do not treat content-bearing snapshots under `artifacts` as public
reports.

Review separately for:

- unresolved absolute home or temporary paths;
- HTTP/HTTPS endpoints;
- credential-shaped API key, bearer, or token values;
- real dataset, document, or KB identifier values;
- private source names or raw retrieved chunks.

Run these scans and retain raw matches only under `RUN_ROOT/logs`:

```bash
rg -n '/home/|/Users/|/tmp/|https?://' "$RUN_ROOT/reports" \
  > "$RUN_ROOT/logs/tool-report-path-endpoint-scan.txt" || true
rg -n -i 'api[_-]?key|bearer|access[_-]?token|credential|secret' \
  "$RUN_ROOT/reports" \
  > "$RUN_ROOT/logs/tool-report-credential-scan.txt" || true
rg -n -i 'dataset_id|document_id|document id|kb_name|kb id|knowledgebase' \
  "$RUN_ROOT/reports" \
  > "$RUN_ROOT/logs/tool-report-identifier-scan.txt" || true
rg -n 'The narrative evidence is exact|The nested table evidence is exact|Outer table starts|The fenced marker remains literal' \
  "$RUN_ROOT/reports" \
  > "$RUN_ROOT/logs/tool-report-raw-content-scan.txt" || true
```

The path/endpoint and raw-content scans are expected to have no matches. The credential
scan may match only zero-valued redaction counters such as `explicit_secret: 0` or
`bearer_token: 0`. The identifier scan may match only schema/coverage field names,
redaction JSON paths, and the literal sanitizer value `<redacted:config-path>`. These are
benign only after manual review confirms the value class. A redaction finding means the
sanitizer applied a rule; it is not automatically an unresolved leak. Record applied
findings and unresolved findings separately. Unresolved findings must be zero.

### 12. Write And Scan Agent Prose Separately

Write the final Chinese report to:

```text
$RUN_ROOT/hermes-final-report.md
```

The report may contain `RUN_LABEL` and report basenames, but must not contain the full
run-root path. Run the same path, endpoint, credential, identifier, private-source, and
raw-content scan against this prose separately from tool reports. Unresolved findings
must be zero.

```bash
rg -n '/home/|/Users/|/tmp/|https?://' "$RUN_ROOT/hermes-final-report.md" \
  > "$RUN_ROOT/logs/agent-prose-path-endpoint-scan.txt" || true
rg -n -i 'api[_-]?key|bearer|access[_-]?token|credential|secret' \
  "$RUN_ROOT/hermes-final-report.md" \
  > "$RUN_ROOT/logs/agent-prose-credential-scan.txt" || true
rg -n -i 'dataset_id|document_id|document id|kb_name|kb id|knowledgebase' \
  "$RUN_ROOT/hermes-final-report.md" \
  > "$RUN_ROOT/logs/agent-prose-identifier-scan.txt" || true
rg -n 'The narrative evidence is exact|The nested table evidence is exact|Outer table starts|The fenced marker remains literal' \
  "$RUN_ROOT/hermes-final-report.md" \
  > "$RUN_ROOT/logs/agent-prose-raw-content-scan.txt" || true
```

The prose scans may match only report headings or explicit zero-result statements, such
as `Unresolved credentials: 0`. They must not match a path, endpoint, credential value,
real resource identifier, or fixture content.

### 13. Verify The Final Repository State

Run:

```bash
git status --short --branch
git status --porcelain=v1 --untracked-files=all
git diff --check
git rev-parse HEAD
test "$(git rev-parse HEAD)" = "$(cat "$RUN_ROOT/base-head.txt")"
```

The final porcelain output must be empty and final HEAD must equal `BASE_HEAD`. If any
repository file, `.gitignore`, cache, report, fixture, or untracked path was created or
changed, mark `test_noncompliant:repository_modified` and stop. Do not clean or commit it.

The final response must be a concise Chinese summary containing:

- commit and identical initial/final Git state;
- focused test command results and actual pass counts;
- legacy/default, forced-marker, auto/mixed, extension, fallback, and negative-case
  results;
- stable repeated hash/source-ID result;
- QA mapping coverage, mapped span count, and `sha256:` expected-chunk result;
- core `boundary` fields and exact zero-call/non-mutation values;
- tool-report and agent-prose scans as two separate results;
- public-safe run label and report basenames only;
- explicit statement that no private source, network, RAGFlow, MinerU, DeepDoc,
  LLM/RAGAS, Stage 8C, default change, repository modification, commit, or push occurred;
- residual gates: L1 private candidate review, L2 observed validation, optional L3
  disposable validation, and L4 promotion decision all remain closed.
````

## Hermes Final Report Template

```markdown
# Hermes Marker-Aware Candidate Snapshot L0 Report

Date:
Agent:
Repository commit:
Authorization: L0 repository-only neutral replay
Initial worktree: clean/noncompliant
Final worktree: clean/noncompliant
Repository modified: no/yes

## Verification

| Check | Status | Public-safe evidence |
| --- | --- | --- |
| Benchmark-governance focused tests | pass/fail | |
| KB-build CLI focused tests | pass/fail | |
| Legacy/default file behavior | pass/fail | |
| Forced markers behavior | pass/fail | |
| Auto directory mixed behavior | pass/fail | |
| Markdown extension behavior | pass/fail | |
| Unbalanced/insufficient fallback | pass/fail | |
| Required negative cases | pass/fail | |
| Repeated semantic identity | pass/fail | |
| QA evidence mapping | pass/fail | |

## Boundary Contract

Requested/effective modes:
Evidence scope:
Observed RAGFlow chunks:
RAGFlow calls:
Writes live RAGFlow:
Script-owned LLM calls:
Document mode counts:
Decision code counts:
Selection check counts:
Marker/table/fence counts:

## Evidence Mapping

Coverage:
Mapped spans:
Expected chunks use sha256:
Candidate/offline only:

## Sensitive Review

Tool reports scanned separately:
Agent prose scanned separately:
Unresolved paths:
Unresolved endpoints:
Unresolved credentials:
Unresolved real identifiers:
Unresolved private/raw content:
Applied redactions explained:

## Artifacts

Run label:
Report basenames:

## Decision

L0 reproducible:
L1 remains gated:
L2 remains gated:
L3 remains gated:
L4 remains gated:
Default changed: no
Next action:
```

## Local Maintainer Calibration

The instruction was locally calibrated before commit without running Hermes:

- the exact fixture-generation block completed successfully under an external temporary
  root;
- the benchmark-governance selection passed with 16 tests and 5 subtests;
- the KB-build CLI selection passed with 4 tests;
- all positive CLI snapshot and QA mapping commands returned zero;
- the four required negative commands returned code 2 with the expected stable failure
  classes;
- the exact semantic verification block printed
  `marker-aware L0 semantic verification: PASS`;
- repeated directory snapshots matched on ordered content, stable hashes, source IDs,
  and boundary metadata;
- QA mapping covered 2 of 2 spans and emitted only `sha256:` expected chunks;
- the tool-report path/endpoint and raw-content scans had no matches;
- credential and identifier scans contained only reviewed zero counters, schema/coverage
  fields, redaction JSON paths, and sanitized config-path values;
- no network, private source, RAGFlow, MinerU, DeepDoc, LLM/RAGAS, Stage 8C, default
  change, or repository mutation was part of calibration.

This local calibration proves that the instruction is executable against the current
implementation. By itself, it is not independent Hermes evidence and does not close any
L0 execution checkbox in `docs/40`.

## Independent Hermes Replay Evidence

Hermes independently replayed this instruction on 2026-07-11 against commit `fb38de2`.
The initial and final porcelain states were empty, the final commit matched the captured
base commit, and the repository was not modified.

Verified results:

- benchmark-governance selection: 16 passed with 5 subtests;
- KB-build CLI selection: 4 passed;
- omitted/default and explicit `file`: one chunk each with matching stable hashes;
- forced `markers`: three chunks, four source markers, one suppressed table boundary,
  one ignored fenced marker, and no RAGFlow-facing `chunk_id` values;
- directory `auto`: `mixed` across three documents with two marker-selected documents
  and one deterministic file fallback;
- `.markdown`, duplicate-basename isolation, nested/mixed-case/same-line/self-closing
  table shapes, unbalanced fallback, and insufficient-chunk fallback passed;
- all four negative commands returned code 2 with their expected failure classes;
- repeated snapshots matched on ordered content, stable hashes, source IDs, and boundary
  decisions;
- neutral QA mapping covered 2 of 2 evidence spans and emitted only `sha256:` expected
  chunks;
- `evidence_scope=candidate_offline`, `observed_ragflow_chunks=false`,
  `ragflow_calls=0`, `writes_live_ragflow=false`, and
  `script_owned_llm_calls=0` remained explicit;
- path/endpoint and raw-content scans had no matches. Credential and identifier scans
  contained only reviewed zero counters, schema/coverage labels, redaction JSON paths,
  sanitized config-path values, or equivalent descriptive prose; unresolved sensitive
  findings were zero;
- no private source, network, RAGFlow, MinerU, DeepDoc, LLM/RAGAS, Stage 8C, default
  change, Git mutation, commit, or push occurred.

The retained public-safe run label is
`ragflow-marker-aware-hermes-l0-20260711T103549Z`. Maintainer review inspected the final
report, focused test logs, negative return codes and errors, key snapshot and evidence-map
artifacts, redaction sidecars, and separate tool/prose scan logs, then reran the committed
semantic verification block successfully.

This replay closes only the L0 execution rows in `docs/40`. L1 private candidate review,
L2 observed validation, optional L3 disposable validation, and L4 promotion remain
separately authorization-gated.

## Acceptance Criteria

The L0 replay passes only when:

1. Initial and final Git states are clean, identical, and on the same commit.
2. No repository file, `.gitignore`, cache, report, fixture, or untracked path is
   created or changed.
3. Both focused test commands pass without repository-local pytest or bytecode caches.
4. The public CLI replay proves legacy `file`, forced `markers`, deterministic `auto`,
   aggregate `mixed`, `.markdown`, duplicate-basename, table, fence, and fallback
   behavior.
5. All four negative cases return nonzero with the expected failure classes.
6. Repeated snapshots reproduce ordered content, stable hashes, source IDs, and boundary
   decisions.
7. The exact committed synthetic QA fixture maps two spans with full coverage and only
   `sha256:` expected chunks.
8. The core `boundary` contract and fixed marker/table/fence counts match the assertions.
9. `observed_ragflow_chunks=false`, `ragflow_calls=0`,
   `writes_live_ragflow=false`, and `script_owned_llm_calls=0` are explicit.
10. JSON, Markdown, and redaction sidecars exist, and separate tool/prose scans have zero
    unresolved sensitive findings.
11. No network, private source, RAGFlow, MinerU, DeepDoc, LLM/RAGAS, Stage 8C, default
    change, Git mutation, commit, or push occurs.

A passing L0 replay closes only the independent repository replay rows in `docs/40`.
It does not close any open `docs/38` row and does not authorize L1, L2, L3, or L4.
