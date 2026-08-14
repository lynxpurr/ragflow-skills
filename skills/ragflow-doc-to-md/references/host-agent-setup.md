# Host Agent Setup

Use this reference when Hermes, OpenClaw, Claude Code, opencode, or another controllable CLI agent needs to configure and validate the public RAGFlow skills on behalf of a user.

For a copy-paste prompt that end users can give to their own host agent, use `user-onboarding-prompt.md`.

## Agent Responsibilities

- Prefer host-agent config and environment variables over asking the user to run manual setup commands.
- Never write real API keys into a skill folder, repository file, release artifact, prompt transcript, or shared project document.
- Never print key prefixes, suffixes, partial token values, or inline comments that look like real secrets. Use `${ENV_VAR}`, secret names, or redacted placeholders in reports.
- Use `templates/ragflow-config.example.yaml` as the config template.
- Put real config in a stable host-agent path and point scripts to it with `RAGFLOW_CONFIG` or `--config`.
- Treat RAGFlow and MinerU as external services. Do not start or supervise them from these skills.
- Distinguish MinerU execution modes before testing conversion. The `mineru-fastapi` backend supports MinerU 3.2+ FastAPI protocol v2: submit files to `/tasks`, poll `/tasks/{task_id}`, then read Markdown from `/tasks/{task_id}/result`. The `mineru-v4` and `mineru-platform` backends support MinerU v4 platform-compatible APIs, including the public `mineru.net` API: request upload URLs at `/api/v4/file-urls/batch`, upload files with `PUT`, poll `/api/v4/extract-results/batch/{batch_id}`, then extract Markdown from `full_zip_url`. The `mineru-cli` backend runs a local MinerU binary. The `mineru` and `mineru-agent` backends support the MinerU Agent API shape: create a parse task with `/parse/file`, upload to the returned URL, poll `/parse/{task_id}`, then download Markdown. The `mineru-sync` and `mineru-local` backends are legacy compatibility paths for synchronous multipart `/parse` services.
- For a remote MinerU FastAPI service, set `doc_to_md.backend: mineru-fastapi` explicitly. For a MinerU v4 platform-compatible API, set `doc_to_md.backend: mineru-v4` or `mineru-platform` explicitly. Use `auto` only when local `mineru-cli` discovery is intentionally allowed. Do not set `doc_to_md.backend: mineru` for a FastAPI v2, v4 platform-compatible, or synchronous multipart MinerU service.
- Do not patch `scripts/_vendor` inside release artifacts. New backend support must be implemented in the source runtime package and then re-vendored by the release builder.
- Keep all E2E artifacts in a temporary or user-approved workspace, and report paths at the end.

## Config Locations

Recommended real config paths:

- Hermes: `~/.hermes/ragflow/config.local.yaml`
- OpenClaw: `~/.config/openclaw/ragflow/config.local.yaml`, `/etc/openclaw/ragflow/config.local.yaml`, `/var/lib/openclaw/ragflow/config.local.yaml`, or a mounted secret/config path
- Claude Code and opencode: `~/.config/ragflow-skills/config.local.yaml`
- Project fallback: `.ragflow/config.local.yaml` only when the working directory is stable and private

The config file may contain `${ENV_VAR}` placeholders. Put secret values in the host environment, secret store, or mounted secret path.

Config precedence for MinerU endpoints is: `--mineru-base-url` overrides `MINERU_BASE_URL`, which overrides `mineru.base_url` in the config file. v4 model settings follow the same order: `--mineru-v4-model-version`, `MINERU_V4_MODEL_VERSION`, then `mineru.v4_model_version`.

## Sanitized Reports And Redaction Sidecars

Write generated reports for a run under one private workspace, for example `/tmp/ragflow-skills-e2e/reports` or a user-approved project artifact directory. Keep sanitized `--report-json`, `--report-md`, and matching `--redaction-report` sidecars together so later reviewers can verify what was redacted without seeing raw endpoint, key, home-path, or config-path values.

