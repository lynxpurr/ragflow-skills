# Release Hardening

Status: active
Date: 2026-06-23

## Release Checklist

Run from the repository root on `develop` before cutting a release:

```bash
PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -v

python3 tools/build_release.py --check
python3 tools/vendor_import_smoke.py
python3 tools/platform_smoke_matrix.py
python3 tools/release_hygiene_check.py
python3 tools/export_release_archives.py
python3 tools/live_integration_check.py
```

Run these commands sequentially. Several release tools rebuild `dist/`, so parallel execution can corrupt an in-progress check.

The hygiene check rebuilds `dist/` and verifies:

- only the three public skills are present in the release artifact;
- each skill has `SKILL.md` with only `name` and `description` frontmatter;
- each skill vendors `scripts/_vendor/ragflow_skill_runtime`;
- unused optional resource directories such as empty `agents/` and `references/` are omitted from release artifacts;
- no local config, cache, bytecode, secret-like, dedao, OPC, personal path, or localhost-only RAGFlow defaults are present in release artifacts;
- public source directories under `skills/`, `packages/ragflow-skill-runtime/src/`, and `tools/` do not contain private or non-portable references.

## Artifact Export

Export deterministic per-skill archives:

```bash
python3 tools/export_release_archives.py
```

The exporter rebuilds `dist/`, runs the hygiene gate, writes one archive per public skill, and emits `release-artifacts/release-manifest.json` with SHA-256 checksums.

Use custom paths when needed:

```bash
python3 tools/export_release_archives.py --dist dist --output-dir release-artifacts
```

Do not commit `dist/` or `release-artifacts/`.

## Live Integration

`tools/live_integration_check.py` is opt-in. It exits successfully with `skipped: true` unless all required settings are present:

```bash
RAGFLOW_BASE_URL=https://ragflow.example.test \
RAGFLOW_API_KEY=... \
RAGFLOW_DATASET_ID=... \
python3 tools/live_integration_check.py
```

Use it before a public release when a reachable RAGFlow endpoint is available.

## Runtime Compatibility

Public scripts load `ragflow_skill_runtime` in this order:

1. `RAGFLOW_SKILL_RUNTIME_PATH` for local development.
2. `scripts/_vendor/ragflow_skill_runtime` inside each release skill.
3. `../_shared/ragflow_skill_runtime` for bundle-level shared deployments.
4. Normal Python import paths for platforms that install `ragflow-skill-runtime`.

Release artifacts must work through path 2. Editable installs are optional convenience only.

## Public Examples

The public examples are intentionally small and live inside the skills they support:

- `ragflow-doc-to-md/templates/doc_manifest.example.json`
- `ragflow-doc-to-md/templates/ragflow-config.example.yaml`
- `ragflow-kb-build/templates/ragflow-config.example.yaml`
- `ragflow-kb-build/templates/validation-queries.example.json`
- `ragflow-query/templates/ragflow-config.example.yaml`
- `ragflow-query/templates/host-assisted-response.example.json`

These examples cover host-agent configuration, the handoff manifest, validation query set, and host-assisted evidence payload without shipping private datasets or real credentials.

## Agents Metadata Decision

Do not add `agents/openai.yaml` in v1. The suite targets Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent CLI tools, so the first release keeps platform-neutral `SKILL.md` plus scripts as the canonical interface.

Add `agents/openai.yaml` later only when a target marketplace or host UI requires it. When adding it, generate one file per public skill from the current `SKILL.md` and validate it against the target host schema.
