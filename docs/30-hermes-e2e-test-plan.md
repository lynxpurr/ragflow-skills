# Hermes E2E Test Plan For `ragflow-doc-to-md` And `ragflow-kb-build`

Status: archived reusable test plan; live retest closure is tracked in `docs/31-hermes-e2e-improvement-follow-up-plan.md`
Date: 2026-07-08
Scope: `ragflow-doc-to-md` -> `ragflow-kb-build`

## Objective

This reusable plan analyzes the public capabilities of `ragflow-doc-to-md` and
`ragflow-kb-build`, then turns them into an end-to-end test matrix and report template
that can be handed to a Hermes agent.

Disposition: keep this file under `docs/` as reusable cross-skill E2E guidance, but do
not cite it as evidence that a live run passed. The completed real-PDF follow-up retest,
closed evidence gap, and remaining improvement backlog are recorded in
`docs/31-hermes-e2e-improvement-follow-up-plan.md`.

The intended E2E boundary is:

```text
source documents
  -> ragflow-doc-to-md formal handoff
  -> ragflow-kb-build inspection and dry-run
  -> optional read-only service probes
  -> explicitly approved disposable RAGFlow KB build
  -> validation, health review, cleanup evidence
```

This plan is not evidence that a live Hermes run has already passed. It is a detailed
test plan plus a report template. Live RAGFlow mutation remains gated by explicit user
approval and reviewed credentials.

## Sources Reviewed

- `skills/ragflow-doc-to-md/SKILL.md`
- `skills/ragflow-doc-to-md/references/host-agent-setup.md`
- `skills/ragflow-doc-to-md/references/user-onboarding-prompt.md`
- `skills/ragflow-kb-build/SKILL.md`
- `skills/ragflow-kb-build/references/host-agent-setup.md`
- `skills/ragflow-kb-build/references/user-onboarding-prompt.md`
- `docs/03-development-plan.md`
- `docs/10-legacy-feature-gap-closure-design.md`
- `docs/15-field-trial-observation-plan.md`
- CLI help for `convert.py`, `build.py`, `validate.py`, `profile.py`, and `probe.py`
- Targeted offline calibration commands run with Markdown input and `/tmp` artifacts

## Offline Calibration Performed

These local checks were run without RAGFlow credentials, MinerU credentials, network
service calls, or live mutation.

| Check | Result | Key evidence |
| --- | --- | --- |
| `ragflow-doc-to-md pipeline` over a Markdown source | Pass | Generated `handoff_mode: formal_ingest`, `doc_manifest.json`, `quality_report.json`, `runtime_report.json`, `postprocess_report.json`, `chunk_profile_report.json`, rich sidecars, `formal_handoff_manifest.json`, and `ragflow_ingest_plan.yaml`. |
| `ragflow-doc-to-md adaptive --decision-only` | Pass | Generated `ragflow_document_features_v1`, `ragflow_pipeline_decision_v1`, and `ragflow_adaptive_pipeline_summary_v1`; no LLM calls and no live mutation. |
| `ragflow-doc-to-md backend probe --backend builtin` | Pass | Produced `ragflow_doc_backend_probe_report_v1` with `available: 1`. |
| `ragflow-kb-build inspect-handoff` | Pass | Recomputed handoff readiness as `ready`, rich sidecars complete, ingest plan stores no credentials. |
| `ragflow-kb-build asset-upload-plan` | Pass | Produced an offline-only asset/package plan, included sidecars, and made no RAGFlow calls. |
| `ragflow-kb-build --dry-run` | Pass | Consumed `doc_manifest.json` and `retrieval_hints.json`, returned `ok: true`, and recommended `activation-plan` after a real build. |
| `ragflow-kb-build profile.py lint` | Pass | Default profile lint returned `ok: true`; model-neutral template warning is informational. |

Observed nuance: `convert.py --help` lists most top-level commands but omits some custom
dispatch commands such as `package`, `postprocess`, and `compare-adaptive-summaries` from
its epilog, even though those commands do respond to `--help`. Hermes should test both
documented command examples and command-specific help output.

## Capability Analysis: `ragflow-doc-to-md`

### Main Responsibilities

`ragflow-doc-to-md` is the document-side pre-ingest skill. It creates normalized Markdown
handoffs and sidecars that `ragflow-kb-build` can inspect, dry-run, and upload.

Primary capabilities:

- Convert or pass through Markdown, text, HTML, Office/PDF-like inputs, and image inputs.
- Choose among backends: `builtin`, `pandoc`, `remote`, `mineru-cli`, `mineru`,
  `mineru-agent`, `mineru-fastapi`, `mineru-v4`, `mineru-platform`, `mineru-sync`, and
  legacy `mineru-local`.
- Run the formal `pipeline` path for KB pre-ingest. This wraps conversion, deterministic
  postprocess, rich sidecar packaging, retrieval hints, ingest readiness, and a non-secret
  RAGFlow ingest plan.
