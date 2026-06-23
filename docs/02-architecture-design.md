# Cross-Platform RAGFlow Skills Architecture

Status: implementation snapshot
Date: 2026-06-22

## Decision Summary

Build a public RAGFlow skill suite with three skills and one shared runtime package:

```text
ragflow-doc-to-md      raw documents -> Markdown handoff
ragflow-kb-build      Markdown -> RAGFlow KB + validation
ragflow-query         direct and host-assisted agentic retrieval
ragflow-skill-runtime          shared runtime, vendored into release artifacts
```

Dedao-related skills stay private and are not shipped.

Commercial SaaS agent sandboxes are explicitly out of the v1 public skill target set. They are usually difficult to extend, constrain service configuration, and are not the user's preferred deployment path. If the user builds a first-party SaaS platform, RAGFlow, MinerU, Pandoc, and retrieval workflows should be implemented as platform-native backend services and LangGraph/tool code, using this repository only as a reference for command semantics and manifest shapes.

## Design Principles

- High cohesion: each public skill owns one state transition.
- Loose coupling: skills communicate through thin manifest files and `ragflow-skill-runtime`, not through direct imports of each other.
- Self-contained release: every published skill can run without editable installs or local absolute paths.
- Portable by default: no `/home/zenz`, no implicit localhost assumption, and no required long-running daemon.
- Remote-service friendly: RAGFlow and MinerU normally live on reachable LAN, VPN, or HTTPS endpoints; localhost is only a configured local-debug case.
- CLI-agent friendly: Hermes, OpenClaw, Claude Code, and opencode can provide config through host-agent files, environment variables, or explicit CLI flags.
- Non-SaaS public scope: optimize for Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent CLI tools.
- Product-grade validation: KB build includes retrieval validation as a first-class command.
- Progressive disclosure: `SKILL.md` files stay short; detailed behavior goes into `references/` and deterministic code goes into `scripts/`.

## Public Skill Boundaries

### `ragflow-doc-to-md`

Owns:

- Source file discovery.
- Document conversion to Markdown.
- Source hashing and metadata capture.
- Conversion warnings and skip reports.
- `doc_manifest.json` creation.

Does not own:

- RAGFlow upload.
- Chunking profile decisions beyond optional metadata hints.
- Query, retrieval, rerank, or synthesis.
- Dedao download or bookshelf automation.

### `ragflow-kb-build`

Owns:

- Markdown ingestion into RAGFlow.
- Chunk profile linting.
- Dataset creation and update.
- Document upload and parse triggering.
- Parse status monitoring.
- KB inspection.
- Retrieval validation at smoke, regression, and benchmark levels.
- `kb_manifest.json` creation.

Does not own:

- Raw file conversion.
- Agentic synthesis.
- Long-lived query service as a default behavior.
- Private MySQL/ES repair unless explicitly exposed as an advanced admin reference.

### `ragflow-query`

Owns:

- Direct retrieval.
- Host-assisted agentic evidence retrieval.
- `--mode auto|direct|agentic` dispatch.
- Host-assisted evidence return for host agents that do final answer generation.

Does not own:

- KB creation.
- Markdown conversion.
- Dedao-specific routing examples.
- Script-owned planning/synthesis in v1.
- Long-lived HTTP service mode in v1.

## `ragflow-skill-runtime` Runtime Boundary

`ragflow-skill-runtime` is the shared runtime package. It is a public, neutral package, not a renamed dump of current shared-infra.

Allowed modules:

```text
ragflow_skill_runtime/
  __init__.py
  bootstrap.py
  auth.py
  config.py
  paths.py
  http.py
  manifests.py
  profiles.py
  ragflow_client.py
  retrieval.py
  doc_convert.py
  kb_build.py
  validation.py
  routing.py
  llm.py
```

Allowed content:

- HTTP client and retry logic.
- Auth and config loading.
- Environment variable handling.
- Thin manifest dataclasses.
- Profile linting helpers.
- Direct retrieval logic.
- RAGFlow response normalization.
- Query routing helpers.
- Common validation primitives.