Share sanitized reports and redaction sidecars when useful. Do not paste unsanitized reports, local config paths, private service URLs, key fragments, or raw host logs into shared transcripts. Redaction sidecars should contain schema, counts, and findings only; if a sidecar contains raw secret material, treat it as private and regenerate the report through the skill command.

Temporary report directories can be removed after the user has collected the sanitized artifacts they want to keep. Keep durable copies only in private project storage or a host-agent artifact store, not inside released skill folders.

## Minimal Config

Create the host config from `templates/ragflow-config.example.yaml` if it does not exist. Keep placeholders for secrets:

```yaml
ragflow:
  base_url: https://ragflow.example.com
  api_key: ${RAGFLOW_API_KEY}
  timeout: 60
  verify_ssl: true

doc_to_md:
  # Remote Hermes-agent deployments should pin the intended converter.
  # Use mineru-fastapi for MinerU 3.2+ protocol-v2 async services.
  # Use mineru-v4 for MinerU v4 platform-compatible precision APIs.
  # Use auto only when local CLI discovery is intentionally allowed.
  backend: mineru-fastapi

mineru:
  # Optional local CLI example: /opt/mineru/bin/mineru
  cli_path: ${MINERU_CLI_PATH}
  cli_backend: pipeline
  # FastAPI v2 async example: https://mineru.example.internal
  # MinerU v4 platform-compatible example: https://mineru.net or https://mineru.net/api/v4
  # Agent API example: https://mineru.net/api/v1/agent
  # Legacy sync multipart example: http://mineru.example.internal:8777/api/v1
  base_url: https://mineru.example.internal
  api_key: ${MINERU_API_KEY}
  timeout: 1800
  poll_interval: 3
  verify_ssl: true
  asset_mode: markdown_assets
  v4_model_version: pipeline
  v4_result_mode: full_zip
  v4_data_id_prefix:
  language: ch
  page_range:
  enable_table: true
  is_ocr: false
  enable_formula: true
```

Then export:

```bash
export RAGFLOW_CONFIG=$HOME/.hermes/ragflow/config.local.yaml
```

Use the equivalent stable path for non-Hermes hosts.

## Preflight Checks

Before live E2E:

1. Confirm the four public skill folders are available in the same workspace:
   - `ragflow-doc-to-md`
   - `ragflow-canonical-review`
   - `ragflow-kb-build`
   - `ragflow-query`
2. Confirm `RAGFLOW_CONFIG` points to a readable config file, or choose the host config path above.
3. Confirm RAGFlow settings are present through config or environment:
   - `RAGFLOW_BASE_URL`
   - `RAGFLOW_API_KEY`
4. Confirm MinerU settings only when raw PDF/Office/image conversion is in scope:
   - local CLI path through `MINERU_CLI_PATH`, `mineru.cli_path`, or `mineru` on `PATH`; or
   - `MINERU_BASE_URL`
   - `MINERU_API_KEY`
   - whether the service implements MinerU FastAPI v2, MinerU v4 platform-compatible protocol, MinerU Agent API, or synchronous multipart `/parse`
   - **Note on CLI discovery**: `command -v mineru` and `pip list` both fail when MinerU is installed inside an isolated virtual environment (e.g. `~/tools/mineru/bin/mineru`). Do not report "not found" from these checks alone. When `MINERU_CLI_PATH` is unset and `command -v mineru` returns nothing, do a broad filesystem search (`find ~/tools ~/.local/bin ~/bin /opt -name 'mineru' -type f`) before concluding it is absent. This is a common false negative in real host-agent environments.
5. Use LAN, VPN, or HTTPS endpoints by default. Use localhost only for an intentional single-machine debug setup.

If required values are missing, ask the user only for the missing endpoint/key names. Do not ask them to manually edit every command.

## No-Network Smoke

Run this first to prove the release artifacts and vendored runtime are usable without touching RAGFlow:

