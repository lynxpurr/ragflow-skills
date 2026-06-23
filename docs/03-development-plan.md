# RAGFlow Skills Phased Development Plan

Status: active roadmap
Date: 2026-06-22

## Objective

Implement a cross-platform public RAGFlow skill suite in the current workspace:

- `ragflow-doc-to-md`
- `ragflow-kb-build`
- `ragflow-query`
- shared `ragflow-skill-runtime`

The suite must be self-contained at release time and usable from Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent CLI tools.

Commercial SaaS agent sandboxes are excluded from the active public-skill roadmap. The user's own SaaS platform should implement document parsing, KB generation, validation, and retrieval as native backend capabilities, not by delegating first-class product workflows to portable skill scripts.

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
- Phase 12 CLI agent integration polish, including host-agent config templates and MinerU service backend
- High-value roadmap Phase 13 document quality and segmentation MVP
- High-value roadmap Phase 14 read-only RAGFlow diagnostics MVP

Partially completed:

- Phase 3 `ragflow-query`
  - Direct retrieval CLI exists.
  - `--mode auto` currently falls back conservatively to direct mode.
  - Host-assisted evidence return exists.
  - V1 scope is CLI-only; `serve` and script-owned agentic planning/synthesis are deferred.

Near-term priority correction:

- The next public-suite milestone is not private dedao bridging.
- RC2 validated the CLI-agent target-scope changes and unified service config hardening.
- The next milestone is RC3 with the default profile API-payload fix discovered during Hermes live E2E.
- Platform work should stay focused on Hermes, OpenClaw, Claude Code, opencode, and CLI-style runners.
- Post-v0.1 high-value feature work is tracked in `docs/09-high-value-feature-roadmap.md`, beginning with Phase 13 document quality and segmentation.

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

- No hardcoded personal home-directory defaults.
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
- [x] Add `--host-assisted` response shape for host-agent synthesis.
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

- [x] Passthrough mode works in a clean strict vendor/env environment.
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
- [x] opencode CLI smoke: vendored runtime and CLI-only execution.
- [x] Strict vendor/env simulation: no editable install, env-provided RAGFlow config.
- [x] Artifact-oriented CLI smoke: CLI produces files in a declared output directory.
- [x] OpenClaw v1 smoke: document and test CLI-only usage while `serve` is deferred.
- [x] Document failure modes and workarounds for config, auth, and network reachability.

Invocation:

