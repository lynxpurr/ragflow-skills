# RAGFlow Skills Phased Development Plan

Status: active roadmap
Date: 2026-06-22

## Objective

Implement a cross-platform public RAGFlow skill suite in the current workspace:

- `ragflow-doc-to-md`
- `ragflow-kb-build`
- `ragflow-query`
- shared `ragflow-skill-runtime`

The suite must be self-contained at release time and usable from Hermes, OpenClaw, Claude Code, and SaaS agent code sandboxes.

## Current Snapshot

Completed foundations:

- Phase 0 architecture skeleton
- Phase 1 runtime foundation
- Phase 2 release vendoring
- Phase 4 `ragflow-kb-build` MVP
- Phase 5 `ragflow-doc-to-md` MVP
- Phase 6 validation command consolidation
- Phase 8 cross-platform smoke matrix
- Phase 9 release hardening
- Phase 10 first release candidate validation and GitHub prerelease publication

Partially completed:

- Phase 3 `ragflow-query`
  - Direct retrieval CLI exists.
  - `--mode auto` currently falls back conservatively to direct mode.
  - Host-assisted evidence return exists.
  - V1 scope is CLI-only; `serve` and script-owned agentic planning/synthesis are deferred.

Near-term priority correction:

- The next public-suite milestone is not private dedao bridging.
- The next milestone is stable release promotion after RC1 external artifact validation.

## Phase 0: Architecture Skeleton

Goal: create the public workspace shape and capture design decisions.

Tasks:

- [x] Create `ragflow-skills/`.
- [x] Create `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/`.
- [x] Create public skill folders under `skills/`.
- [x] Create `tools/` for release packaging.
- [x] Write folder plan.
- [x] Write architecture design.
- [x] Write phased development plan.

Exit criteria:

- Folder skeleton exists.
- Architecture decisions are captured in docs.
- Existing dedao skills are untouched.

## Phase 1: `ragflow-skill-runtime` Foundation

Goal: build the portable runtime foundation and prove vendor loading works.

Tasks:

- [x] Add `packages/ragflow-skill-runtime/pyproject.toml`.
- [x] Add `ragflow_skill_runtime/__init__.py`.
- [x] Add `ragflow_skill_runtime/bootstrap.py`.
- [x] Add `ragflow_skill_runtime/config.py`.
- [x] Add `ragflow_skill_runtime/auth.py`.
- [x] Add `ragflow_skill_runtime/paths.py`.
- [x] Add `ragflow_skill_runtime/http.py`.
- [x] Add `ragflow_skill_runtime/ragflow_client.py`.
- [x] Add `ragflow_skill_runtime/manifests.py`.
- [x] Add tests for env/config loading.
- [x] Add tests for manifest validation.
- [x] Add a tiny script that imports `ragflow_skill_runtime` through vendor bootstrap.

Constraints:

- No `/home/zenz` defaults.
- No dedao imports.
- No OPC references.
- No real credentials.
- No dependency on `pip install -e` for release-mode tests.

Exit criteria:

- `python -c "import ragflow_skill_runtime"` works in development.
- A script can import vendored `ragflow_skill_runtime` from `scripts/_vendor`.
- Config can be loaded from environment and explicit path.

## Phase 2: Release Vendor Tooling

Goal: make self-contained skill artifacts repeatable.

Tasks:

- [x] Implement `tools/build_release.py`.
- [x] Copy each public skill into `dist/`.
- [x] Vendor `ragflow_skill_runtime` into each skill's `scripts/_vendor/ragflow_skill_runtime`.
- [x] Exclude caches, virtualenvs, private config, `.git`, and dedao folders.
- [x] Add `--check` mode that verifies every public script can bootstrap core.
- [x] Add release smoke test using a clean temp directory.

Exit criteria:

- `python tools/build_release.py --check` passes.
- Release artifact can run import smoke with no installed `ragflow_skill_runtime`.
- No private skills are present in release output.

## Phase 3: `ragflow-query` MVP

Goal: consolidate smart-query and agentic-rag into one portable public query skill.

Tasks:

- [x] Create `skills/ragflow-query/SKILL.md`.
- [x] Create `skills/ragflow-query/scripts/query.py`.
- [x] Add bootstrap code to `query.py`.
- [x] Implement `ask --mode direct`.
- [x] Implement normalized JSON output.
- [x] Implement `--kb`, `--kb-manifest`, and `--top-k`.
- [x] Move direct retrieval logic into `ragflow_skill_runtime/retrieval.py`.
- [x] Add `--mode auto` classification placeholder with conservative direct fallback.
- [x] Add `--host-assisted` response shape for SaaS agent synthesis.
- [ ] Add optional `serve` subcommand for local/OpenClaw use.
- [ ] Port agentic retrieval after direct mode is stable.

Validation:

- [x] Import smoke in vendor mode.
- [x] Release-style direct query smoke runs in a clean artifact with fake or reachable endpoint.
- [x] CLI help renders in release or installed-package mode.
- [x] Missing dataset or missing KB inputs fail with a clear message before network work.
- [x] Host-assisted mode returns chunks/evidence in a tested release-path smoke.

Exit criteria:

- One command can perform direct retrieval from a configured RAGFlow endpoint.
- `--mode auto|direct|agentic` command surface is stable, with current gaps explicitly documented.

## Phase 4: `ragflow-kb-build` MVP

Goal: provide public Markdown-to-RAGFlow build, inspect, and validation commands.

Tasks:

- [x] Create `skills/ragflow-kb-build/SKILL.md`.
- [x] Create `scripts/build.py`.
- [x] Create `scripts/validate.py`.
- [x] Create `scripts/inspect_kb.py`.
- [x] Add default profile templates.
- [x] Implement profile linting in `ragflow_skill_runtime/profiles.py`.
- [x] Implement dataset creation in `ragflow_skill_runtime/ragflow_client.py`.
- [x] Implement document upload and parse trigger.
- [x] Implement parse status polling.
- [x] Write `kb_manifest.json`.
- [x] Implement `validate --level smoke`.
- [x] Define placeholders for `regression` and `benchmark` levels.

Validation:

- [x] Build command validates input before touching RAGFlow.
- [x] Smoke validation checks KB exists and at least one query returns chunks.
- [x] Inspect command summarizes dataset and document parse status.

Exit criteria:

- A Markdown directory can be uploaded to RAGFlow.
- A `kb_manifest.json` is produced.
- `validate --level smoke` runs as a first-class command.

## Phase 5: `ragflow-doc-to-md` MVP

Goal: produce Markdown handoff directories without requiring local-only tools.

Tasks:

- [x] Create `skills/ragflow-doc-to-md/SKILL.md`.
- [x] Create `scripts/convert.py`.
- [x] Implement passthrough mode for existing Markdown.
- [x] Implement basic text/HTML to Markdown conversion.
- [x] Add local backend adapter for installed tools where available.
- [x] Add remote backend adapter interface.
- [x] Write `doc_manifest.json`.
- [x] Record source sha256 and conversion warnings.
- [x] Add templates for manifest examples.

Validation:

- [x] Passthrough mode works in a clean SaaS-like environment.
- [x] Missing optional converters produce clear warnings.
- [x] `doc_manifest.json` can be consumed by `ragflow-kb-build`.

Exit criteria:

- Existing Markdown can become a valid handoff bundle.
- Non-Markdown conversion is optional and backend-driven.

## Phase 6: Validation and Benchmark Consolidation

Goal: keep quality engineering as a product feature without preserving script sprawl.

Tasks:

- [x] Inventory existing benchmark and regression scripts.
- [x] Classify each as `smoke`, `regression`, `benchmark`, `legacy`, or `private`.
- [x] Move reusable metrics into `ragflow_skill_runtime/validation.py`.
- [x] Expose a stable `validate` command surface.
- [x] Support user-provided query sets.
- [x] Generate compact JSON and Markdown reports.
- [x] Keep heavy benchmark datasets out of default release unless explicitly included.

Exit criteria:

- Public validation has one stable command.
- Heavy evaluation remains available but opt-in.
- Existing quality lessons are preserved without 70+ scripts in the main public scripts directory.

## Phase 7: Query Completion and Release Readiness

Goal: close the remaining public-suite gaps in `ragflow-query` before platform-wide smoke.

Tasks:

- [x] Add release-style smoke that runs `ragflow-query ask` from a vendored artifact.
- [x] Add tested host-assisted evidence output example and fixture path.
- [x] Decide whether `serve` is part of v1; implement it or explicitly defer it from v1 scope.
- [x] Decide whether v1 agentic mode means host-assisted-only or script-owned synthesis.
- [x] Align `SKILL.md`, architecture docs, and CLI help with the chosen query v1 scope.
- [x] Add one example config or invocation pattern for direct query from a clean checkout.

Clean checkout invocation:

```bash
RAGFLOW_SKILL_RUNTIME_PATH=./packages/ragflow-skill-runtime/src \
  python skills/ragflow-query/scripts/query.py \
  --base-url https://ragflow.example.test \
  --api-key "$RAGFLOW_API_KEY" \
  ask "Question" --dataset-id ds-example --mode direct --json
```

Exit criteria:

- `ragflow-query` has an honest, tested v1 surface.
- Release artifact can perform direct retrieval smoke through the real CLI entrypoint.
- Agentic and `serve` status are no longer ambiguous.

## Phase 8: Cross-Platform Smoke Matrix

Goal: prove the suite can run across target platforms with the finalized v1 surface.

Tasks:

- [x] Add `tools/platform_smoke_matrix.py`.
- [x] Hermes local smoke: source-runtime and vendor mode.
- [x] Claude Code smoke: CLI mode with vendored core.
- [x] SaaS sandbox simulation: no pip install, no daemon, HTTPS-style base URL config.
- [x] Manus-like artifact smoke: CLI produces files in a declared output directory.
- [x] OpenClaw v1 smoke: document and test CLI-only usage while `serve` is deferred.
- [x] Document failure modes and workarounds for config, auth, and network reachability.