```bash
mkdir -p /tmp/ragflow-skills-smoke/input-docs
printf '# Smoke\n\nPortable RAGFlow skill smoke.\n' > /tmp/ragflow-skills-smoke/input-docs/sample.md

python ragflow-doc-to-md/scripts/convert.py \
  --input /tmp/ragflow-skills-smoke/input-docs \
  --output /tmp/ragflow-skills-smoke/handoff \
  --mode passthrough \
  --json

python ragflow-canonical-review/scripts/audit_markdown_structure.py \
  --markdown /tmp/ragflow-skills-smoke/handoff/documents/sample.md \
  --image-root /tmp/ragflow-skills-smoke/handoff/documents \
  --json-out /tmp/ragflow-skills-smoke/canonical-audit.json

python ragflow-kb-build/scripts/build.py \
  --doc-manifest /tmp/ragflow-skills-smoke/handoff/doc_manifest.json \
  --kb-name kb:ragflow-skills-smoke \
  --profile ragflow-kb-build/templates/default-en-768.json \
  --dry-run \
  --json

python ragflow-query/scripts/query.py ask --help
```

Expected result: `doc_manifest.json` is produced, canonical review reports structural-only
status without claiming source fidelity, `build.py --dry-run` succeeds, and
`query.py ask --help` shows `--mode` and `--host-assisted`.

## Formal Pre-Ingest Handoff

For real document preparation before KB build, prefer the pipeline command so the host agent does not forget postprocess, rich sidecars, or the non-secret ingest plan:

```bash
python ragflow-doc-to-md/scripts/convert.py pipeline \
  --input /path/to/source-docs \
  --output /tmp/ragflow-skills-handoff \
  --backend mineru-fastapi \
  --mineru-asset-mode markdown_assets \
  --postprocess-profile chunk-markers-dense \
  --json
```

For complex table documents on MinerU FastAPI, add `--table-quality high` for an explicit
high-accuracy pass, or `--table-quality auto` when the host should promote only formal
PDF/Office/image candidates.

For MinerU v4 platform-compatible APIs, use `--backend mineru-v4` with the same formal
handoff shape. The public `https://mineru.net` service is the official example endpoint;
compatible hosted or gateway services may use their own base URL. `--table-quality high`
selects `--mineru-v4-model-version vlm` unless the user explicitly configured
`MinerU-HTML`.

When the source shape is unknown, run the deterministic adaptive entrypoint first. Use
`--decision-only` when the user wants to review parameters before conversion:

```bash
python ragflow-doc-to-md/scripts/convert.py adaptive \
  --input /path/to/source-docs \
  --output /tmp/ragflow-skills-handoff \
  --decision-only \
  --report-json /tmp/ragflow-skills-handoff/adaptive_summary.json \
  --redaction-report /tmp/ragflow-skills-handoff/adaptive_summary.redaction.json \
  --json
```

Without `--decision-only`, `adaptive` reuses the formal pipeline and writes
`document_features.json`, `pipeline_decision.json`, and `adaptive_summary.json` into the
handoff. It does not call an LLM or execute live RAGFlow mutation.

Expected result: stdout and `doc_manifest.json` contain `handoff_mode:
formal_ingest`; the handoff contains `doc_manifest.json`, `quality_report.json`,
`runtime_report.json` when applicable, `postprocess_report.json`,
`retrieval_hints.json`, rich package sidecars, and `ragflow_ingest_plan.yaml`. The
ingest plan is advisory and non-secret; it must not contain RAGFlow endpoints or API
keys.

If stdout or `doc_manifest.json` says `handoff_mode: thin_preview`, do not treat the
output as a formal KB pre-ingest package. Re-run with `ragflow-doc-to-md pipeline`
before comparing it with a legacy thick package or sending it to a live build.

## Required Canonical Multimodal Order

When the user selects canonical mode, the host must enforce this non-skippable order:

1. Retain the MinerU extraction handoff unchanged as candidate evidence.
2. Copy editable content into a separate review workspace; run the structural audit with
   the exact source and complete a source-coverage map.
