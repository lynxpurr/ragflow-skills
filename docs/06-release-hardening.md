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
```

The hygiene check rebuilds `dist/` and verifies:

- only the three public skills are present in the release artifact;
- each skill has `SKILL.md` with only `name` and `description` frontmatter;
- each skill vendors `scripts/_vendor/ragflow_skill_runtime`;
- no local config, cache, bytecode, secret-like, dedao, OPC, personal path, or localhost-only RAGFlow defaults are present in release artifacts;
- public source directories under `skills/`, `packages/ragflow-skill-runtime/src/`, and `tools/` do not contain private or non-portable references.

## Artifact Export

Build the self-contained skill folders:

```bash
python3 tools/build_release.py --dist dist
```

Export one archive per skill from the `dist/` directory:

```bash
mkdir -p release-artifacts
tar --sort=name --mtime='UTC 2026-01-01' --owner=0 --group=0 --numeric-owner \
  -C dist -czf release-artifacts/ragflow-doc-to-md.tar.gz ragflow-doc-to-md
tar --sort=name --mtime='UTC 2026-01-01' --owner=0 --group=0 --numeric-owner \
  -C dist -czf release-artifacts/ragflow-kb-build.tar.gz ragflow-kb-build
tar --sort=name --mtime='UTC 2026-01-01' --owner=0 --group=0 --numeric-owner \
  -C dist -czf release-artifacts/ragflow-query.tar.gz ragflow-query
```

Do not commit `dist/` or `release-artifacts/`.

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
- `ragflow-kb-build/templates/validation-queries.example.json`
- `ragflow-query/templates/host-assisted-response.example.json`

These examples cover the handoff manifest, validation query set, and host-assisted evidence payload without shipping private datasets.

## Agents Metadata Decision

Do not add `agents/openai.yaml` in v1. The suite targets Hermes, OpenClaw, Claude Code, and generic SaaS sandboxes, so the first release keeps platform-neutral `SKILL.md` plus scripts as the canonical interface.

Add `agents/openai.yaml` later only when a target marketplace or host UI requires it. When adding it, generate one file per public skill from the current `SKILL.md` and validate it against the target host schema.