- Run `adaptive` to inspect sources and choose deterministic pipeline settings without
  LLM calls. `--decision-only` emits reports without conversion.
- Produce `doc_manifest.json`, `quality_report.json`, optional Markdown reports,
  `runtime_report.json`, and redaction sidecars.
- Produce rich formal handoff artifacts: `metadata.json`, `artifact_index.json`,
  `profile_suggestions.json`, `retrieval_hints.json`, `assistant_profile.json`,
  `assistant_test_plan.json`, `ingest_readiness_report.json`,
  `formal_handoff_manifest.json`, `package_readme.md`, and `ragflow_ingest_plan.yaml`.
- Apply deterministic Markdown cleanup through `postprocess` profiles:
  `none`, `safe`, `ocr`, `chunk-markers`, `chunk-markers-conservative`,
  `chunk-markers-dense`, and `chunk-markers-ragflux-like`.
- Plan or materialize long-document splits with `segment-plan` and `split`, including
  checkpoint/resume support for large split jobs.
- Probe and warm up conversion backends with `backend probe` and `backend warmup`.
- Compare old retained packages or adaptive summaries without live RAGFlow mutation.

### Formal Handoff Contract

For Hermes E2E, formal ingestion must use `pipeline`, not a quick thin preview. A passing
formal handoff should include:

- `doc_manifest.json`
- `quality_report.json`
- `runtime_report.json` when runtime telemetry is enabled
- `postprocess_report.json`
- `chunk_profile_report.json` for chunk-marker profiles
- `retrieval_hints.json`
- `ingest_readiness_report.json`
- `formal_handoff_manifest.json`
- `ragflow_ingest_plan.yaml`
- `package_readme.md`

`doc_manifest.json` should contain `handoff_mode: formal_ingest`. A plain `convert`
result may contain `handoff_mode: thin_preview`; Hermes must not use that as the formal KB
build input unless it intentionally tests quick preview behavior.

### MinerU-Specific Capability

Hermes must identify the MinerU protocol before choosing a backend:

- `mineru-fastapi`: MinerU 3.2+ FastAPI v2 using `/tasks`,
  `/tasks/{task_id}`, and `/tasks/{task_id}/result`.
- `mineru-v4` or `mineru-platform`: platform-compatible v4 APIs using
  `/api/v4/file-urls/batch`, presigned PUT upload, `/api/v4/extract-results/batch/{batch_id}`,
  and `full_zip_url` extraction.
- `mineru-cli`: local MinerU executable.
- `mineru` or `mineru-agent`: Agent API shape using `/parse/file`, signed upload, polling,
  and Markdown download.
- `mineru-sync`: synchronous multipart `/parse` compatibility.

For complex tables, `--table-quality high` should use a higher-accuracy FastAPI backend or
v4 `vlm` model unless the user explicitly configured another valid model. For formal KB
pre-ingest with images, `--mineru-asset-mode markdown_assets` should materialize local
image assets under the handoff.

### Safety Boundaries

- No RAGFlow mutation is performed by `ragflow-doc-to-md`.
- `adaptive` and comparison commands do not call LLMs.
- Backend network checks are opt-in through `--network-check` or warmup commands.
- Redaction reports are available for generated report surfaces.
- `quality_gate.status: BLOCKED` is a downstream build gate unless the user explicitly
  allows it in `ragflow-kb-build`.

## Capability Analysis: `ragflow-kb-build`

### Main Responsibilities

`ragflow-kb-build` owns Markdown handoff inspection, RAGFlow KB mutation, parse handling,
validation, advisory metadata, benchmarks, topology/activation reports, and cleanup.

Primary capabilities:

- Consume a Markdown file/directory through `--input` or a `doc_manifest.json` through
  `--doc-manifest`.
- Apply chunk profile templates and lint/recommend/compare profiles through `profile.py`.
- Run `--dry-run` to validate local inputs, profile, metadata, retrieval hints, batching,
  table preflight, and post-build recommendations without touching RAGFlow.
- Live build a RAGFlow dataset, upload Markdown, trigger parse, wait for parse completion,
  and emit `kb_manifest.json`.
- Use `--batch-size`, `--checkpoint`, and `--resume` for bounded or interrupted live
  Markdown builds.
- Block `BLOCKED` handoffs by default; require `--allow-blocked` for explicit override.
- Inspect formal handoffs through `inspect-handoff`.
- Produce non-live `asset-upload-plan` packages for Markdown plus local image assets.
- Run artifact `consistency-check` across retrieval hints, upload plan, chunk profile, and
  KB manifest evidence.
- Probe RAGFlow read-only compatibility with `probe.py`.
- Probe model-provider readiness with `model-providers probe`.
- Generate and lint metadata/tagset artifacts; create no-LLM request/review boundaries for
  metadata suggestions.
- Import, sample, preflight, summarize, gate, trend, delta, and suggest benchmark
  artifacts.