3. Record one source-backed decision for every candidate HTML table, then run the positive
   asset audit over the reviewed Markdown and local images.
4. Run `finalize_review.py`; continue only for `ragflow_canonical_review_v1.status:
   accepted`. Write all accepted files under the command's new output root.
5. Create a new passthrough handoff from the accepted output. Do not repurpose or overwrite
   the extraction handoff.
6. Run `inspect-handoff`, `asset-upload-plan`, `image-ingestion-readiness`, and build
   `--dry-run` against the new handoff.
7. Run live text build or `image-ingestion-execute` only after a separate approval naming
   the target and mutation types. Provider and model choices must come from the user or
   deployment configuration.

The host order and build-side canonical gate are both required. The build gate rehashes
the accepted record's exact source, Markdown, audits, and selected assets before client
creation; generic non-canonical builds remain compatible. Conversion success,
`PASS_WITH_REVIEW`, `ready_with_review`, table fingerprint preservation, and local image
presence do not by themselves prove canonical acceptance or completed multimodal
ingestion.

When a user asks for retained-package comparison, keep it static and explicit:

```bash
python ragflow-doc-to-md/scripts/convert.py compare-retained-package \
  --retained-package /path/to/legacy-retained-package \
  --replacement-handoff /tmp/ragflow-skills-handoff \
  --report-json /tmp/ragflow-skills-handoff/comparison.json \
  --report-md /tmp/ragflow-skills-handoff/comparison.md \
  --redaction-report /tmp/ragflow-skills-handoff/comparison.redaction.json \
  --json
```

Expected result: `ragflow_handoff_comparison_v1` is written without live RAGFlow
mutation. The report compares retained ingestion-package artifacts only, excludes
obvious raw/intermediate/layout/span directories, normalizes chunk markers and image path
differences for text similarity, and marks strict paired live A/B as `not_run` unless a
separately approved live run produced evidence.

Before any live RAGFlow mutation, run:

```bash
python ragflow-kb-build/scripts/build.py inspect-handoff \
  --handoff /tmp/ragflow-skills-handoff \
  --report-json /tmp/ragflow-skills-handoff/inspection.json \
  --report-md /tmp/ragflow-skills-handoff/inspection.md

python ragflow-kb-build/scripts/build.py asset-upload-plan \
  --doc-manifest /tmp/ragflow-skills-handoff/doc_manifest.json \
  --report-json /tmp/ragflow-skills-handoff/asset_upload_plan.json \
  --report-md /tmp/ragflow-skills-handoff/asset_upload_plan.md \
  --package-zip /tmp/ragflow-skills-handoff/asset_upload_package.zip \
  --json

python ragflow-kb-build/scripts/build.py image-ingestion-readiness \
  --asset-upload-plan /tmp/ragflow-skills-handoff/asset_upload_plan.json \
  --profile ragflow-kb-build/templates/default-en-768.json \
  --report-json /tmp/ragflow-skills-handoff/image_ingestion_readiness.json \
  --json

python ragflow-kb-build/scripts/build.py \
  --doc-manifest /tmp/ragflow-skills-handoff/doc_manifest.json \
  --kb-name kb:reviewed-name \
  --profile ragflow-kb-build/templates/default-en-768.json \
  --ingest-plan /tmp/ragflow-skills-handoff/ragflow_ingest_plan.yaml \
  --canonical-review ./accepted-review/ragflow_canonical_review.json \
  --canonical-source ./source/document.pdf \
  --canonical-markdown-audit ./run/markdown-audit.json \
  --canonical-asset-audit ./run/asset-audit.json \
  --dry-run \
  --json
```

Repeat the same four canonical evidence options for an approved live text build. The
checkpoint and `kb_manifest.json` bind only the review-record SHA-256; they do not copy
the review record or private evidence paths.

