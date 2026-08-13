---
doc_type: reference
topic: release-hardening
status: reference
created: 2026-06-23
updated: 2026-08-13
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Release Hardening


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
python3 tools/consumer_acceptance.py --artifacts-dir release-artifacts --work-dir /tmp/ragflow-consumer-acceptance --overwrite
python3 tools/live_integration_check.py
```

Run these commands sequentially. Several release tools rebuild `dist/`, so parallel execution can corrupt an in-progress check.

### Failure Attribution And Focused Runtime Fixes

For a bounded runtime correction:

1. Review the source diff and run focused tests that exercise the changed contract.
2. Run `tools/build_release.py --check` and `tools/vendor_import_smoke.py` to prove the public skills receive the updated runtime.
3. When the authoring host provides the Skill Creator validator, run its `quick_validate.py` for each changed skill source and generated release skill. This is an authoring check, not a repository-bundled runtime command.
4. Run the full runtime and release hygiene suites before public release.

If the full suite or release hygiene check fails outside the changed surface, reproduce the same command on a clean `HEAD` worktree before attributing the failure. Record a clean-HEAD reproduction as existing baseline debt; do not claim it passed, hide it, or mix an unrelated repair into the bounded fix.

### Validation Environment Recovery Lesson (2026-08-06)

An isolated or linked worktree may not contain ignored release products such as
`release-artifacts/release-manifest.json`. If a baseline check fails because that
generated prerequisite is absent, classify the result as a validation-environment failure
until the environment is restored; do not infer an implementation defect from the
cascading failures.

When the exporter itself depends on the hygiene result encoded in that manifest, use a
bounded bootstrap export only to restore the prerequisite, then run the normal certified
export and require `hygiene.ok=true` with zero findings. After a feature merge, repeat the
release-facing chain on the merged target before pushing it.

Edit shared behavior in `packages/ragflow-skill-runtime/src` and public skill guidance under `skills/`. Do not edit or commit generated `dist/`, release archives, or an installed host copy as though they were source. Rebuild and validate generated artifacts, then update host installations through the normal deployment flow.

### MinerU CLI Acceptance Gate

When a local MinerU CLI is available, verify the auto-discovery path:

```bash
MINERU_CLI_PATH=/path/to/mineru \
MINERU_CLI_BACKEND=pipeline \
python3 skills/ragflow-doc-to-md/scripts/convert.py \
  --input <test-file> \
  --output /tmp/ragflow-mineru-cli-real-test \
  --backend auto \
  --json
