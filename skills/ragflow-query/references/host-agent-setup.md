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
- Distinguish MinerU execution modes before testing conversion. The `mineru-cli` backend runs a local MinerU binary. The `mineru` and `mineru-agent` backends support the MinerU Agent API shape: create a parse task with `/parse/file`, upload to the returned URL, poll `/parse/{task_id}`, then download Markdown. The `mineru-sync` and `mineru-local` backends support synchronous multipart `/parse` services, whether they run on localhost, LAN, VPN, or HTTPS.
- Keep `doc_to_md.backend: auto` unless a specific converter is required. In `auto`, local `mineru-cli` is preferred when `MINERU_CLI_PATH`, `mineru.cli_path`, or `mineru` on `PATH` is available; then configured service backends can be used. Do not set `doc_to_md.backend: mineru` for a synchronous multipart MinerU service.
- Do not patch `scripts/_vendor` inside release artifacts. New backend support must be implemented in the source runtime package and then re-vendored by the release builder.
- Keep all E2E artifacts in a temporary or user-approved workspace, and report paths at the end.

## Config Locations

Recommended real config paths:

- Hermes: `~/.hermes/ragflow/config.local.yaml`
- OpenClaw: `~/.config/openclaw/ragflow/config.local.yaml`, `/etc/openclaw/ragflow/config.local.yaml`, `/var/lib/openclaw/ragflow/config.local.yaml`, or a mounted secret/config path
- Claude Code and opencode: `~/.config/ragflow-skills/config.local.yaml`
- Project fallback: `.ragflow/config.local.yaml` only when the working directory is stable and private

The config file may contain `${ENV_VAR}` placeholders. Put secret values in the host environment, secret store, or mounted secret path.

## Minimal Config

Create the host config from `templates/ragflow-config.example.yaml` if it does not exist. Keep placeholders for secrets:

```yaml
ragflow:
  base_url: https://ragflow.example.com
  api_key: ${RAGFLOW_API_KEY}
  timeout: 60
  verify_ssl: true

doc_to_md:
  # Keep auto unless a specific converter is required.
  # Auto uses local mineru-cli first when available, then other configured backends.
  # Use mineru/mineru-agent for Agent API; use mineru-sync/mineru-local for sync multipart /parse.
  backend: auto

mineru:
  # Optional local CLI example: /opt/mineru/bin/mineru
  cli_path: ${MINERU_CLI_PATH}
  cli_backend: pipeline
  # Agent API example: https://mineru.net/api/v1/agent
  # Sync multipart example: http://mineru.internal:8777/api/v1
  base_url: https://mineru.net/api/v1/agent
  api_key: ${MINERU_API_KEY}
  timeout: 300
  poll_interval: 3
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

For PDF/Office/image E2E, keep `--backend auto` when a local MinerU CLI is configured and should be preferred. Use `--backend mineru-cli` to force local CLI, `--backend mineru` when the service implements the MinerU Agent API, or `--backend mineru-sync` when the service implements synchronous multipart `/parse`. If no compatible CLI or service protocol can be identified, report the uncertainty and skip the MinerU test rather than guessing.

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