Review dry-run `build_payload_preview` and `handoff_consumption_status` before live
mutation. The preview shows the actual RAGFlow dataset payload versus local-only or
advisory evidence; the consumption status classifies sidecars, images, tables, metadata,
and assistant/query artifacts without implying they are all written to RAGFlow. If
`ingest_readiness.checks.chunk_readiness.delimiter_profile_guidance.status` is
`recommended`, plan a reviewed delimiter profile before live build; chunk marker
delimiters help boundaries only when the deployment honors `parser_config.delimiter` and
do not override server-side parent chunk limits.

Dry-run success does not create a real `kb_manifest.json` and cannot close a post-build
artifact consistency gate. Record that gate as pending until an authorized live build
writes the real manifest. If a later parse trigger or wait fails after dataset creation or
upload, inspect the checkpoint and read-only server state, fix the shared cause, and resume
the same build. Do not create a suffixed replacement KB or repeat confirmed uploads to
hide the failure.

## Complex Table Ingest Review

For complex specification tables, keep the review offline until the user explicitly
approves live RAGFlow mutation:

- Convert with `ragflow-doc-to-md pipeline --table-quality high` or `--table-quality auto`,
  `--mineru-asset-mode markdown_assets`, and `--postprocess-profile chunk-markers-dense`.
- Review `retrieval_hints.json` for `table_artifacts`, `table_term_alias_candidates`,
  `semantic_risks`, and `estimated_parent_chunk_tokens`.
- In canonical mode, finish exact-source review, table decisions, positive asset audit,
  and `ragflow_canonical_review_v1` acceptance before creating the new passthrough handoff.
- Run `inspect-handoff` and require no BLOCKED quality or missing-image errors.
- Run `asset-upload-plan`; require `missing_image_asset_count=0` before any live build,
  and review unreferenced handoff images instead of silently uploading them. Sidecar
  paths such as `images/...` are checked against both the handoff root and
  `documents/images/...`; semantic aliases remain advisory review hints.
- Prefer a generated `table-atomic-*-4096` profile when the target deployment supports
  that parent chunk size. If the deployment requires a smaller profile, materialize a
  reviewed profile that clamps unsupported `chunk_token_num` values, keeps the original
  suggestion auditable, and treats `table_parent_chunk_preflight` warnings from
  `build.py --dry-run` as manual review gates.
- Do not set a children delimiter for table-atomic ingestion; delimiter chunk markers
  control boundaries but cannot override a lower server-side parent chunk limit.

## Legacy Workflow Migration Gates

When replacing a legacy all-in-one workflow, map responsibilities explicitly:

| Legacy responsibility | Public skill replacement |
| --- | --- |
| Document conversion and image handoff | `ragflow-doc-to-md pipeline` with `markdown_assets` |
| Chunk markers and rich sidecars | `postprocess --profile chunk-markers-dense` and `package --rich`, run by `pipeline` |
| Retrieval hints and assistant review artifacts | `retrieval_hints.json`, `assistant_profile.json`, `assistant_test_plan.json` |
| RAGFlow ingest guidance | non-secret `ragflow_ingest_plan.yaml` |
| KB creation, parse, and validation | `ragflow-kb-build inspect-handoff`, `--dry-run`, build, validate, parse/health reports |
| Retrieval and assistant validation | `ragflow-query ask`, `assistant-profile recommend`, `assistant-test-plan` |

Before retiring the legacy workflow for a user workflow, confirm:

- release-facing offline validation is green for the packaged skills;
- a real MinerU FastAPI sample with images/tables produces local `documents/images/...` assets and a non-BLOCKED quality gate;
- `inspect-handoff` and `build.py --dry-run` pass without `--allow-blocked`;
- a user-approved disposable KB completes live build, parse wait, smoke validation, direct query, and host-assisted query;
- no report, sidecar, copied config, or summary contains real API keys, private endpoint secrets, or user-specific paths.

## Live RAGFlow E2E

Use a disposable KB name:

```text
kb:ragflow-skills-e2e-YYYYMMDD-HHMM
```

For Markdown-only E2E:

```bash
python ragflow-doc-to-md/scripts/convert.py \
  --config "$RAGFLOW_CONFIG" \
  --input /tmp/ragflow-skills-smoke/input-docs \
  --output /tmp/ragflow-skills-e2e/handoff \
  --mode passthrough \
  --json

python ragflow-kb-build/scripts/build.py \
  --config "$RAGFLOW_CONFIG" \
  --doc-manifest /tmp/ragflow-skills-e2e/handoff/doc_manifest.json \
  --kb-name kb:ragflow-skills-e2e-YYYYMMDD-HHMM \
  --profile ragflow-kb-build/templates/default-en-768.json \
  --output /tmp/ragflow-skills-e2e/kb_manifest.json \
  --json

python ragflow-kb-build/scripts/validate.py \
  --config "$RAGFLOW_CONFIG" \
  --kb-manifest /tmp/ragflow-skills-e2e/kb_manifest.json \
  --level smoke \
  --retention-json /tmp/ragflow-skills-e2e/public_query_result_retention.json \
  --retention-md /tmp/ragflow-skills-e2e/public_query_result_retention.md

python ragflow-query/scripts/query.py \
  --config "$RAGFLOW_CONFIG" \
  ask "Summarize this test knowledge base." \
  --kb-manifest /tmp/ragflow-skills-e2e/kb_manifest.json \
  --mode agentic \
  --host-assisted \
  --json
```

The `--output` file above is the real post-build manifest. Use it with fresh observed
state for consistency, parse, health, and validation reports. Treat nonzero application
`code` values as parse-trigger failures even when the transport returned JSON. If the
build is interrupted, use the same reviewed profile, KB name, checkpoint, and `--resume`;
verify exact dataset identity, document counts, and embedding model before continuing.

Live parser output may merge reviewed Markdown markers or add alternate HTML/table
chunks. Measure retrieval impact before changing canonical text or parser settings. A
non-empty query against a forced single KB is diagnostic only and does not prove that the
actual answer layer will or should answer.

For PDF/Office/image E2E, use `--backend mineru-fastapi` when the service implements MinerU FastAPI protocol v2, or `--backend mineru-v4` when it implements the MinerU v4 platform-compatible protocol. Keep `--backend auto` only when a local MinerU CLI is configured and should be preferred. Use `--backend mineru-cli` to force local CLI, `--backend mineru` when the service implements the MinerU Agent API, or `--backend mineru-sync` only for legacy synchronous multipart `/parse`. If no compatible CLI or service protocol can be identified, report the uncertainty and skip the MinerU test rather than guessing.

For formal `markdown_assets` handoffs, expect local image references to use readable semantic filenames when MinerU or another converter returns hash-like names. Do not treat the absence of hash filenames as lost provenance; content hashes remain in the public manifest and rich sidecars.

When retaining retrieval-quality evidence for comparison reports, prefer
`validate.py --retention-json --retention-md` over copying raw query output into a
shared summary. The retention artifact omits raw query text, raw chunk text, and raw
dataset/document/chunk IDs, and keeps global best-per-query counts distinct from
pairwise win counts.

## GitHub Release E2E

When testing a published release from the source repository, prefer the bundled harness:

```bash
python3 tools/consumer_acceptance.py \
  --github-release v0.1.0-rc2 \
  --repo OWNER/ragflow-skills \
  --work-dir /tmp/ragflow-skills-e2e-rc2 \
  --overwrite \
  --download-timeout 90
```

Add `--live-build` only when disposable RAGFlow credentials are configured and test KB creation is acceptable.

## Report Back

At the end, report:

- config path used, without secret values;
- whether no-network smoke passed;
- whether MinerU conversion was tested;
- created RAGFlow dataset name and ID;
- paths to `doc_manifest.json`, `kb_manifest.json`, validation reports, and query output;
- cleanup recommendation for the disposable KB.