```

Confirm:
- `doc_manifest.json` is produced.
- `documents/*.md` exists and is non-empty.
- `quality_report.json` exists.
- The output identifies `backend: mineru-cli` (not falling through to builtin passthrough).

If no MinerU CLI is available on the test host, `consumer_acceptance.py` still validates the CLI path through a fake MinerU binary — this proves packaging correctness. Real end-to-end CLI conversion should be run on a host with `mineru` installed before tagging the release.

### MinerU CLI Discovery Lesson (2026-06-24)

`command -v mineru` alone is not a reliable existence check. MinerU is commonly installed inside a dedicated virtual environment (`~/tools/mineru/bin/mineru`, `~/.venv/mineru/bin/mineru`) that is invisible to the system PATH, `pip list`, and `import mineru` from the system Python interpreter. Always fall through to a broad filesystem search before reporting "not found." See `docs/reference/cli-agent-integration.md#mineru-cli-localization` for the progressive discovery protocol.

The hygiene check rebuilds `dist/` and verifies:

- only the four public skills are present in the release artifact;
- each skill has `SKILL.md` with only `name` and `description` frontmatter;
- each skill vendors `scripts/_vendor/ragflow_skill_runtime`;
- unused optional resource directories such as empty `agents/` and `references/` are omitted from release artifacts;
- no local config, cache, bytecode, secret-like, private-workflow, OPC, personal path, or localhost-only RAGFlow defaults are present in release artifacts;
- public source directories under `skills/`, `packages/ragflow-skill-runtime/src/`, and `tools/` do not contain private or non-portable references;
- schema identity, rename governance, and Hermes/OpenClaw release-archive forward-test prompt templates remain covered by static subreports.

### Public Documentation And Candidate Hygiene Boundaries

Treat `docs/` as a tracked public documentation surface. New or relocated public
documents must follow the repository taxonomy, carry lifecycle metadata, be registered
in `docs/document-registry.json`, pass link and lifecycle validation, and contain only
sanitized, durable information. Local private requirement and review trees such as the
ignored `reqs/` directory are not public documentation sources and must not be moved or
copied into `docs/` as a batch.

When a private record contains a conclusion that public maintainers need, write a new,
focused public summary instead of publishing the private record. The summary needs a
public owner and consumer, must omit machine paths, credentials, private endpoints,
live identifiers, raw logs, and temporary evidence locations, and must not preserve
private authorization or operational instructions. Public documents must not link to an
ignored private record as their authority.

The two hygiene commands answer different questions:

- `python3 tools/release_hygiene_check.py` is the required release gate. It validates
  generated artifacts, intended public source roots, document lifecycle, schemas, and
  other release inventories. A passing result supports the public release path; it is
  not a claim that every Git candidate is clean.
- `python3 tools/public_hygiene_surface_check.py` is a standalone, fail-closed Git
  candidate audit. It inspects tracked, staged, and non-ignored untracked candidates and
  also classifies unsafe file types and credential-context entropy. It excludes declared
  private and generated roots, including `reqs/`, `dist/`, `release-artifacts/`, and
  `output/`.

Do not weaken either checker to make their results agree. Classify a standalone finding
against its actual surface: correct current public source when authorized, preserve
immutable history when explicitly accepted, and keep private material outside the public
documentation and release boundaries.

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

Source of truth: edit public skills under `skills/`. The `dist/` tree is a generated
release artifact rebuilt by `tools/build_release.py` and
`tools/export_release_archives.py`; do not edit `dist/` by hand. If a generated
`dist/<skill>/SKILL.md` differs from `skills/<skill>/SKILL.md`, update the source skill
under `skills/` and rerun the release tooling.

## Optional Runtime Wheel

The canonical public release path is still the per-skill archive export above. Wheel
packaging is an optional adapter gate for hosts that can install Python packages. The
current wheel scope is `ragflow-skill-runtime` only; public skill entrypoint wheels are not
part of the default release path.

To verify the runtime wheel without network access or editable installs:

```bash
python3 tools/wheel_packaging_smoke.py --work-dir /tmp/ragflow-wheel-smoke --overwrite
```

The smoke builds `ragflow-skill-runtime`, installs the produced wheel with `--no-index`
and `--no-deps`, then imports `ragflow_skill_runtime` from the installed location. It uses
a temporary venv when available and falls back to an isolated `--target` install on
minimal Ubuntu hosts without `python3-venv`.

To export a smoke-validated runtime wheel artifact and manifest:

```bash
python3 tools/export_runtime_wheel.py
```

The exporter runs the wheel smoke first, copies the validated wheel into
`release-artifacts/wheels/`, and writes `runtime-wheel-manifest.json` with the wheel
checksum and smoke summary. Do not commit generated wheel artifacts.

## Live Integration

`tools/live_integration_check.py` is opt-in. It exits successfully with `skipped: true` unless all required settings are present:

```bash
RAGFLOW_BASE_URL=https://ragflow.example.test \
RAGFLOW_API_KEY=... \
RAGFLOW_DATASET_ID=... \
python3 tools/live_integration_check.py
```

Use it before a public release when a reachable RAGFlow endpoint is available.

For a stronger disposable-KB check through the released artifacts, use:

```bash
python3 tools/consumer_acceptance.py --artifacts-dir release-artifacts --work-dir /tmp/ragflow-consumer-acceptance-live --overwrite --live-build
```

This path creates a temporary RAGFlow dataset, uploads one Markdown document, waits for parsing, validates retrieval, and runs direct plus host-assisted query checks. It depends on the configured RAGFlow embedding provider being usable; provider billing or quota failures are infrastructure failures, not release artifact packaging failures.

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
- `ragflow-doc-to-md/references/host-agent-setup.md`
- `ragflow-doc-to-md/references/user-onboarding-prompt.md`
- `ragflow-kb-build/templates/ragflow-config.example.yaml`
- `ragflow-kb-build/references/host-agent-setup.md`
- `ragflow-kb-build/references/user-onboarding-prompt.md`
- `ragflow-kb-build/templates/validation-queries.example.json`
- `ragflow-query/templates/ragflow-config.example.yaml`
- `ragflow-query/references/host-agent-setup.md`
- `ragflow-query/references/user-onboarding-prompt.md`
- `ragflow-query/templates/host-assisted-response.example.json`

These examples cover host-agent configuration, copy-paste user onboarding prompts, host-agent E2E preparation, the handoff manifest, validation query set, and host-assisted evidence payload without shipping private datasets or real credentials.

## Agents Metadata Decision

Do not add `agents/openai.yaml` in v1. The suite targets Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent CLI tools, so the first release keeps platform-neutral `SKILL.md` plus scripts as the canonical interface.

Add `agents/openai.yaml` later only when a target marketplace or host UI requires it. When adding it, generate one file per public skill from the current `SKILL.md` and validate it against the target host schema.