- Generate deterministic grounded QA, validate source evidence, and map evidence spans to
  chunk snapshots.
- Create topology advice and split plans without mutation.
- Create post-build `activation-plan` reports without editing routing config.
- Create parse, refresh, and health reports from local manifests and optional read-only
  observed-state sidecars.
- Plan profile optimization experiments offline; live optimization requires exact
  confirmation and disposable KB cleanup.
- Append new Markdown and cleanup datasets through separate scripts, with preview-first
  behavior and exact live confirmations.
- Validate live KBs at `smoke`, `regression`, or `benchmark` levels through `validate.py`.

### Live Mutation Contract

Live build behavior is intentionally explicit:

- `build.py --dry-run` should always precede mutation.
- Live build needs reviewed RAGFlow credentials from config/env/flags.
- Cleanup requires `--execute`, exact dataset ID, and matching KB name.
- Optimization live execution requires `--execute`, `--confirm-live-build`,
  `--confirm-kb-name`, and `--confirm-run-id`.
- Disposable KBs should be named with a timestamped, reviewable prefix.

### Validation And Reporting Contract

Expected key artifacts in an E2E run:

- `kb_manifest.json`
- `validation_smoke.json` and optional Markdown report
- optional `refresh_report.json`
- optional `parse_report.json`
- optional `activation_plan.json`
- optional `health_report.json`
- cleanup plan/execution reports for live disposable KBs
- matching redaction sidecars for reports that may contain paths/endpoints

### Safety Boundaries

- Offline reports must not call RAGFlow unless explicitly documented as read-only.
- Live mutation commands need explicit flags and reviewed credentials.
- Cleanup commands need exact confirmations.
- Metadata suggestions, QA suggestions, and LLM-adjacent workflows are request/review
  boundaries, not script-owned model calls.
- Public summaries must not include API keys, secret fragments, private endpoints, private
  KB names, proprietary document titles, full home paths, or raw private chunk text.

## Hermes E2E Test Strategy

Use three layers. Hermes should stop at the highest approved layer and report skipped
layers with concrete reasons.

| Layer | Requires credentials | Mutates RAGFlow | Purpose |
| --- | --- | --- | --- |
| L0 Offline smoke and package review | No | No | Prove both skills run, produce formal handoffs, and dry-run the build path. |
| L1 Read-only service readiness | RAGFlow/MinerU config if available | No | Probe backend/service compatibility and model-provider readiness without upload/delete. |
| L2 Disposable live E2E | RAGFlow config and explicit user approval | Yes, disposable only | Build, parse, validate, inspect, and clean up a temporary KB. |
| L3 Optional high-fidelity MinerU document E2E | MinerU config and suitable source docs | No for conversion; yes only if followed by L2 | Verify complex PDF/Office/image conversion, table quality, and asset handoff. |

## Preconditions For Hermes

Hermes should prepare:

- Skill root containing `ragflow-doc-to-md` and `ragflow-kb-build`.
- Private run root, for example `/tmp/ragflow-skills-hermes-e2e-YYYYMMDD-HHMM`.
- Private config path, preferably `~/.hermes/ragflow/config.local.yaml`.
- Environment variables or secret-store references for `RAGFLOW_API_KEY` and
  `MINERU_API_KEY` when needed.
- A disposable KB name of the form `kb:ragflow-skills-e2e-YYYYMMDD-HHMM`.
- A final report path under the private run root, for example
  `reports/hermes_e2e_report.md`.

Hermes must not write real API keys into skill folders, git repositories, public docs, or
release artifacts. Reports should use sanitized URLs, secret names, or `<redacted>`.

## Test Cases

### TC-00 Skill Discovery And Help Surface

Purpose: confirm Hermes can locate and invoke both skills.

Commands:

```bash
python ragflow-doc-to-md/scripts/convert.py --help
python ragflow-doc-to-md/scripts/convert.py pipeline --help
python ragflow-doc-to-md/scripts/convert.py package --help
python ragflow-doc-to-md/scripts/convert.py postprocess --help
python ragflow-doc-to-md/scripts/convert.py backend probe --help

python ragflow-kb-build/scripts/build.py --help
python ragflow-kb-build/scripts/build.py inspect-handoff --help
python ragflow-kb-build/scripts/build.py asset-upload-plan --help
python ragflow-kb-build/scripts/build.py metadata --help
python ragflow-kb-build/scripts/build.py benchmark --help
python ragflow-kb-build/scripts/validate.py --help
python ragflow-kb-build/scripts/profile.py --help
python ragflow-kb-build/scripts/probe.py --help
```

Pass criteria:

- Each command exits 0.
- Command-specific help is available for `pipeline`, `package`, `postprocess`,
  `inspect-handoff`, `asset-upload-plan`, `metadata`, `benchmark`, `validate.py`,
  `profile.py`, and `probe.py`.
