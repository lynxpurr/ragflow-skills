# CLI Agent Integration

Status: active
Date: 2026-06-23

## Purpose

This guide describes how to use the public RAGFlow skills from controllable programming-agent CLI environments:

- Hermes;
- OpenClaw;
- Claude Code;
- opencode;
- similar LAN, VPN, HTTPS, or explicitly local-debug CLI runners.

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

Prefer a stable host-agent config file for repeated use, explicit CLI flags for one-off overrides, and environment variables for secrets or deployment injection. The default assumption is that RAGFlow and MinerU run outside the agent machine and are reached through LAN, VPN, or HTTPS endpoints.

Each public skill ships the same template:

```text
templates/ragflow-config.example.yaml
```

Copy it to a stable host-agent path and point scripts to it with `RAGFLOW_CONFIG`:

```bash
export RAGFLOW_CONFIG=$HOME/.hermes/ragflow/config.local.yaml
```

Recommended locations:

- Hermes: `~/.hermes/ragflow/config.local.yaml`
- OpenClaw: `/etc/openclaw/ragflow/config.local.yaml`, `/var/lib/openclaw/ragflow/config.local.yaml`, or a mounted secret/config path
- Claude Code / opencode: `~/.config/ragflow-skills/config.local.yaml`
- Local project fallback: `.ragflow/config.yaml` plus `.ragflow/config.local.yaml` in the current working directory

Prefer host-agent config paths over document-project folders when project naming or working directories are unstable. Do not put real config in the skill folder; skill folders are release artifacts and may be replaced during upgrades.

Example:

```yaml
ragflow:
  base_url: https://ragflow.example.test
  api_key: ${RAGFLOW_API_KEY}
  timeout: 60
  verify_ssl: true

doc_to_md:
  backend: mineru

mineru:
  base_url: https://mineru.net/api/v1/agent
  api_key: ${MINERU_API_KEY}
  timeout: 300
  poll_interval: 3
  language: ch
  enable_table: true
  is_ocr: false
  enable_formula: true
```

Generic remote converter alternative:

```yaml
doc_to_md:
  backend: remote
  remote_url: https://converter.example.test/convert
  remote_api_key: ${DOC_TO_MD_REMOTE_API_KEY}
  remote_timeout: 120
```

Environment-only configuration remains supported:

```bash
export RAGFLOW_BASE_URL=https://ragflow.example.test
export RAGFLOW_API_KEY=...
export DOC_TO_MD_BACKEND=mineru
export MINERU_BASE_URL=https://mineru.net/api/v1/agent
export MINERU_API_KEY=...
```

Do not commit local config files or real credentials. Use `${ENV_VAR}` placeholders in shared config files when possible.

## Endpoint Rules

RAGFlow may be reachable through:

- LAN or VPN addresses for controlled workstations or clusters;
- HTTPS gateways for remote runners.
- localhost only when the host agent and service are intentionally co-located for debugging or a single-machine deployment.

Public scripts do not start or manage RAGFlow. They only call an explicitly configured endpoint.

Pandoc is treated as a local binary on `PATH`. MinerU is treated as a remote service by default and is configured through the shared config file or `MINERU_*` environment variables. The built-in `mineru` backend expects the MinerU Agent API protocol: create a task at `/parse/file`, upload to the returned URL, poll `/parse/{task_id}`, then download Markdown. Other MinerU-compatible services, including local synchronous multipart `/parse` APIs, should be exposed through a compatible gateway or the generic remote converter contract.

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

The MinerU backend uses the Agent parsing API shape: create a parse task, upload the local file to the returned signed URL, poll the task, and download the returned Markdown URL. Do not point this backend directly at a local synchronous multipart `/parse` service unless a gateway makes it Agent API compatible.

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
- use LAN, VPN, or HTTPS RAGFlow/MinerU endpoints by default;
- localhost is valid only when services are intentionally running on the same machine.

OpenClaw:

- use CLI mode in v1;
- configure RAGFlow through flags, environment variables, or a workspace config file;
- prefer mounted config/secret paths for RAGFlow and MinerU endpoints;
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