Invocation:

```bash
python3 tools/platform_smoke_matrix.py
python3 tools/platform_smoke_matrix.py --work-dir /tmp/ragflow-platform-smoke
python3 tools/platform_smoke_matrix.py --profile saas-sandbox-https
```

Exit criteria:

- [x] Each target has a documented invocation pattern.
- [x] Failure modes are clear and actionable.
- [x] Release artifacts pass vendor and command smoke, not just import smoke.
- [x] Full matrix is included in the regular pre-release checklist.

## Phase 9: Release Hardening

Goal: turn the public suite from an internally tested repo into a publishable external artifact.

Tasks:

- [x] Add Phase 8 matrix to the required release command list.
- [x] Produce a release checklist for private/public hygiene.
- [x] Add `tools/release_hygiene_check.py`.
- [x] Add deterministic packaging notes for per-skill artifact export.
- [x] Add sample query-set and handoff examples where they materially reduce onboarding friction.
- [x] Decide whether to add `agents/openai.yaml` metadata for the three public skills.
- [x] Add a small compatibility note for runtime loading in installed-package vs vendored mode.
- [x] Add archive creation automation with per-skill checksums.
- [x] Add opt-in live integration check for reachable RAGFlow endpoints.

Exit criteria:

- [x] A private repo clone can produce a clean external release bundle repeatably.
- [x] Public examples and artifacts are sufficient for first external users.
- [x] Archive creation is fully automated.

## Deferred: Private Dedao Bridge

Goal: let private dedao workflows feed public skills without making public skills depend on dedao.

Tasks:

- [ ] Leave current dedao skills in place.
- [ ] Add private adapter only if needed.
- [ ] Make dedao private output match `doc_manifest.json` handoff shape.
- [ ] Do not add dedao references to public SKILL.md files.

Exit criteria:

- Dedao workflows remain private.
- Public skills can consume dedao-produced handoff bundles as ordinary Markdown handoffs.

## Backlog

- [ ] Formal JSON Schema for manifests after multiple independent consumers exist.
- [ ] Wheel-based release path for platforms that support package installation.
- [ ] Remote document conversion service client.
- [ ] LLM provider abstraction beyond OpenAI-compatible APIs.
- [ ] Reranker provider abstraction.
- [ ] Optional web UI or hosted API wrapper.

## Phase 10: First Release Candidate Validation

Goal: validate a first external release candidate before promotion to `main`.

Tasks:

- [x] Add `docs/07-first-release.md`.
- [x] Generate release archives and checksum manifest.
- [x] Complete fresh-agent forward test from release artifacts.
- [x] Run live integration against a reachable test RAGFlow endpoint, or record explicit skip.
- [x] Tag `v0.1.0-rc1` after RC docs and forward-test results are committed.
- [x] Publish GitHub prerelease `v0.1.0-rc1` with all three skill archives and `release-manifest.json`.

Exit criteria:

- Release artifacts can be used without repository context.
- Live endpoint status is explicit.
- RC findings are either fixed or tracked before stable release.

## Phase 11: Stable Release Promotion

Goal: promote RC1 into a stable `v0.1.0` release only after the external artifact path is trustworthy.

Tasks:

- [ ] Run one external install trial from GitHub Release artifacts on a clean agent workspace.
- [ ] Run the stronger live RAGFlow endpoint check against a disposable test KB, or record an explicit stable-release waiver.
- [ ] Fix or document any RC1 findings on `develop`.
- [ ] Decide whether stable `v0.1.0` can reuse the RC1 source commit or needs a new release commit.
- [ ] Promote the chosen release commit to `main`.
- [ ] Tag and publish stable `v0.1.0` with refreshed artifacts.

Exit criteria:

- Stable artifacts are downloadable from GitHub Release without repository context.
- At least one real external consumer path has been exercised.
- `main` represents the latest stable public skill suite.

## Definition of Done

The public suite is ready for first external use when:

- [x] Three public skills have concise `SKILL.md` files.
- [x] `ragflow-skill-runtime` contains no private environment assumptions.
- [x] Release artifacts vendor `ragflow_skill_runtime`.
- [x] `ragflow-query ask --mode direct` works from a clean release artifact.
- [x] `ragflow-kb-build build` produces `kb_manifest.json`.
- [x] `ragflow-kb-build validate --level smoke` works.
- [x] `ragflow-doc-to-md --mode passthrough` produces `doc_manifest.json`.
- [x] SaaS sandbox simulation works without daemon or editable install.
- [x] Release hygiene check blocks private paths, private workflow references, and missing vendored runtime.
- [x] Release archive export produces deterministic per-skill archives and checksum manifest.
- [x] Dedao skills remain private and untouched.