```bash
python3 tools/platform_smoke_matrix.py
python3 tools/platform_smoke_matrix.py --work-dir /tmp/ragflow-platform-smoke
python3 tools/platform_smoke_matrix.py --profile strict-vendor-env
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

- [x] Add `tools/consumer_acceptance.py` for clean-consumer artifact validation.
- [x] Run no-network consumer acceptance from local RC1 artifacts.
- [x] Run one external install trial from GitHub Release artifacts on a clean agent workspace.
- [x] Add opt-in `--live-build` gate for disposable KB build, smoke validation, and direct/host-assisted query.
- [x] Cut `v0.1.0-rc2` from updated `develop`; RC1 predates the final CLI-agent target refocus.
- [x] Run the stronger live RAGFlow endpoint check against a disposable test KB.
- [x] Fix or document any RC1 findings on `develop`.
- [x] Decide whether stable `v0.1.0` can reuse the RC1 source commit or needs a new release commit. It needs a new release commit and RC2.
- [x] Promote the chosen release commit to `main`.
- [x] Tag and publish stable `v0.1.0` with refreshed artifacts.

Exit criteria:

- Stable artifacts are downloadable from GitHub Release without repository context.
- At least one real external consumer path has been exercised.
- `main` represents the latest stable public skill suite.

## Phase 12: CLI Agent Integration Polish

Goal: make the public suite feel native in Hermes, OpenClaw, Claude Code, opencode, and similar configurable CLI agent environments.

Tasks:

- [x] Add `docs/08-cli-agent-integration.md`.
- [x] Remove remaining SaaS target wording from public `SKILL.md` files.
- [x] Add environment-variable configuration for `ragflow-doc-to-md` remote conversion.
- [x] Support `DOC_TO_MD_BACKEND`, `DOC_TO_MD_REMOTE_URL`, `DOC_TO_MD_REMOTE_API_KEY`, and `DOC_TO_MD_TIMEOUT`.
- [x] Add fake remote converter tests for CLI-agent doc conversion.
- [x] Add a platform smoke profile or check that exercises remote converter configuration without external network dependency.
- [x] Decide whether MinerU remains a generic remote converter contract in v1 or gets a named `mineru` adapter in v0.2. Decision: MinerU is a named service backend using `MINERU_*` config.
- [x] Add `mineru` backend support to `ragflow-doc-to-md`.
- [x] Add `mineru-sync` backend support for self-hosted synchronous multipart `/parse` services on localhost, LAN, VPN, or HTTPS.
- [x] Add shared `templates/ragflow-config.example.yaml` to each public skill.
- [x] Add `references/host-agent-setup.md` to each public skill so Hermes/OpenClaw-style agents can prepare config and E2E checks from the released skill itself.
- [x] Support unified config files for `ragflow`, `doc_to_md`, and `mineru` sections.
- [x] Support `${ENV_VAR}` substitution in lightweight JSON/YAML config files.
- [x] Document recommended host-agent config locations for Hermes, OpenClaw, Claude Code, and opencode.
- [x] Make endpoint guidance remote-first: RAGFlow and MinerU normally live on LAN, VPN, or HTTPS endpoints.
- [x] Preserve config-file `timeout` and `verify_ssl` values when `.local` files or CLI overrides only set credentials.
- [x] Wire `verify_ssl` config through to the HTTP client.
- [x] Clean empty release artifact directories such as unused `agents/` or `references/`.
- [x] Run design/code self-check and update architecture, integration, release, and roadmap docs.
- [x] Regenerate release archives and publish `v0.1.0-rc2`.

Exit criteria:

- All public examples use Hermes/OpenClaw/Claude Code/opencode wording.
- Raw-document conversion can be configured through environment variables, matching RAGFlow config ergonomics.
- The no-network smoke suite covers the remote and MinerU service conversion paths.
- Host-agent config templates ship without real credentials and do not encourage storing local config in skill folders.
- RC2 artifacts represent the final v1 target scope.

## Phase 13: RC2 Release and Stable Promotion

Goal: cut a refreshed release candidate from the current CLI-agent-focused source and prepare stable `v0.1.0`.

Tasks:

- [x] Run the full pre-release command list from `docs/06-release-hardening.md`.
- [x] Export refreshed per-skill archives and `release-manifest.json`.
- [x] Run clean consumer acceptance from local refreshed artifacts.
- [x] Publish `v0.1.0-rc2` as a GitHub prerelease.
- [x] Run consumer acceptance against the GitHub `v0.1.0-rc2` assets.
- [x] Run Hermes-assisted live RAGFlow check against a disposable test KB.
- [x] Record live finding: default profile `parser_config.__language__` leaked into RAGFlow dataset create payload and caused API `code: 101`.
- [x] Record live infrastructure waiver candidate: Tongyi embedding provider was unavailable because of overdue payment, blocking parse completion after dataset creation and upload.
- [x] Merge or promote the selected release commit to `main`.
- [x] Tag and publish stable `v0.1.0`.

Exit criteria:

- RC2 artifacts are downloadable and self-contained.
- Local and GitHub consumer acceptance paths pass.
- Stable promotion decision is based on the refreshed CLI-agent scope, not RC1.
- RC2 is not promoted directly because Hermes live E2E found a default profile payload bug.

## Phase 14: RC3 Fix Candidate

Goal: fix Hermes live-E2E findings, refresh artifacts, and publish a release candidate suitable for stable promotion after live infrastructure is healthy or explicitly waived.

Tasks:

- [x] Filter internal `parser_config.__*` keys from RAGFlow dataset API payloads while preserving them in manifests.
- [x] Add a regression test for default-profile internal metadata filtering.
- [x] Add a release-artifact consumer acceptance check for default-profile API-payload filtering.
- [x] Run the full pre-release command list from `docs/06-release-hardening.md`.
- [x] Commit and push the fix on `develop`.
- [x] Export refreshed per-skill archives and `release-manifest.json` from the fix commit.
- [x] Run clean consumer acceptance from local refreshed artifacts.
- [x] Publish `v0.1.0-rc3` as a GitHub prerelease.
- [x] Run consumer acceptance against the GitHub `v0.1.0-rc3` assets.
- [x] Re-run Hermes live E2E after the embedding provider is usable.

Exit criteria:

- Default profiles no longer send internal metadata fields to RAGFlow API.
- RC3 artifacts are downloadable and self-contained.
- Stable promotion has a passing disposable live E2E.

## Phase 15: Host-Agent User Onboarding Prompt

Goal: ship a standard copy-paste prompt that end users can give to Hermes, OpenClaw, Claude Code, opencode, or another controllable CLI agent so the host agent can gather RAGFlow/MinerU service settings, configure the skills, and run validation.

Tasks:

- [x] Add `references/user-onboarding-prompt.md` to each public skill.
- [x] Link the prompt from each public `SKILL.md`.
- [x] Link the prompt from each `references/host-agent-setup.md`.
- [x] Add a release-build assertion that every public skill artifact includes the prompt.
- [x] Record the prompt as a public release example in `docs/06-release-hardening.md`.
- [x] Forward-test the prompt with Hermes and record the MinerU protocol distinction found during onboarding.
- [x] Clarify that `mineru` / `mineru-agent` target MinerU Agent API, while `mineru-sync` / `mineru-local` target synchronous multipart `/parse` services.
- [x] Forward-test the prompt with OpenClaw and tighten guidance so synchronous multipart MinerU services use `doc_to_md.backend: mineru-sync`, not `mineru`.
- [x] Clarify that host agents must not patch release-artifact `scripts/_vendor`; source runtime changes must be made in `packages/ragflow-skill-runtime` and re-vendored.
- [x] Add the OpenClaw user-level config path `~/.config/openclaw/ragflow/config.local.yaml` observed during second-round validation.

Exit criteria:

- The prompt is included in every future public skill artifact.
- The prompt instructs host agents to ask only for missing RAGFlow/MinerU endpoint and key values.
- The prompt instructs host agents to keep secrets out of skill folders, repositories, release artifacts, and reports.
- The prompt guides host agents through no-network smoke, optional MinerU conversion, and disposable RAGFlow live E2E.
- MinerU onboarding distinguishes Agent API and synchronous multipart `/parse` services before choosing a backend.
- Config templates default to `doc_to_md.backend: auto`; `mineru` and `mineru-sync` are opt-in after protocol compatibility is confirmed.

## Phase 16: Document Quality and Segmentation MVP

Goal: begin the v0.2 high-value roadmap with deterministic handoff quality gates and long-document segmentation.

Tasks:

- [x] Add `doc_quality.py` with quality report dataclasses and gate statuses.
- [x] Check Markdown existence, emptiness, missing local image references, and conversion warnings.
- [x] Make `ragflow-doc-to-md` write `quality_report.json` during normal conversion.
- [x] Add `quality_gate` and `quality_report` as optional fields in `doc_manifest.json`.
- [x] Add `ragflow-doc-to-md inspect` to regenerate quality reports from existing handoffs.
- [x] Add `doc_segment.py` with segmentation plan dataclasses and threshold validation.
- [x] Add `ragflow-doc-to-md segment-plan`.
- [x] Add `ragflow-doc-to-md split` to materialize segment Markdown files.
- [x] Add `ragflow-kb-build --allow-blocked`; block `quality_gate.status: BLOCKED` by default.
- [x] Add unit and CLI coverage for quality reports, blocked manifests, segment planning, and split output.
- [x] Add clean-consumer acceptance checks for quality report and segmentation command availability.
- [ ] Add optional manifest rewrite/package mode for split outputs after the basic segment-directory path is validated.

Exit criteria:

- Empty or broken Markdown handoffs are prevented from reaching live RAGFlow upload unless the user explicitly accepts the risk.
- Long Markdown files can be split into `segments/*.md`, then ingested by passing the segment directory to `ragflow-kb-build --input`.
- Existing v0.1 command surfaces and manifests remain backward-compatible.

## Phase 17: Read-Only RAGFlow Diagnostics MVP

Goal: expose safe public diagnostics for common RAGFlow ingestion and KB-state problems without requiring private database or Elasticsearch access.

Tasks:

- [x] Add `diagnostics.py` with `ragflow_kb_diagnostic_report_v1`.
- [x] Add short dataset/document ID checks.
- [x] Add duplicate-name and suffix-fragment detection.
- [x] Add stuck parse, failed parse, and zero-chunk diagnostics.
- [x] Add safe `RAGFlowClient` helpers for dataset detail, dataset deletion, document deletion, and paginated document listing.
- [x] Add `ragflow-kb-build/scripts/diagnose.py`.
- [x] Add `ragflow-kb-build/scripts/probe.py`.
- [x] Add JSON and Markdown diagnostic report output.
- [x] Add unit, CLI, and clean-consumer help coverage.
- [ ] Add live disposable probe tests where credentials are present.
- [ ] Add append, parse-only-new-documents, and cleanup preview/confirm commands.

Exit criteria:

- Host agents can explain short-ID, duplicate-name, parse-state, and zero-chunk symptoms from public artifacts.
- `probe.py` and `diagnose.py` are read-only by default and do not mutate RAGFlow.
- High-risk maintenance commands remain deferred until the diagnostic surface is stable.

## Definition of Done

The public suite is ready for first external use when:

- [x] Three public skills have concise `SKILL.md` files.
- [x] `ragflow-skill-runtime` contains no private environment assumptions.
- [x] Release artifacts vendor `ragflow_skill_runtime`.
- [x] `ragflow-query ask --mode direct` works from a clean release artifact.
- [x] `ragflow-kb-build build` produces `kb_manifest.json`.
- [x] `ragflow-kb-build validate --level smoke` works.
- [x] `ragflow-doc-to-md --mode passthrough` produces `doc_manifest.json`.
- [x] Strict vendor/env simulation works without daemon or editable install.
- [x] Release hygiene check blocks private paths, private workflow references, and missing vendored runtime.
- [x] Release archive export produces deterministic per-skill archives and checksum manifest.
- [x] Dedao skills remain private and untouched.