Implemented modules as of this snapshot:

```text
auth.py
bootstrap.py
config.py
doc_convert.py
http.py
kb_build.py
manifests.py
paths.py
profiles.py
ragflow_client.py
retrieval.py
validation.py
```

Future modules:

```text
routing.py
llm.py
```

Forbidden content:

- Dedao code, names, IDs, cookies, or CLI assumptions.
- OPC or personal infra details.
- Hardcoded private KB names.
- Hardcoded `/home/zenz` paths.
- Cron registry, agent inventory, fleet control, or local operations metadata.
- Secrets or secret examples that look real.

## Runtime Loading Strategy

Every public script starts by bootstrapping `ragflow-skill-runtime`.

Runtime resolution:

1. `RAGFLOW_SKILL_RUNTIME_PATH` when explicitly set.
2. Skill-local `scripts/_vendor/ragflow_skill_runtime`.
3. Optional adjacent bundle-level `_shared/ragflow_skill_runtime`.
4. Normal Python import paths, including an installed `ragflow_skill_runtime` package.

Minimal bootstrap pattern:

```python
from pathlib import Path
import os
import sys

def bootstrap_core() -> None:
    candidates = [
        os.environ.get("RAGFLOW_SKILL_RUNTIME_PATH"),
        Path(__file__).parent / "_vendor",
        Path(__file__).parents[1] / "_shared",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            sys.path.insert(0, str(candidate))
            return

bootstrap_core()
```

Release artifacts must include `scripts/_vendor/ragflow_skill_runtime/` so Claude Code, opencode, and other CLI agents can run without package installation.

## Configuration Contract

Public skills read configuration with this effective precedence:

1. Explicit CLI flags.
2. Environment variables.
3. Explicit config file from `--config` or `RAGFLOW_CONFIG`.
4. Auto-discovered project config: `.ragflow/config.json|yaml|yml`, then `.ragflow/config.local.json|yaml|yml`.
5. Safe defaults.

Each public skill ships `templates/ragflow-config.example.yaml`. Real config should be copied to a stable host-agent path, not stored in the skill folder. Recommended paths are:

- Hermes: `~/.hermes/ragflow/config.local.yaml`.
- OpenClaw: `~/.config/openclaw/ragflow/config.local.yaml`, `/etc/openclaw/ragflow/config.local.yaml`, `/var/lib/openclaw/ragflow/config.local.yaml`, or a mounted secret/config path.
- Claude Code and opencode: `~/.config/ragflow-skills/config.local.yaml`.
- Project fallback: `.ragflow/config.yaml` plus `.ragflow/config.local.yaml` only when the working directory is stable.

The config file is intentionally lightweight YAML/JSON, not a formal schema system. It supports top-level sections for `ragflow`, `doc_to_md`, and `mineru`, plus `${ENV_VAR}` substitution for secrets.

Example:

```yaml
ragflow:
  base_url: https://ragflow.example.com
  api_key: ${RAGFLOW_API_KEY}
  timeout: 60
  verify_ssl: true

doc_to_md:
  # Keep auto unless the MinerU protocol is confirmed.
  # Use mineru/mineru-agent for Agent API; use mineru-sync/mineru-local for sync multipart /parse.
  backend: auto

mineru:
  # Agent API example: https://mineru.net/api/v1/agent
  # Sync multipart example: http://mineru.internal:8777/api/v1
  base_url: https://mineru.net/api/v1/agent
  api_key: ${MINERU_API_KEY}
  timeout: 300
  poll_interval: 3
  language: ch
  enable_table: true
  is_ocr: false
  enable_formula: true
```

Core environment variables:

