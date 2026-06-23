# CLI Agent Integration

Status: active
Date: 2026-06-23

## Purpose

This guide describes how to use the public RAGFlow skills from controllable programming-agent CLI environments:

- Hermes;
- OpenClaw;
- Claude Code;
- opencode;
- similar local, LAN, VPN, or HTTPS-reachable CLI runners.

Commercial SaaS agent sandboxes are not a v1 target. First-party SaaS platforms should integrate RAGFlow, MinerU, Pandoc, validation, and retrieval as native backend services rather than by shelling out to these portable scripts.

## Release Shape

Use per-skill release archives:

```text
ragflow-doc-to-md.tar.gz
ragflow-kb-build.tar.gz
ragflow-query.tar.gz
release-manifest.json
```

Each archive contains a self-contained skill folder:

```text
SKILL.md
scripts/
scripts/_vendor/ragflow_skill_runtime/
templates/
```

No editable install is required. Source checkouts can also run with:

```bash
export RAGFLOW_SKILL_RUNTIME_PATH=/path/to/ragflow-skills/packages/ragflow-skill-runtime/src
```

## Configuration

Prefer explicit CLI flags for one-off tasks and environment variables for repeated agent sessions.

RAGFlow:

```bash
export RAGFLOW_BASE_URL=https://ragflow.example.test
export RAGFLOW_API_KEY=...
```

Document conversion remote backend:

```bash
export DOC_TO_MD_BACKEND=mineru
export MINERU_BASE_URL=https://mineru.net/api/v1/agent
export MINERU_API_KEY=...
export MINERU_TIMEOUT=300
export MINERU_POLL_INTERVAL=3
```

Generic converter backend:

```bash
export DOC_TO_MD_BACKEND=remote
export DOC_TO_MD_REMOTE_URL=https://converter.example.test/convert
export DOC_TO_MD_REMOTE_API_KEY=...
export DOC_TO_MD_TIMEOUT=120
```

Local config files are also supported:

```text
.ragflow/config.yaml
```

Example:

```yaml
base_url: https://ragflow.example.test
api_key: replace-with-local-secret
timeout: 60
verify_ssl: true
```

Do not commit local config files or real credentials.

## Endpoint Rules

RAGFlow may be reachable through:

- localhost for local Hermes/OpenClaw deployments;
- LAN or VPN addresses for controlled workstations or clusters;
- HTTPS gateways for remote runners.

Public scripts do not start or manage RAGFlow. They only call an explicitly configured endpoint.

Pandoc is treated as a local binary on `PATH`. MinerU is treated as a remote service by default and is configured through `MINERU_*` environment variables. Other layout-aware parsers can use the generic remote converter contract.

## Document To Markdown

Existing Markdown:

```bash
python ragflow-doc-to-md/scripts/convert.py \
  --input ./markdown \
  --output ./handoff \
  --mode passthrough \
  --json
```

Remote converter:

```bash
python ragflow-doc-to-md/scripts/convert.py \
  --input ./raw \
  --output ./handoff \
  --backend mineru \
  --json
```

The MinerU backend uses the Agent parsing API shape: create a parse task, upload the local file to the returned signed URL, poll the task, and download the returned Markdown URL.

Generic remote converter:

```bash
python ragflow-doc-to-md/scripts/convert.py \
  --input ./raw \
  --output ./handoff \
  --backend remote \
  --json
```

The remote converter receives JSON:

```json
{
  "filename": "example.pdf",
  "content_base64": "..."
}
```

It should return:

```json
{
  "markdown": "# Example\n..."
}
```

## Build KB

```bash
python ragflow-kb-build/scripts/build.py \
  --doc-manifest ./handoff/doc_manifest.json \
  --kb-name kb:project-docs \
  --profile ./ragflow-kb-build/templates/default-zh-512.json \
  --output ./run/kb_manifest.json
```

Dry-run without touching RAGFlow:

```bash
python ragflow-kb-build/scripts/build.py \
  --doc-manifest ./handoff/doc_manifest.json \
  --kb-name kb:project-docs \
  --profile ./ragflow-kb-build/templates/default-zh-512.json \
  --dry-run \
  --json
```

Validate:

```bash
python ragflow-kb-build/scripts/validate.py \
  --kb-manifest ./run/kb_manifest.json \
  --level smoke
```

## Query

Direct retrieval:

```bash
python ragflow-query/scripts/query.py \
  ask "What does this KB say?" \
  --kb-manifest ./run/kb_manifest.json \
  --mode direct \
  --json
```

Host-assisted agentic evidence:

```bash
python ragflow-query/scripts/query.py \
  ask "Compare the main tradeoffs." \
  --kb-manifest ./run/kb_manifest.json \
  --mode agentic \
  --host-assisted \
  --json
```

In v1, `agentic` means evidence return for a host agent. Script-owned planning and synthesis are deferred.

## Platform Notes

Hermes:

- source checkout can use `RAGFLOW_SKILL_RUNTIME_PATH`;
- release artifacts can use vendored runtime;
- localhost or LAN RAGFlow endpoints are valid.

OpenClaw:

- use CLI mode in v1;
- configure RAGFlow through flags, environment variables, or a workspace config file;
- `serve` remains deferred until a repeated low-latency tool endpoint is needed.

Claude Code and opencode:

- unpack release archives inside the workspace;
- call scripts directly;
- pass absolute paths for handoff and KB manifests when steps run from different working directories.

## Smoke Checks

Run the matrix from a source checkout:

```bash
python3 tools/platform_smoke_matrix.py
python3 tools/platform_smoke_matrix.py --profile opencode-cli
python3 tools/platform_smoke_matrix.py --profile openclaw-cli-v1
```

Release tools rebuild `dist/`; run them sequentially.