- Hermes records any mismatch between top-level help epilog and command-specific help as
  a documentation/discoverability note, not an E2E failure if the command works.

### TC-01 No-Network Formal Markdown Handoff

Purpose: prove formal handoff generation works without converters, credentials, or
RAGFlow.

Commands:

```bash
RUN=/tmp/ragflow-skills-hermes-e2e-YYYYMMDD-HHMM
mkdir -p "$RUN/input" "$RUN/reports"
cat > "$RUN/input/sample.md" <<'EOF'
# Hermes RAGFlow Smoke

The Hermes smoke marker is RAGFLOW-HERMES-SMOKE-20260708.

| Field | Value |
| --- | --- |
| owner | Hermes |
| mode | offline |

## Expected Retrieval

The disposable KB should contain the smoke marker and this table.
EOF

python ragflow-doc-to-md/scripts/convert.py pipeline \
  --input "$RUN/input" \
  --output "$RUN/handoff" \
  --mode passthrough \
  --postprocess-profile chunk-markers-dense \
  --runtime-report-md runtime_report.md \
  --redaction-report "$RUN/reports/doc_pipeline.redaction.json" \
  --json
```

Pass criteria:

- Stdout reports `ok: true`.
- `doc_manifest.json` exists and reports `handoff_mode: formal_ingest`.
- `quality_gate.status` is `PASS` or `PASS_WITH_REVIEW`.
- Handoff contains `quality_report.json`, `runtime_report.json`,
  `postprocess_report.json`, `chunk_profile_report.json`, `retrieval_hints.json`,
  `ingest_readiness_report.json`, `formal_handoff_manifest.json`,
  `ragflow_ingest_plan.yaml`, and `package_readme.md`.
- `ragflow_ingest_plan.yaml` does not contain RAGFlow endpoint values or API keys.

### TC-02 Adaptive Decision-Only Review

Purpose: prove source inspection and deterministic pipeline decision reports work without
conversion or live mutation.

Command:

```bash
python ragflow-doc-to-md/scripts/convert.py adaptive \
  --input "$RUN/input" \
  --output "$RUN/adaptive-decision" \
  --decision-only \
  --report-json "$RUN/reports/adaptive_summary.json" \
  --redaction-report "$RUN/reports/adaptive_summary.redaction.json" \
  --json
```

Pass criteria:

- Reports include schemas `ragflow_document_features_v1`,
  `ragflow_pipeline_decision_v1`, and `ragflow_adaptive_pipeline_summary_v1`.
- `script_owned_llm_calls` is `0`.
- `live_mutation_enabled` is `false`.
- Review commands point to `inspect-handoff`, `asset-upload-plan`, and build dry-run.

### TC-03 Backend Probe Without Network

Purpose: prove backend probe reporting and redaction sidecars work in offline mode.

Command:

```bash
python ragflow-doc-to-md/scripts/convert.py backend probe \
  --backend builtin \
  --report-json "$RUN/reports/backend_probe.json" \
  --report-md "$RUN/reports/backend_probe.md" \
  --redaction-report "$RUN/reports/backend_probe.redaction.json" \
  --json
```

Pass criteria:

- Report schema is `ragflow_doc_backend_probe_report_v1`.
- Selected backend is `builtin`.
- Status is `available`.
- No network check is attempted.

### TC-04 Handoff Inspection And Asset Upload Plan

Purpose: prove `ragflow-kb-build` can consume formal handoffs before any live build.

Commands:

```bash
python ragflow-kb-build/scripts/build.py inspect-handoff \
  --handoff "$RUN/handoff" \
  --report-json "$RUN/reports/handoff_inspection.json" \
  --report-md "$RUN/reports/handoff_inspection.md" \
  --redaction-report "$RUN/reports/handoff_inspection.redaction.json" \
  --json

python ragflow-kb-build/scripts/build.py asset-upload-plan \
  --doc-manifest "$RUN/handoff/doc_manifest.json" \
  --report-json "$RUN/reports/asset_upload_plan.json" \
  --report-md "$RUN/reports/asset_upload_plan.md" \
  --redaction-report "$RUN/reports/asset_upload_plan.redaction.json" \
  --package-zip "$RUN/reports/asset_upload_package.zip" \
  --json
```

Pass criteria:

- Inspection report schema is `ragflow_handoff_inspection_v1`.
- Ingestion readiness is `ready` or `ready_with_review`.
- Rich and pipeline sidecars are complete.
- Missing image count is `0` for the Markdown-only fixture.
- Asset upload plan schema is `ragflow_kb_asset_upload_plan_v2`.
- `offline_only` is `true`, `live_upload_enabled` is `false`, and `ragflow_calls` is `0`.

### TC-05 Build Dry-Run

Purpose: prove build input validation and profile handling without RAGFlow mutation.

Command:

```bash
python ragflow-kb-build/scripts/build.py \
  --doc-manifest "$RUN/handoff/doc_manifest.json" \
  --retrieval-hints "$RUN/handoff/retrieval_hints.json" \
  --kb-name "kb:ragflow-skills-e2e-dry-run" \
  --profile ragflow-kb-build/templates/default-en-768.json \
  --dry-run \
  --json > "$RUN/reports/kb_build_dry_run.json"
```

Pass criteria:

- JSON reports `ok: true` and `dry_run: true`.
- It lists the planned Markdown documents.
- It includes retrieval hint summary.
- It does not write `kb_manifest.json`.
- It recommends `activation-plan` for post-build review.

### TC-06 Profile, Metadata, Tagset, And Benchmark Offline Checks

Purpose: exercise governance commands that commonly precede a serious live build.

Commands:

```bash
python ragflow-kb-build/scripts/profile.py lint \
  --profile ragflow-kb-build/templates/default-en-768.json \
  --report-md "$RUN/reports/profile_lint.md"

python ragflow-kb-build/scripts/build.py metadata generate-template \
  --doc-manifest "$RUN/handoff/doc_manifest.json" \
  --output "$RUN/reports/metadata.template.json"

python ragflow-kb-build/scripts/build.py metadata lint \
  --metadata "$RUN/reports/metadata.template.json" \
  --report-md "$RUN/reports/metadata_lint.md"

python ragflow-kb-build/scripts/build.py tagset generate-template \
  --output "$RUN/reports/tagset.template.json"

python ragflow-kb-build/scripts/build.py tagset lint \
  --tagset "$RUN/reports/tagset.template.json" \
  --report-md "$RUN/reports/tagset_lint.md"

python ragflow-kb-build/scripts/build.py benchmark import \
  --queries ragflow-kb-build/templates/benchmark-queries.example.json \
  --qrels ragflow-kb-build/templates/qrels.example.json \
  --output "$RUN/reports/benchmark"

python ragflow-kb-build/scripts/build.py benchmark preflight \
  --manifest "$RUN/reports/benchmark/manifest.json" \
  --gate-config ragflow-kb-build/templates/benchmark-gate.example.json \
  --report-md "$RUN/reports/benchmark_preflight.md"
```

Pass criteria:

- Profile lint exits 0; model-neutral warnings are informational.
- Metadata and tagset commands emit JSON templates and Markdown lint reports.
- Benchmark import emits `manifest.json`.
- Benchmark preflight exits 0 or records only expected fixture-level warnings.

### TC-07 Optional Read-Only Service Probes

Purpose: verify configured services before mutation.

Run only if relevant config is present.

Commands:

```bash
python ragflow-kb-build/scripts/probe.py \
  --config "$RAGFLOW_CONFIG" \
  --report-json "$RUN/reports/ragflow_probe.json" \
  --report-md "$RUN/reports/ragflow_probe.md" \
  --redaction-report "$RUN/reports/ragflow_probe.redaction.json" \
  --json

python ragflow-kb-build/scripts/build.py model-providers probe \
  --config "$RAGFLOW_CONFIG" \
  --embedding-model bge-m3 \
  --report-json "$RUN/reports/model_provider_probe.json" \
  --report-md "$RUN/reports/model_provider_probe.md" \
  --redaction-report "$RUN/reports/model_provider_probe.redaction.json" \
  --json

python ragflow-doc-to-md/scripts/convert.py backend probe \
  --config "$RAGFLOW_CONFIG" \
  --backend auto \
  --network-check \
  --report-json "$RUN/reports/doc_backend_probe_network.json" \
  --report-md "$RUN/reports/doc_backend_probe_network.md" \
  --redaction-report "$RUN/reports/doc_backend_probe_network.redaction.json" \
  --json
```

Pass criteria:

- RAGFlow probe reports API compatibility or a clear read-only failure class.
- Model-provider probe reports expected provider/model readiness or a clear warning.
- MinerU/backend probe classifies the selected backend as `available`, `missing`,
  `wrong_protocol`, `timeout`, or `not_configured`.
- Reports and redaction sidecars do not reveal API keys or private endpoint details.

### TC-08 Optional MinerU Formal Conversion E2E

Purpose: verify real converter behavior for PDF, Office, or image inputs.

Run only when the user provides a safe source file and MinerU configuration is complete.

FastAPI v2 example:

```bash
python ragflow-doc-to-md/scripts/convert.py pipeline \
  --config "$RAGFLOW_CONFIG" \
  --input "$RUN/source-docs" \
  --output "$RUN/mineru-handoff" \
  --backend mineru-fastapi \
  --mineru-asset-mode markdown_assets \
  --table-quality auto \
  --postprocess-profile chunk-markers-dense \
  --runtime-report-md runtime_report.md \
  --redaction-report "$RUN/reports/mineru_pipeline.redaction.json" \
  --json
```

MinerU v4 example:

