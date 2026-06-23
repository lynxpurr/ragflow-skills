# Cross-Platform Smoke Matrix

Status: implemented
Date: 2026-06-23

## Purpose

Phase 8 proves the public RAGFlow skills can run in the target programming-agent CLI environments without private paths, editable installs, required daemons, or real network access during CI-style smoke.

The matrix no longer treats commercial SaaS sandboxes as product targets. `strict-vendor-env` remains only as a stress profile for self-contained packaging and environment-based configuration.

Run the full matrix:

```bash
python3 tools/platform_smoke_matrix.py
```

Keep artifacts for inspection:

```bash
python3 tools/platform_smoke_matrix.py --work-dir /tmp/ragflow-platform-smoke
```

Run one profile:

```bash
python3 tools/platform_smoke_matrix.py --profile strict-vendor-env
```

List profiles:

```bash
python3 tools/platform_smoke_matrix.py --list-profiles
```

## Profiles

| Profile | Target | Runtime loading | Config loading | What it proves |
|---|---|---|---|---|
| `hermes-local-source` | Hermes local development | `PYTHONPATH=packages/ragflow-skill-runtime/src` | CLI flags | Source tree can run without vendoring. |
| `hermes-local-vendor` | Hermes local release artifact | `scripts/_vendor/ragflow_skill_runtime` | CLI flags | Release artifacts bootstrap from vendor. |
| `claude-code-cli` | Claude Code | `scripts/_vendor/ragflow_skill_runtime` | CLI flags | CLI-only use works without editable installs. |
| `opencode-cli` | opencode | `scripts/_vendor/ragflow_skill_runtime` | CLI flags | CLI-only use works for opencode-style programming agents. |
| `strict-vendor-env` | Strict vendor/env runner | `scripts/_vendor/ragflow_skill_runtime` | `RAGFLOW_*`, `DOC_TO_MD_*`, and `MINERU_*` environment variables | Compatibility stress profile with env-provided RAGFlow and MinerU service config. |
| `artifact-runner-cli` | Artifact-oriented CLI runner | `scripts/_vendor/ragflow_skill_runtime` | environment | Handoff, MinerU service conversion, query evidence, and validation reports are written as artifacts. |
| `openclaw-cli-v1` | OpenClaw | `scripts/_vendor/ragflow_skill_runtime` | CLI flags | V1 CLI path works while `serve` remains deferred. |

Legacy aliases are accepted for older docs and scripts:

- `saas-sandbox-https` -> `strict-vendor-env`
- `manus-artifact-cli` -> `artifact-runner-cli`

## Checked Flow

Each profile performs the same no-network smoke:

1. Build release artifacts into `dist/`.
2. Run `ragflow-doc-to-md/scripts/convert.py` in passthrough mode and verify `doc_manifest.json`.
3. For environment-config profiles, run `ragflow-doc-to-md` against fake MinerU services using `DOC_TO_MD_BACKEND=mineru` for Agent API and `DOC_TO_MD_BACKEND=mineru-sync` for synchronous multipart `/parse`.
4. Run `ragflow-kb-build/scripts/build.py --dry-run` against the handoff manifest.
5. Create a fake `kb_manifest.json` for no-network query and validation smoke.
6. Import `ragflow-query/scripts/query.py`, inject a fake `RAGFlowClient`, and run direct plus host-assisted query paths.
7. Import `ragflow-kb-build/scripts/validate.py`, inject a fake `RAGFlowClient`, and produce JSON plus Markdown validation reports.

The fake client is intentional. The matrix should verify packaging and CLI behavior rather than live RAGFlow service availability. Localhost, LAN, VPN, and HTTPS RAGFlow endpoints are all valid in real CLI-agent use when explicitly configured.

## Expected Failure Modes

| Failure | Likely cause | Fix |
|---|---|---|
| `No module named ragflow_skill_runtime` | Vendor directory missing or source path not set | Run `python3 tools/build_release.py --check`; verify `scripts/_vendor/ragflow_skill_runtime`. |
| `RAGFlow base URL is required` | Platform did not provide CLI flags or `RAGFLOW_BASE_URL` | Set `--base-url` or export `RAGFLOW_BASE_URL`. |
| `remote backend requires --remote-url` | Remote conversion was selected without `--remote-url` or `DOC_TO_MD_REMOTE_URL` | Pass `--remote-url` or export `DOC_TO_MD_REMOTE_URL`. |
| `MinerU create-task response missing task_id` | `DOC_TO_MD_BACKEND=mineru` was pointed at a service that does not match the Agent parsing API contract | Use an Agent API endpoint, or set `DOC_TO_MD_BACKEND=mineru-sync` for synchronous multipart `/parse`. |
| `manifest not found` | Handoff artifact path not preserved between steps | Pass absolute artifact paths or keep all steps in one workspace. |
| `agentic mode is not implemented` | Script-owned synthesis requested in v1 | Use `--mode agentic --host-assisted`; host agent performs synthesis. |
| Network or DNS errors in real use | RAGFlow endpoint is not reachable from the runner | Use a reachable LAN, VPN, HTTPS, or explicitly configured localhost debug endpoint and provide `RAGFLOW_API_KEY`. |

## V1 Boundary

`serve` is not required for Phase 8 and remains deferred. Platform compatibility is judged by CLI behavior, vendored runtime loading, manifest handoff, and artifact production.
