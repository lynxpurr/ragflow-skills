# Cross-Platform Smoke Matrix

Status: implemented
Date: 2026-06-23

## Purpose

Phase 8 proves the public RAGFlow skills can run in the target agent environments without private paths, editable installs, local daemon assumptions, or real network access during CI-style smoke.

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
python3 tools/platform_smoke_matrix.py --profile saas-sandbox-https
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
| `saas-sandbox-https` | SaaS agent sandbox | `scripts/_vendor/ragflow_skill_runtime` | `RAGFLOW_BASE_URL` and `RAGFLOW_API_KEY` | No daemon, no local socket, HTTPS-style config. |
| `manus-artifact-cli` | Manus-like artifact runner | `scripts/_vendor/ragflow_skill_runtime` | environment | Handoff, query evidence, and validation reports are written as artifacts. |
| `openclaw-cli-v1` | OpenClaw | `scripts/_vendor/ragflow_skill_runtime` | CLI flags | V1 CLI path works while `serve` remains deferred. |

## Checked Flow

Each profile performs the same no-network smoke:

1. Build release artifacts into `dist/`.
2. Run `ragflow-doc-to-md/scripts/convert.py` in passthrough mode and verify `doc_manifest.json`.
3. Run `ragflow-kb-build/scripts/build.py --dry-run` against the handoff manifest.
4. Create a fake `kb_manifest.json` for no-network query and validation smoke.
5. Import `ragflow-query/scripts/query.py`, inject a fake `RAGFlowClient`, and run direct plus host-assisted query paths.
6. Import `ragflow-kb-build/scripts/validate.py`, inject a fake `RAGFlowClient`, and produce JSON plus Markdown validation reports.

The fake client is intentional. Local socket listeners are not portable to managed code sandboxes, and the matrix should verify packaging and CLI behavior rather than RAGFlow service availability.

## Expected Failure Modes

| Failure | Likely cause | Fix |
|---|---|---|
| `No module named ragflow_skill_runtime` | Vendor directory missing or source path not set | Run `python3 tools/build_release.py --check`; verify `scripts/_vendor/ragflow_skill_runtime`. |
| `RAGFlow base URL is required` | Platform did not provide CLI flags or `RAGFLOW_BASE_URL` | Set `--base-url` or export `RAGFLOW_BASE_URL`. |
| `manifest not found` | Handoff artifact path not preserved between steps | Pass absolute artifact paths or keep all steps in one workspace. |
| `agentic mode is not implemented` | Script-owned synthesis requested in v1 | Use `--mode agentic --host-assisted`; host agent performs synthesis. |
| Network or DNS errors in real use | RAGFlow endpoint is not reachable from the sandbox | Use an HTTPS gateway reachable by the platform and provide `RAGFLOW_API_KEY`. |

## V1 Boundary

`serve` is not required for Phase 8 and remains deferred. Platform compatibility is judged by CLI behavior, vendored runtime loading, manifest handoff, and artifact production.