```bash
python ragflow-doc-to-md/scripts/convert.py pipeline \
  --config "$RAGFLOW_CONFIG" \
  --input "$RUN/source-docs" \
  --output "$RUN/mineru-v4-handoff" \
  --backend mineru-v4 \
  --mineru-asset-mode markdown_assets \
  --table-quality auto \
  --postprocess-profile chunk-markers-dense \
  --runtime-report-md runtime_report.md \
  --redaction-report "$RUN/reports/mineru_v4_pipeline.redaction.json" \
  --json
```

Pass criteria:

- Handoff mode is `formal_ingest`.
- Markdown files are produced.
- For image/table-rich inputs, local assets and retrieval hints are present.
- `quality_gate.status` is not `BLOCKED` unless the user intentionally accepts the risk.
- Runtime report includes converter attempt and stage timing evidence.
- `inspect-handoff` and build dry-run pass on the resulting handoff.

Skip criteria:

- MinerU protocol cannot be identified.
- Required endpoint/API key/secret reference is missing.
- The user does not approve running a converter against the source document.

### TC-09 Disposable Live KB Build

Purpose: verify the real `doc-to-md` -> `kb-build` path against RAGFlow.

Run only after TC-01 through TC-07 are acceptable and the user explicitly approves
creating a disposable KB.

Commands:

```bash
KB_NAME="kb:ragflow-skills-e2e-YYYYMMDD-HHMM"

python ragflow-kb-build/scripts/build.py \
  --config "$RAGFLOW_CONFIG" \
  --doc-manifest "$RUN/handoff/doc_manifest.json" \
  --retrieval-hints "$RUN/handoff/retrieval_hints.json" \
  --kb-name "$KB_NAME" \
  --profile ragflow-kb-build/templates/default-en-768.json \
  --output "$RUN/reports/kb_manifest.json" \
  --json

python ragflow-kb-build/scripts/validate.py \
  --config "$RAGFLOW_CONFIG" \
  --kb-manifest "$RUN/reports/kb_manifest.json" \
  --level smoke \
  --query "What is the Hermes smoke marker?" \
  --report-json "$RUN/reports/validation_smoke.json" \
  --report-md "$RUN/reports/validation_smoke.md" \
  --redaction-report "$RUN/reports/validation_smoke.redaction.json"
```

Pass criteria:

- Dataset/KB is created with the disposable name.
- Upload count matches the handoff Markdown document count.
- Parse reaches a completed state unless the user intentionally passed `--no-wait`.
- `kb_manifest.json` exists and records dataset ID/name plus document IDs.
- Smoke validation exits 0 and returns evidence for the smoke marker.
- Runtime metrics are present when live upload/parse stages run.

### TC-10 Post-Build Parse, Activation, And Health Reports

Purpose: verify the post-build review surfaces that decide whether a KB is usable.

Commands:

```bash
python ragflow-kb-build/scripts/build.py refresh-report \
  --config "$RAGFLOW_CONFIG" \
  --kb-manifest "$RUN/reports/kb_manifest.json" \
  --report-json "$RUN/reports/kb_refresh_report.json" \
  --report-md "$RUN/reports/kb_refresh_report.md" \
  --redaction-report "$RUN/reports/kb_refresh_report.redaction.json" \
  --json

python ragflow-kb-build/scripts/build.py parse-report \
  --kb-manifest "$RUN/reports/kb_manifest.json" \
  --observed-state "$RUN/reports/kb_refresh_report.json" \
  --profile ragflow-kb-build/templates/default-en-768.json \
  --report-json "$RUN/reports/parse_report.json" \
  --report-md "$RUN/reports/parse_report.md" \
  --redaction-report "$RUN/reports/parse_report.redaction.json" \
  --json

python ragflow-kb-build/scripts/build.py activation-plan \
  --kb-manifest "$RUN/reports/kb_manifest.json" \
  --doc-manifest "$RUN/handoff/doc_manifest.json" \
  --retrieval-hints "$RUN/handoff/retrieval_hints.json" \
  --ingest-plan "$RUN/handoff/ragflow_ingest_plan.yaml" \
  --profile ragflow-kb-build/templates/default-en-768.json \
  --output "$RUN/reports/kb_activation_plan.json" \
  --report-md "$RUN/reports/kb_activation_plan.md" \
  --redaction-report "$RUN/reports/kb_activation_plan.redaction.json" \
  --json

python ragflow-kb-build/scripts/build.py health-report \
  --kb-manifest "$RUN/reports/kb_manifest.json" \
  --parse-report "$RUN/reports/parse_report.json" \
  --observed-state "$RUN/reports/kb_refresh_report.json" \
  --activation-plan "$RUN/reports/kb_activation_plan.json" \
  --report-json "$RUN/reports/kb_health_report.json" \
  --report-md "$RUN/reports/kb_health_report.md" \
  --redaction-report "$RUN/reports/kb_health_report.redaction.json" \
  --json
```

Pass criteria:

- Refresh report reads current document status without upload/delete/repair.
- Parse report shows completed or clearly explained parse states.
- Activation plan is advisory-only and identifies route/profile/readiness risks.
- Health report aggregates parse, observed state, activation readiness, and model risks.
- Reports are sanitized.

### TC-11 Cleanup And Read-Back Verification

Purpose: ensure the disposable KB is not left behind.

Commands:

```bash
python ragflow-kb-build/scripts/cleanup.py \
  --kb-manifest "$RUN/reports/kb_manifest.json" \
  --output "$RUN/reports/cleanup_plan.json"

python ragflow-kb-build/scripts/cleanup.py \
  --config "$RAGFLOW_CONFIG" \
  --kb-manifest "$RUN/reports/kb_manifest.json" \
  --execute \
  --confirm-dataset-id "<dataset-id-from-kb-manifest>" \
  --confirm-kb-name "$KB_NAME" \
  --output "$RUN/reports/cleanup_execution_report.json"

python ragflow-kb-build/scripts/probe.py \
  --config "$RAGFLOW_CONFIG" \
  --report-json "$RUN/reports/ragflow_probe_after_cleanup.json" \
  --report-md "$RUN/reports/ragflow_probe_after_cleanup.md" \
  --redaction-report "$RUN/reports/ragflow_probe_after_cleanup.redaction.json" \
  --json
```

Pass criteria:

- Cleanup plan identifies the exact disposable dataset.
- Cleanup execution requires exact dataset ID and KB name.
- Delete response is successful.
- Post-cleanup read-back or probe evidence shows the disposable KB is absent, or Hermes
  reports the exact remaining dataset ID/name for manual cleanup.

### TC-12 Negative Safety Checks

Purpose: verify unsafe flows fail closed.

Recommended checks:

- Try `build.py --doc-manifest <blocked-manifest> ... --dry-run` and confirm blocked
  quality is reported.
- Confirm a live build is not run as part of any dry-run command.
- Confirm cleanup without `--execute` only writes a plan.
- Confirm cleanup with a wrong `--confirm-dataset-id` or wrong `--confirm-kb-name` fails.
- Confirm optimization live execution without exact confirmation fails.
- Confirm generated reports and redaction sidecars do not contain API keys, token
  fragments, full private config paths, or private endpoints.

Pass criteria:

- Unsafe commands refuse to mutate.
- Reports explain the missing confirmation or blocked gate.
- No secret material is printed.

## Hermes Task Prompt

The following prompt can be sent to a Hermes agent. It intentionally focuses on
`ragflow-doc-to-md` and `ragflow-kb-build`; query-skill testing is optional and outside
this plan's scope.

```text
请对当前 workspace 中的 RAGFlow public skills 执行端到端测试，范围只包括：
- ragflow-doc-to-md
- ragflow-kb-build

请先读取：
- ragflow-doc-to-md/SKILL.md
- ragflow-doc-to-md/references/host-agent-setup.md
- ragflow-kb-build/SKILL.md
- ragflow-kb-build/references/host-agent-setup.md
- docs/30-hermes-e2e-test-plan.md

目标：
1. 验证 ragflow-doc-to-md 能生成 formal_ingest handoff。
2. 验证 ragflow-kb-build 能 inspect handoff、asset-upload-plan、dry-run。
3. 在有配置但没有 live 批准时，只执行 read-only probe，不创建 KB。
4. 只有在我明确批准后，才创建一次性 RAGFlow KB 并执行 live build、validate、refresh、parse-report、activation-plan、health-report、cleanup。
5. 最后保存中文详细报告到本次运行目录，例如 /tmp/ragflow-skills-hermes-e2e-YYYYMMDD-HHMM/reports/hermes_e2e_report.md。

安全要求：
- 不要把真实 API key 写入 skill 目录、git 仓库、项目文档、release artifacts 或最终报告。
- 不要打印 API key 前缀、后缀、局部片段或看起来像 token 的值。
- 配置优先使用 ~/.hermes/ragflow/config.local.yaml 和环境变量占位符。
- RAGFlow 和 MinerU 是外部服务，不要尝试从 skill 内启动或修复服务。
- 每个可能包含路径、endpoint 或诊断信息的报告都尽量写 redaction sidecar。
- live KB 必须使用一次性名称：kb:ragflow-skills-e2e-YYYYMMDD-HHMM。
- live cleanup 必须使用 kb_manifest.json 中的 dataset id 和完全匹配的 KB 名称。

请按 docs/30-hermes-e2e-test-plan.md 中的测试用例执行：
- TC-00 到 TC-06 必跑，必须不联网、不接触 RAGFlow/MinerU。
- TC-07 只在配置存在时执行，只读。
- TC-08 只在我提供 PDF/Office/图片样本和 MinerU 配置时执行。
- TC-09 到 TC-11 只有我明确批准 live disposable KB 后执行。
- TC-12 选择至少两条 negative safety check 执行，不能造成 live 破坏。

最终报告请包含：
- 运行时间、agent、工作目录的脱敏描述。
- 使用的 skill 相对路径和脚本版本/帮助面检查结果。
- 配置来源；endpoint 只写脱敏值，API key 一律不写。
- 每个测试用例的 pass/fail/skip、命令摘要、artifact 路径、关键 JSON 字段、失败原因。
- live 阶段如果执行：KB 名称、dataset id、上传文档数、parse 状态、chunk 数、validate smoke 结果、refresh/parse/activation/health 摘要、cleanup 结果。
- live 阶段如果跳过：明确写明是因为缺配置、缺样本文档、未批准 mutation，还是服务不可达。
- redaction 检查结论。
- 是否可以把当前配置视为可用。
- 残余风险和下一步建议。
```