| Variable | Purpose |
|---|---|
| `RAGFLOW_BASE_URL` | RAGFlow API base URL, such as `https://ragflow.example.com/api/v1`. |
| `RAGFLOW_API_KEY` | RAGFlow bearer token. |
| `RAGFLOW_TIMEOUT` | RAGFlow request timeout in seconds. |
| `RAGFLOW_VERIFY_SSL` | Set to `false` only for controlled self-signed test endpoints. |
| `RAGFLOW_CONFIG` | Optional config file path. |
| `RAGFLOW_AUTH_FILE` | Optional auth file path. |
| `RAGFLOW_SKILL_RUNTIME_PATH` | Optional development-time source override for `ragflow_skill_runtime`. |
| `RAGFLOW_LLM_BASE_URL` | Optional OpenAI-compatible LLM endpoint for script-owned synthesis. |
| `RAGFLOW_LLM_API_KEY` | Optional LLM API key. |
| `DOC_TO_MD_BACKEND` | Document converter backend: `auto`, `builtin`, `pandoc`, `remote`, or `mineru`. |
| `DOC_TO_MD_REMOTE_URL` | Generic remote converter endpoint. |
| `DOC_TO_MD_REMOTE_API_KEY` | Generic remote converter bearer token. |
| `DOC_TO_MD_TIMEOUT` | Generic remote converter timeout in seconds. |
| `MINERU_BASE_URL` | MinerU service base URL. Use an Agent API base for `mineru` / `mineru-agent`, or a sync multipart service root for `mineru-sync` / `mineru-local`. |
| `MINERU_API_KEY` | MinerU API key. |
| `MINERU_TIMEOUT` | MinerU parse timeout in seconds. |
| `MINERU_POLL_INTERVAL` | MinerU parse polling interval in seconds. |
| `MINERU_LANGUAGE` | MinerU language option. |
| `MINERU_PAGE_RANGE` | Optional MinerU page range. |
| `MINERU_ENABLE_TABLE` | MinerU table parsing boolean. |
| `MINERU_IS_OCR` | MinerU OCR boolean. |
| `MINERU_ENABLE_FORMULA` | MinerU formula parsing boolean. |

No public script may default to `http://localhost:9380` unless the user asks for local mode or a config file explicitly declares it.

Public skills do not start or supervise RAGFlow, MinerU, Pandoc workers, or query daemons. RAGFlow and MinerU are external services configured by endpoint and key. Pandoc is a local binary if installed on `PATH`; otherwise use MinerU or a generic remote converter.

## Thin Manifest Strategy

Use two lightweight manifests. Do not build a heavy JSON Schema system in phase 1.

### `doc_manifest.json`

Purpose: handoff from document conversion to KB build.

Minimum fields:

```json
{
  "version": "0.1",
  "created_at": "2026-06-22T00:00:00Z",
  "source_root": ".",
  "documents": [
    {
      "source_path": "docs/example.pdf",
      "markdown_path": "documents/example.md",
      "sha256": "hex",
      "title": "Example",
      "language": "unknown",
      "warnings": []
    }
  ]
}
```

### `kb_manifest.json`

Purpose: handoff from KB build to query and validation.

Minimum fields:

```json
{
  "version": "0.1",
  "created_at": "2026-06-22T00:00:00Z",
  "ragflow_base_url": "https://ragflow.example.com/api/v1",
  "dataset": {
    "id": "dataset-id",
    "name": "kb:project-docs"
  },
  "profile": {
    "id": "default-zh-512",
    "embedding_model": "provider/model"
  },
  "documents": [
    {
      "document_id": "doc-id",
      "source_path": "docs/example.pdf",
      "markdown_path": "documents/example.md",
      "status": "parsed",
      "chunk_count": 12
    }
  ]
}
```

Validation can be implemented with dataclasses and explicit required-field checks. Formal JSON Schema and compatibility migration are deferred until multiple independent consumers need them.

## Validation Model

Validation remains a product feature of `ragflow-kb-build`, but entry points are layered.

| Level | Default | Purpose |
|---|---|---|
| `smoke` | Yes after build | Fast check: KB exists, docs parsed, query returns chunks. |
| `regression` | No | Runs a user-provided query set with lightweight pass/fail metrics. |
| `benchmark` | No | Uses the same stable query-set surface initially; heavier benchmark runners remain opt-in backlog. |

