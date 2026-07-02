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
- Distinguish MinerU execution modes before testing conversion. The `mineru-fastapi` backend supports MinerU 3.2+ FastAPI protocol v2: submit files to `/tasks`, poll `/tasks/{task_id}`, then read Markdown from `/tasks/{task_id}/result`. The `mineru-cli` backend runs a local MinerU binary. The `mineru` and `mineru-agent` backends support the MinerU Agent API shape: create a parse task with `/parse/file`, upload to the returned URL, poll `/parse/{task_id}`, then download Markdown. The `mineru-sync` and `mineru-local` backends are legacy compatibility paths for synchronous multipart `/parse` services.
- For a remote MinerU FastAPI service, set `doc_to_md.backend: mineru-fastapi` explicitly. Use `auto` only when local `mineru-cli` discovery is intentionally allowed. Do not set `doc_to_md.backend: mineru` for a FastAPI v2 or synchronous multipart MinerU service.
- Do not patch `scripts/_vendor` inside release artifacts. New backend support must be implemented in the source runtime package and then re-vendored by the release builder.
- Keep all E2E artifacts in a temporary or user-approved workspace, and report paths at the end.

## Config Locations

Recommended real config paths:

- Hermes: `~/.hermes/ragflow/config.local.yaml`
- OpenClaw: `~/.config/openclaw/ragflow/config.local.yaml`, `/etc/openclaw/ragflow/config.local.yaml`, `/var/lib/openclaw/ragflow/config.local.yaml`, or a mounted secret/config path
- Claude Code and opencode: `~/.config/ragflow-skills/config.local.yaml`
- Project fallback: `.ragflow/config.local.yaml` only when the working directory is stable and private

The config file may contain `${ENV_VAR}` placeholders. Put secret values in the host environment, secret store, or mounted secret path.

Config precedence for the MinerU FastAPI endpoint is: `--mineru-base-url` overrides `MINERU_BASE_URL`, which overrides `mineru.base_url` in the config file.

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
  # Use auto only when local CLI discovery is intentionally allowed.
  backend: mineru-fastapi

mineru:
  # Optional local CLI example: /opt/mineru/bin/mineru
  cli_path: ${MINERU_CLI_PATH}
  cli_backend: pipeline
  # FastAPI v2 async example: https://mineru.example.internal
  # Agent API example: https://mineru.net/api/v1/agent
  # Legacy sync multipart example: http://mineru.example.internal:8777/api/v1
  base_url: https://mineru.example.internal
  api_key: ${MINERU_API_KEY}
  timeout: 1800
  poll_interval: 3
  verify_ssl: true
  asset_mode: markdown_assets
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

1. Confirm the three public skill folders are available in the same workspace:
   - `ragflow-doc-to-md`
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
   - whether the service implements MinerU Agent API or synchronous multipart `/parse`
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

python ragflow-kb-build/scripts/build.py \
  --doc-manifest /tmp/ragflow-skills-smoke/handoff/doc_manifest.json \
  --kb-name kb:ragflow-skills-smoke \
  --profile ragflow-kb-build/templates/default-en-768.json \
  --dry-run \
  --json

python ragflow-query/scripts/query.py ask --help
```

Expected result: `doc_manifest.json` is produced, `build.py --dry-run` succeeds, and `query.py ask --help` shows `--mode` and `--host-assisted`.

## Formal Pre-Ingest Handoff

For real document preparation before KB build, prefer the pipeline command so the host agent does not forget postprocess, rich sidecars, or the non-secret ingest plan:

```bash
python ragflow-doc-to-md/scripts/convert.py pipeline \
  --input /path/to/source-docs \
  --output /tmp/ragflow-skills-handoff \
  --backend mineru-fastapi \
  --mineru-asset-mode markdown_assets \
  --postprocess-profile chunk-markers \
  --json
```

Expected result: the handoff contains `doc_manifest.json`, `quality_report.json`, `runtime_report.json` when applicable, `postprocess_report.json`, `retrieval_hints.json`, rich package sidecars, and `ragflow_ingest_plan.yaml`. The ingest plan is advisory and non-secret; it must not contain RAGFlow endpoints or API keys.

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
  --level smoke

python ragflow-query/scripts/query.py \
  --config "$RAGFLOW_CONFIG" \
  ask "Summarize this test knowledge base." \
  --kb-manifest /tmp/ragflow-skills-e2e/kb_manifest.json \
  --mode agentic \
  --host-assisted \
  --json
```

For PDF/Office/image E2E, use `--backend mineru-fastapi` when the service implements MinerU FastAPI protocol v2. Keep `--backend auto` only when a local MinerU CLI is configured and should be preferred. Use `--backend mineru-cli` to force local CLI, `--backend mineru` when the service implements the MinerU Agent API, or `--backend mineru-sync` only for legacy synchronous multipart `/parse`. If no compatible CLI or service protocol can be identified, report the uncertainty and skip the MinerU test rather than guessing.

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