## Hermes Final Report Template

Hermes should save a final report with this structure:

```markdown
# Hermes RAGFlow E2E Report

Date:
Agent:
Run root:
Scope: ragflow-doc-to-md -> ragflow-kb-build

## Summary

Overall status:
Offline status:
Read-only service status:
Live disposable KB status:
Cleanup status:
Configuration usable:

## Environment

Skill root:
Config source:
RAGFlow endpoint: <redacted or not configured>
MinerU endpoint: <redacted or not configured>
Secrets: env/secret-store placeholders only

## Results

| Case | Status | Evidence | Notes |
| --- | --- | --- | --- |
| TC-00 | pass/fail/skip | | |
| TC-01 | pass/fail/skip | | |
| TC-02 | pass/fail/skip | | |
| TC-03 | pass/fail/skip | | |
| TC-04 | pass/fail/skip | | |
| TC-05 | pass/fail/skip | | |
| TC-06 | pass/fail/skip | | |
| TC-07 | pass/fail/skip | | |
| TC-08 | pass/fail/skip | | |
| TC-09 | pass/fail/skip | | |
| TC-10 | pass/fail/skip | | |
| TC-11 | pass/fail/skip | | |
| TC-12 | pass/fail/skip | | |

## Key Artifacts

- Handoff:
- Inspection:
- Asset upload plan:
- Dry-run:
- RAGFlow probe:
- Backend probe:
- KB manifest:
- Validation:
- Refresh:
- Parse:
- Activation:
- Health:
- Cleanup:
- Redaction sidecars:

## Live KB Evidence

KB name:
Dataset id:
Uploaded documents:
Parse state:
Chunk count:
Validation smoke:
Cleanup result:

## Redaction Review

API keys exposed: no/yes
Secret fragments exposed: no/yes
Private endpoints exposed: no/yes
Full home paths exposed: no/yes
Private document titles exposed: no/yes

## Failures Or Skips

- Case:
  Reason:
  Required user action:

## Decision

Can use current config:
Can run formal doc-to-md:
Can run KB dry-run:
Can run live KB build:
Retain artifacts:
Next recommended action:
```

## Acceptance Criteria

The Hermes run is considered successful for this scope when:

1. TC-00 through TC-06 pass.
2. If RAGFlow config is available, TC-07 RAGFlow probe succeeds or reports a clear
   read-only compatibility failure.
3. If MinerU conversion is in scope, TC-08 produces a formal handoff or reports a clear
   protocol/config skip.
4. If live mutation is approved, TC-09 through TC-11 build, validate, report, and clean up
   a disposable KB.
5. TC-12 confirms at least two safety gates fail closed.
6. The final Hermes report contains no secrets, private endpoint values, private KB names
   beyond the disposable test name, full home paths, or raw private chunk text.

## Recommended Default Verdict Rules

- `offline_pass`: TC-00 through TC-06 pass.
- `read_only_ready`: `offline_pass` plus read-only RAGFlow/MinerU probes pass or are not
  required.
- `live_ready`: `read_only_ready` plus TC-09 through TC-11 pass after explicit approval.
- `converter_ready`: TC-08 passes for the intended MinerU protocol and source type.
- `configuration_usable`: `offline_pass` plus either `read_only_ready` or a documented
  reason read-only service checks were skipped.
- `needs_user_action`: missing endpoint, missing secret reference, unknown MinerU
  protocol, live approval not granted, service unavailable, parse timeout, validation
  failure, or cleanup not verified.

## Open Risks To Watch During Hermes Execution

- Top-level CLI help does not list every custom-dispatched `convert.py` command even
  though command-specific help works.
- Live parse can pass upload but stall or produce zero chunks; TC-10 is required to catch
  this.
- `default-en-768.json` is model-neutral; use model-specific profiles or
  `--expected-embedding-model` when testing a concrete deployment.
- Complex table documents need `pipeline`, `markdown_assets`, `chunk-markers-dense`, and
  table-quality review; quick `convert` output is not enough for formal ingest.
- Redacted report paths are suitable for sharing, but raw run roots may still contain
  private artifacts and should stay under Hermes/private storage.