Example:

```bash
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level smoke
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level regression --queries ./queries.json
python scripts/validate.py --kb-manifest ./run/kb_manifest.json --level benchmark --queries ./queries.json --report-md ./report.md
```

## Query Modes

`ragflow-query` exposes one user-facing command and three modes:

| Mode | Behavior |
|---|---|
| `direct` | Implemented: retrieve chunks from one or more KBs and return normalized chunks. |
| `agentic` | Partial: host-assisted evidence return is supported; script-owned planning/synthesis is future work. |
| `auto` | Implemented conservatively: currently falls back to direct mode. |

Host-assisted fallback:

- If no LLM key is available, `agentic` can run in `--host-assisted` mode.
- In host-assisted mode, the script returns plan/chunks/evidence and lets the host agent synthesize the final answer.

Current gap:

- `serve` is not implemented yet.
- Script-owned LLM synthesis is not implemented yet.
- Agentic planning/reflection is not implemented yet.

V1 scope decision:

- Public v1 is CLI-first.
- `serve` is deferred to a later local/OpenClaw phase.
- `agentic` v1 means `--host-assisted` evidence return; script-owned planning and synthesis are deferred.

## Platform Compatibility

| Platform | Core loading | RAGFlow access | Recommended interface |
|---|---|---|---|
| Hermes local | Installed package or vendor | LAN, VPN, HTTPS, or explicit localhost debug endpoint | CLI. |
| OpenClaw | Installed package or vendor | LAN, VPN, HTTPS gateway, or explicit localhost debug endpoint | CLI for v1; `serve` deferred. |
| Claude Code | Vendor preferred | HTTPS or reachable LAN endpoint | CLI. |
| opencode | Vendor preferred | HTTPS, VPN, or reachable LAN endpoint | CLI. |
| Strict vendor/env runner | Vendor required | Env-provided endpoint | Compatibility stress profile, not a product target. |
| Artifact-oriented CLI runner | Vendor required | Env-provided endpoint | CLI plus artifacts. |

The primary targets are programming-agent CLI tools. Strict sandbox-style behavior is retained as a compatibility stress profile, but commercial SaaS agent sandboxes are no longer an active v1 target.

This means the strict profile is an engineering guardrail, not a product promise. It checks that release artifacts remain self-contained, do not depend on `/home/zenz`, and can read endpoint credentials from environment variables. It does not imply support for arbitrary commercial SaaS agent platforms.

Operational setup for each CLI agent target is documented in `docs/08-cli-agent-integration.md`.

## Release Build

`tools/build_release.py` will:

1. Copy each skill into a release directory.
2. Copy `packages/ragflow-skill-runtime/src/ragflow_skill_runtime` into each skill's `scripts/_vendor/ragflow_skill_runtime`.
3. Exclude private skills and local caches.
4. Optionally run import smoke tests inside a clean temp directory.
5. Produce one folder per public skill; `tools/export_release_archives.py` creates deterministic per-skill archives.

Release artifacts must not contain:

- `dedao-*`.
- `.git`, `.venv`, `__pycache__`.
- Private config files.
- Real credentials.
- Local machine paths in examples.

## Migration Strategy

Do not move existing production skills in the first phase. Build the public suite in parallel under `ragflow-skills/`, then port tested code gradually.

Order:

1. `ragflow-skill-runtime` bootstrap and config/auth/client primitives.
2. `ragflow-query` direct mode and host-assisted evidence mode.
3. `ragflow-kb-build` build, inspect, and layered validation.
4. `ragflow-doc-to-md` passthrough, text/HTML conversion, local/remote backend hooks.
5. Cross-platform smoke matrix and release hardening.
6. Optional query `serve`, script-owned synthesis, and agentic planning.

This keeps current dedao and local RAGFlow workflows intact while the public suite matures.
