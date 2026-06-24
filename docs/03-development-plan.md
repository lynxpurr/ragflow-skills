# RAGFlow Skills Phased Development Plan

Status: active roadmap
Date: 2026-06-24

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
- High-value roadmap Phase 15 benchmark validation MVP
- High-value roadmap Phase 16 profile engineering MVP
- High-value roadmap Phase 17 neutral routing MVP
- High-value roadmap Phase 18 agentic observability MVP
- High-value roadmap Phase 19 query diagnostics MVP

Partially completed:

- Phase 3 `ragflow-query`
  - Direct retrieval CLI exists.
  - `--mode auto` now uses user-owned routing config when provided; without routing config or with explicit KB inputs, it remains direct retrieval.
  - Host-assisted evidence return includes evidence weights and optional trace reports.
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
- [x] Add `--mode auto` classification placeholder with conservative direct fallback. Superseded by Phase 20 routing config support.
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
- [x] Add `mineru-cli` backend support for locally installed MinerU binaries and `auto` CLI preference.
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
- The prompt instructs host agents to ask only for missing RAGFlow/MinerU endpoint, key, or local CLI path values.
- The prompt instructs host agents to keep secrets out of skill folders, repositories, release artifacts, and reports.
- The prompt guides host agents through no-network smoke, optional MinerU conversion, and disposable RAGFlow live E2E.
- MinerU onboarding distinguishes local CLI, Agent API, and synchronous multipart `/parse` before choosing a backend.
- Config templates default to `doc_to_md.backend: auto`; local `mineru-cli` is auto-preferred when available, while `mineru` and `mineru-sync` remain explicit options after protocol compatibility is confirmed.

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
- [x] Add `ragflow-kb-build/scripts/append.py` with safe non-mutating default plans.
- [x] Add live-preview support for append upload-before snapshots.
- [x] Make append execution parse only newly uploaded document IDs by default.
- [x] Add `ragflow-kb-build/scripts/cleanup.py` with non-mutating previews.
- [x] Require explicit dataset ID and KB name confirmation before cleanup execution.
- [ ] Add live disposable probe tests where credentials are present.

Exit criteria:

- Host agents can explain short-ID, duplicate-name, parse-state, and zero-chunk symptoms from public artifacts.
- `probe.py` and `diagnose.py` are read-only by default and do not mutate RAGFlow.
- `append.py` does not mutate RAGFlow unless `--execute` is explicit.
- `cleanup.py` does not delete a dataset unless `--execute` and exact confirmation flags are provided.

## Phase 18: Benchmark Validation MVP

Goal: promote `ragflow-kb-build validate` from smoke/regression checks to deterministic retrieval-quality gates.

Tasks:

- [x] Add qrels loading for explicit lists and compact query-to-document mappings.
- [x] Add benchmark ranking metrics: hit rate, MRR, precision@k, recall@k, nDCG@k, MAP@k, empty-result rate, and supporting-document coverage.
- [x] Add query-type breakdown via query `metadata.type`.
- [x] Add `validate --level benchmark --queries ... --qrels ...`.
- [x] Add optional `--gate-config` threshold checks.
- [x] Add optional `--baseline-report` metric delta comparison.
- [x] Add benchmark JSON and Markdown report sections.
- [x] Add public example templates for benchmark queries, qrels, and gates.
- [x] Add unit and CLI coverage with fake retrieval clients.

Exit criteria:

- A user can run a public benchmark gate without an LLM key and see ranking metrics, failed thresholds, query-type breakdowns, and baseline deltas.
- Existing smoke and regression validation behavior remains backward-compatible.

## Phase 19: Profile Engineering MVP

Goal: make chunk profile selection explicit, explainable, and testable before live upload.

Tasks:

- [x] Add `ragflow-kb-build/scripts/profile.py`.
- [x] Implement `profile lint` with deterministic consistency, overlap, parser-key, and metadata checks.
- [x] Implement `profile explain` with filtered RAGFlow API payload output.
- [x] Implement rule-based `profile recommend` for `auto`, Chinese, and English starter profiles across common document types.
- [x] Implement `profile compare` using validation report metrics from profile experiments.
- [x] Export profile utilities from `ragflow_skill_runtime`.
- [x] Add unit, CLI, release-build, clean-consumer, and platform-smoke coverage.
- [x] Update public skill docs and roadmap status.

Exit criteria:

- A user can lint or explain a profile before upload.
- A user can generate a neutral starter profile without secrets or live services.
- A user can compare profile experiment validation reports before accepting a profile change.

## Phase 20: Neutral Routing MVP

Goal: make `ragflow-query --mode auto` useful without shipping private route tables.

Tasks:

- [x] Add `ragflow_routing_config_v1` runtime dataclasses.
- [x] Add routing config loading for user-owned KB names, dataset IDs, hints, and retrieval params.
- [x] Add deterministic hint/token scoring.
- [x] Add `ragflow-query list-kbs`.
- [x] Add `ragflow-query route`.
- [x] Add `ragflow-query route-test`.
- [x] Wire `ask --mode auto` to routing config when no explicit KB input is supplied.
- [x] Preserve explicit `--dataset-id`, `--kb`, and `--kb-manifest` precedence.
- [x] Add public routing config and route-test templates.
- [x] Add unit, CLI, release-build, clean-consumer, and platform-smoke coverage.

Exit criteria:

- A user can maintain their own routing hints and run auto retrieval with deterministic route selection.
- Route regression tests run without RAGFlow network access.
- No private KB names, hints, or route tables are shipped.

## Phase 21: Agentic Observability MVP

Goal: improve host-assisted evidence quality without requiring an LLM key or script-owned synthesis.

Tasks:

- [x] Add deterministic evidence weighting for `ragflow-query ask` results.
- [x] Add `--trace-json` and `--trace-md` outputs with `ragflow_query_trace_v1`.
- [x] Add retrieval timing, selected params, route metadata, and zero-result warnings to traces.
- [x] Add `ragflow-query audit-citations` for host-generated answers.
- [x] Add `ragflow_citation_audit_v1` JSON and Markdown reports.
- [x] Add public example payloads for host-assisted output, traces, and citation audit.
- [x] Add unit, CLI, release-build, clean-consumer, and platform-smoke coverage.
- [ ] Keep script-owned LLM synthesis deferred until tracing and audit behavior is stable in real use.

Exit criteria:

- Host agents can inspect why evidence was selected.
- Host agents can preserve trace artifacts for weak retrieval debugging.
- Host-generated answers can be checked against retrieved evidence using simple numeric citations such as `[1]`.
- Existing direct, auto, and host-assisted query paths remain backward-compatible.

## Phase 22: Query Diagnostics MVP

Goal: give host agents a single offline report for explaining weak query results and unstable
host-generated answers.

Tasks:

- [x] Add `ragflow_query_diagnostic_report_v1`.
- [x] Add `ragflow-query diagnose-result`.
- [x] Diagnose zero chunks, low similarity, low evidence score, and missing expected terms.
- [x] Include trace warnings and default-route signals when trace artifacts are supplied.
- [x] Include citation-audit errors and warnings when audit artifacts are supplied.
- [x] Add JSON and Markdown diagnostic reports.
- [x] Add public example diagnostic payload.
- [x] Add unit, CLI, release-build, clean-consumer, and platform-smoke coverage.

Exit criteria:

- A host agent can diagnose saved `query.json`, `query_trace.json`, and `citation_audit.json`
  without live RAGFlow access.
- The report distinguishes hard failures from review warnings.
- Existing query output remains backward-compatible.

## Phase 23: MinerU Local CLI Backend

Goal: close the gap found by Hermes/OpenClaw validation where a host may have a working local MinerU CLI but no compatible MinerU HTTP service.

Design update:

- Original v0.1 design treated MinerU primarily as a configured external service. That remains correct for remote, LAN, VPN, and online MinerU deployments.
- The revised design adds local CLI as a third equivalent execution mode: `mineru-cli` for local binaries, `mineru` / `mineru-agent` for Agent API, and `mineru-sync` / `mineru-local` for synchronous multipart `/parse`.
- `doc_to_md.backend: auto` now prefers local `mineru-cli` for PDF/Office/image inputs when `MINERU_CLI_PATH`, `mineru.cli_path`, or `mineru` on `PATH` is available. If CLI is unavailable, existing configured backends remain available.
- Local CLI is not a daemon and is not started or supervised by the skill. It is a user/host-provided binary invoked for one conversion run.

Tasks:

- [x] Add `mineru-cli` to `ragflow-doc-to-md` backend choices.
- [x] Add runtime CLI discovery through explicit path, `MINERU_CLI_PATH`, config `mineru.cli_path`, and `PATH`.
- [x] Add config fields `mineru.cli_path` and `mineru.cli_backend`, plus environment variables `MINERU_CLI_PATH` and `MINERU_CLI_BACKEND`.
- [x] Implement local CLI conversion with `mineru -b <backend> -p <source> -o <temp-output>` and Markdown output discovery.
- [x] Make `auto` prefer local CLI for PDF/Office/image inputs when available.
- [x] Preserve explicit HTTP backends: `mineru` / `mineru-agent` and `mineru-sync` / `mineru-local`.
- [x] Add unit/CLI tests with a fake MinerU executable.
- [x] Add platform smoke coverage with a fake MinerU executable.
- [x] Update shared config templates in all three public skills.
- [x] Update host-agent setup references and onboarding prompt.
- [x] Update architecture and CLI-agent integration docs.
- [x] Run full release hardening gates after docs are synchronized.
- [x] Ask Hermes/OpenClaw to forward-test a host with real local MinerU CLI, if available.
- [x] Copy local assets referenced by MinerU CLI Markdown, such as `images/*.jpg`, into the final handoff before temporary output is deleted.
- [x] Preserve safe relative image references and rewrite absolute temporary references to stable relative paths under `documents/images/`.
- [x] Add CLI coverage proving a fake MinerU CLI Markdown file with local images produces a `PASS` quality gate.
- [x] Rerun targeted tests, release hygiene, artifact export, consumer acceptance, and platform smoke after the asset-copy fix.

Exit criteria:

- A host with local MinerU can convert PDF/Office/image files without a local HTTP wrapper.
- MinerU CLI handoffs include local Markdown image assets, so valid converted documents are not blocked by `image_missing`.
- A host without local MinerU can still use Agent API, synchronous `/parse`, generic remote conversion, pandoc, or Markdown passthrough.
- No public artifact contains machine-specific MinerU paths.
- Existing v0.1 HTTP MinerU behavior remains backward-compatible.

## Spec Coding Rules For Phase 24-35

The detailed design source for Phase 24 through Phase 35 is
`docs/10-legacy-feature-gap-closure-design.md`. Use that document's Spec Coding Map to
connect each feature design to its owning skill, command surface, schemas, and required
test gates.

Phase dependency groups:

- Phase 24-26 are the document and evaluation-contract foundation. They should establish
  rich handoff sidecars, metadata/tagset schemas, benchmark lifecycle artifacts, grounded
  QA, strict chunk recall, and optimization planning before query-time experiments rely on
  those reports.
- Phase 27-30 are the retrieval and query-quality layer. They should consume benchmark,
  route, trace, and chunk artifacts rather than inventing parallel report formats.
- Phase 31-33 are runtime and release-governance hardening. They can be developed in
  parallel with feature work, but they must pass before any new release candidate that
  exposes the Phase 24-30 command surfaces.
- Phase 34-35 are post-ingest productization and health telemetry. They should reuse
  rich handoff retrieval hints, routing reports, diagnostics, and sanitized report helpers.

Per-phase implementation checklist:

- [ ] Add or update versioned runtime schemas and dataclasses first.
- [ ] Add neutral fixtures with placeholder KB names, placeholder endpoints, and fake keys only.
- [ ] Add CLI command surfaces with `--help`, JSON output, and report file options when relevant.
- [ ] Add non-mutating plan/dry-run behavior before any live RAGFlow mutation.
- [ ] Add deterministic unit tests and CLI tests before live-service tests.
- [ ] Add or update consumer acceptance and platform smoke checks when command surfaces or release artifacts change.
- [ ] Update `SKILL.md` only with concise routing instructions; put detailed workflows in `references/` or repo docs.
- [ ] Update shared templates/references in all three skills when a shared config or onboarding rule changes.
- [ ] Run `git diff --check`, `tools/release_hygiene_check.py`, and a sensitive-pattern scan for public-release safety.

Consistency rules:

- `doc_manifest.json`, `kb_manifest.json`, existing validation reports, and current
  `ragflow-query ask --mode direct|auto|agentic --host-assisted` behavior remain
  backward-compatible unless a future major schema version is explicitly planned.
- Rich handoff sidecars are optional inputs for `ragflow-kb-build`; plain v0.1 handoffs
  must continue to work.
- Assistant profiles, topology advice, activation plans, suppression candidates, and
  parser health reports are review artifacts. They must not silently mutate RAGFlow chat
  assistants, route configs, tags, or user content.
- Public commands must not perform direct DB, Redis, Docker, systemd, or Elasticsearch
  repair. They may diagnose and recommend operator actions.
- Any LLM-backed feature must be opt-in, traceable, and covered by deterministic offline
  fallback tests.

## Phase 24: Rich Handoff 2.0 And Markdown Post-Processing

Goal: migrate the strongest RAGFlux package and cleanup ideas without replacing the
portable `doc_manifest.json` contract.

Design reference:

- `docs/10-legacy-feature-gap-closure-design.md`

Tasks:

- [x] Add `ragflow_handoff_package_v1` runtime schema for optional package sidecars.
- [x] Add `ragflow_document_metadata_v1` for source metadata, source hash, locale, and document-level hints.
- [x] Add `ragflow_artifact_index_v1` for images, tables, raw artifacts, and copied asset hashes.
- [x] Add `ragflow_profile_suggestions_v1` for advisory profile recommendations.
- [x] Add `ragflow_retrieval_hints_v1` for section boundaries, table artifacts, keyword candidates, question candidates, and quality risks.
- [x] Add `ragflow_assistant_profile_v1` and `ragflow_assistant_test_plan_v1` as optional review sidecars.
- [x] Add source inventory fields for source format, MIME hint, size, sha256, and language hint.
- [x] Add `ragflow-doc-to-md package --rich` while keeping plain `doc_manifest.json` as default.
- [x] Generate `metadata.json`, `package_readme.md`, and artifact index files in rich mode.
- [x] Generate optional `retrieval_hints.json`, `assistant_profile.json`, and `assistant_test_plan.json` in rich mode.
- [x] Add `ragflow-kb-build inspect-handoff` to summarize manifest and optional sidecars before upload.
- [x] Add deterministic Markdown post-processing profiles: `none`, `safe`, `ocr`, and `chunk-markers`.
- [x] Emit `postprocess_report.json` with changed line counts, rule IDs, and warnings.
- [x] Make destructive Markdown rewriting require an explicit output path or `--write`.
- [x] Add unit tests for sidecar schemas and artifact hashing.
- [x] Add unit tests for post-processing rule reports.
- [x] Add CLI, consumer acceptance, and platform smoke coverage for rich handoff mode.
- [x] Add CLI, consumer acceptance, and platform smoke coverage for Markdown post-processing.
- [x] Update public `SKILL.md`, config templates if needed, and host-agent references.

Exit criteria:

- A plain v0.1 handoff still builds without reading any sidecars.
- A rich handoff can be inspected offline and contains hashes, metadata, artifacts, and profile suggestions.
- Retrieval hints and assistant profiles are reviewable sidecars, not hidden runtime behavior.
- Markdown post-processing is deterministic, reportable, and opt-in.
- No rich package sidecar contains personal paths, private service endpoints, or real secrets.

## Phase 25: Metadata And Tagset Governance MVP

Goal: provide a neutral public replacement for old KB Ops metadata and tag discipline.

Tasks:

- [x] Add `ragflow_metadata_v1` runtime schema with safe public fields.
- [x] Add `ragflow_tagset_v1` runtime schema for RAGFlow tag preparation.
- [x] Add `ragflow-kb-build metadata lint`.
- [x] Add `ragflow-kb-build metadata merge` for combining handoff metadata, user metadata, and path-derived metadata.
- [x] Add `ragflow-kb-build metadata generate-template` for user-editable starter files.
- [x] Add `ragflow-kb-build tagset lint`.
- [x] Add `ragflow-kb-build tagset export` for RAGFlow-compatible CSV/JSON outputs.
- [x] Add `ragflow-kb-build tagset report` for coverage, duplicates, and orphan tag warnings.
- [x] Wire metadata summaries into build and validation reports without changing default upload behavior.
- [ ] Add optional LLM-assisted metadata generation as a deferred adapter, not as the MVP default.
- [x] Add offline tests for schema validation, merge precedence, and redaction.
- [x] Add sample public metadata and tagset templates with placeholder-only values.

MVP note: LLM-assisted metadata generation is intentionally not part of the deterministic
Phase 25 command surface. A future adapter must mark generated metadata advisory and pass
`metadata lint` before build or validation can summarize it.

Exit criteria:

- A user can lint and merge document metadata without RAGFlow access.
- A user can export a tagset report without private KB names or private corpora.
- AI-generated metadata, if later enabled, is clearly marked advisory and never used as a security boundary.

## Phase 26: Benchmark Governance, Optimization Loop, And Strict Chunk Recall

Goal: turn existing profile, benchmark, probe, diagnose, append, and cleanup commands into a
guided profile optimization workflow with benchmark lifecycle governance.

Tasks:

- [x] Add `ragflow-kb-build benchmark import` for public or user-local benchmark formats.
- [x] Generate normalized benchmark `manifest.json`, `queries.json`, `qrels.json`, `qa.json`, and source hashes.
- [x] Support deterministic benchmark sampling with seed and strategy fields.
- [x] Add `ragflow-kb-build benchmark preflight`.
- [x] Add `ragflow-kb-build benchmark trend` with baseline/current comparison thresholds.
- [x] Add `ragflow-kb-build benchmark delta` for recall, nDCG, pollution, wrong-doc, empty-retrieval, cost, and latency changes.
- [x] Add `ragflow-kb-build benchmark gate` and `benchmark summarize` wrappers around existing validation reports.
- [x] Add root-cause hints for retrieval coverage, ranking, tag pollution, generation grounding, citation gaps, over-abstention, and cost/latency regressions.
- [ ] Add `ragflow-kb-build qa generate` for grounded QA sets with optional LLM adapter.
- [x] Add `ragflow-kb-build qa validate` to reject ungrounded generated evidence before benchmark use.
- [x] Add `ragflow-kb-build qa map-evidence` to map evidence spans onto chunk snapshots.
- [ ] Add `ragflow-kb-build segment-metadata report`.
- [ ] Add `ragflow-kb-build optimize --plan-only` for non-mutating experiment planning.
- [ ] Add candidate profile set loading from files, directories, and generated recommendations.
- [ ] Add disposable KB naming conventions and collision checks.
- [ ] Require `--execute` before creating any experiment KB.
- [ ] Build each candidate profile into an isolated disposable KB.
- [ ] Run benchmark validation for each candidate.
- [ ] Run `diagnose` automatically for failed builds or zero-chunk cases.
- [ ] Produce `optimization_plan.json`.
- [ ] Produce `profile_experiment_results.json`.
- [ ] Produce `best_profile_report.md` with metric tradeoffs and recommendation rationale.
- [ ] Add `cleanup_plan.json` and exact-confirmation cleanup execution.
- [x] Add `ragflow-kb-build snapshot-chunks`.
- [x] Add chunk snapshot schema with stable content hashes.
- [x] Extend qrels to support `expected_chunks`.
- [x] Add strict chunk recall, expected chunk hit rate, and expected evidence rank metrics.
- [ ] Add evidence mapping confidence, segment metadata coverage, and chunk coverage metrics.
- [x] Add unit tests with fake RAGFlow clients and deterministic chunk snapshots.
- [ ] Add live disposable tests gated by credentials and explicit confirmation.

Exit criteria:

- Users can import, sample, preflight, summarize, trend, and delta benchmark runs with public schemas.
- Users can compare multiple profiles with repeatable reports.
- Mutating optimization never runs without explicit execution flags.
- Chunk-level recall can be measured even when RAGFlow chunk IDs are unstable.
- Generated QA must be grounded before it can feed a benchmark gate.
- All disposable KBs are either cleaned up or reported with dataset IDs for manual cleanup.

## Phase 27: Retrieval Enrichment Experiments

Goal: make enrichment knobs such as keywords, questions, tags, rerank, and retrieval params
testable through public reports instead of private ad hoc scripts, including pollution and
suppression diagnostics.

Tasks:

- [ ] Add an experiment matrix schema for retrieval enrichment settings.
- [ ] Support experiments for `auto_keywords`, `auto_questions`, and parser enrichment options.
- [ ] Support user-provided `tag_kb_ids` experiments without shipping private tag IDs.
- [ ] Support retrieval parameter sweeps for `vsw`, `threshold`, `top_k`, and rerank flags.
- [ ] Include query latency, parse time, empty-result rate, and benchmark quality metrics in reports.
- [ ] Warn when an experiment enables slow or LLM-backed RAGFlow paths.
- [ ] Add tag pollution rate, wrong-document rate, expected-tag hit rate, and unexpected-tag hit rate metrics.
- [ ] Add `ragflow-kb-build suppression-report` for bridge-term, source, and tag suppression candidates.
- [ ] Add risk scoring for low-risk suppression and high-risk allowed-tag review candidates.
- [ ] Add `ragflow-query pollution-report` for likely BM25 translation/keyword pollution symptoms.
- [ ] Add `ragflow-query rerank-ab` to compare RAGFlow ordering with optional external reranker output.
- [ ] Keep suppression candidates as review artifacts, not automatic deletes or hidden filters.
- [ ] Integrate enrichment experiments into `optimize` or add `profile experiment`.
- [ ] Add no-network tests with fake reports.
- [ ] Add live tests only for disposable KBs and explicit user approval.

Exit criteria:

- Users can explain whether enrichment improved retrieval quality or only increased cost/latency.
- Users can distinguish recall gaps from pollution, bridge-term, source-boundary, or rerank-ordering problems.
- Enrichment experiments are reproducible from public config files.
- No private tagset, model provider, or KB naming assumptions are shipped.

## Phase 28: Multi-KB Fusion And Query Rewrite MVP

Goal: migrate the highest-value smart-query and agentic-rag retrieval ideas while keeping raw
evidence output available without an LLM key.

Tasks:

- [ ] Add `ragflow_fusion_report_v1`.
- [ ] Add `ragflow-query ask --fusion rrf`.
- [ ] Add `ragflow-query fusion` for explicit multi-KB result merging.
- [ ] Add `ragflow-query fusion-test` with offline fixture coverage.
- [ ] Normalize per-KB scores and preserve original score components.
- [ ] Deduplicate near-identical chunks across KBs.
- [ ] Add reciprocal rank fusion with explainable rank contributions.
- [ ] Preserve source KB, document, chunk ID/hash, and route metadata in output.
- [ ] Add `ragflow-query rewrite`.
- [ ] Add `ask --rewrite simple`, `ask --rewrite translate`, and `ask --rewrite hyde`.
- [ ] Add `ask --multi-query queries.json`.
- [ ] Ensure generated queries are always recorded in trace output.
- [ ] Keep original query retrieval visible in outputs.
- [ ] Add deterministic offline rewrite stubs for tests.
- [ ] Gate LLM-backed rewrite/HyDE behind explicit LLM config.

Exit criteria:

- Multi-KB fusion works without an LLM key.
- Fusion reports explain why each evidence chunk was ranked.
- Query rewrite is opt-in, traceable, and never hides the original query.

## Phase 29: Routing Quality Upgrade

Goal: bring the useful routing discipline from smart-query into the public suite without
shipping private route tables or private centroids.

Tasks:

- [ ] Add `ragflow-query route-report`.
- [ ] Report hint coverage, missing route tests, ambiguous patterns, and low-confidence routes.
- [ ] Add `ragflow-query route-diagnose`.
- [ ] Classify route failures as missing hint, regex-order issue, priority conflict, acceptable ambiguity, missing KB config, or low-confidence semantic fallback.
- [ ] Add regex ordering and substring-conflict checks.
- [ ] Add word-boundary checks for short English names, acronyms, and product terms.
- [ ] Add English hint coverage reporting by category and KB.
- [ ] Add comprehensive route-test categories: exact, fuzzy, short query, long query, mixed-language, negative, substring conflict, wildcard shadowing.
- [ ] Report per-KB retrieval parameter coverage and missing defaults.
- [ ] Add optional centroid index schema generated from user-owned KB snapshots or manifests.
- [ ] Add `ragflow-query centroid build --plan-only` with user-owned snapshots or KB manifests.
- [ ] Add bounded centroid build execution with `--batch-size`, checkpoint, resume, and dynamic embedding config.
- [ ] Add centroid scoring as a tie-breaker after explicit hints and user-specified KBs.
- [ ] Add route regression summaries by category, locale, and negative-query class.
- [ ] Add cross-language A/B reports for retrieval setting changes, including zero-result rate, chunk count delta, top-1 stability, similarity delta, and latency.
- [ ] Add benchmark-derived retrieval parameter suggestions.
- [ ] Add config linting for `kb_routing_hints` versus per-KB descriptive `hints` confusion.
- [ ] Add tests proving no private routing examples are embedded in public fixtures.

Exit criteria:

- Users can assess whether their routing config is complete and stable.
- Centroid routing is optional and user-generated.
- Cross-language and route-hint changes are backed by A/B or route-test reports.
- Public artifacts contain only neutral route examples and placeholder KB names.

## Phase 30: Query Orchestration Safety, Experimental Agentic Synthesis, And Generation Evaluation

Goal: add safe query orchestration and an opt-in agentic layer while preserving
host-assisted evidence as the default recommended workflow.

Tasks:

- [ ] Add `ragflow_query_intent_v1` and `ragflow_query_route_decision_v1`.
- [ ] Add `ragflow-query intent classify`.
- [ ] Add `ragflow-query intent route`.
- [ ] Classify `knowledge_query`, `comparison`, `clarification_needed`, and `out_of_scope`.
- [ ] Return confidence and low-confidence disclaimers in structured JSON.
- [ ] Add normalized retrieval statuses: `success`, `empty`, `low_quality`, `needs_refinement`, `clarification`, `rejected`, `error`, `timeout`, and `partial`.
- [ ] Add `ragflow_query_session_v1`.
- [ ] Add `ragflow-query session enrich`.
- [ ] Add `ragflow-query session inspect`.
- [ ] Implement deterministic pronoun/follow-up detection for recent session context.
- [ ] Enforce session turn count and token budget limits.
- [ ] Add `ragflow_agentic_plan_v1` and `ragflow_agentic_trace_v1`.
- [ ] Add `ragflow-query agentic-plan`.
- [ ] Add `ragflow-query agentic-answer` behind explicit LLM config.
- [ ] Implement query complexity classification with deterministic fallback.
- [ ] Implement bounded query decomposition and sub-query retrieval.
- [ ] Implement optional reflection with a strict iteration budget.
- [ ] Synthesize answers only from retrieved evidence.
- [ ] Emit citations compatible with `audit-citations`.
- [ ] Emit latency, token, model, and estimated cost traces.
- [ ] Add `ragflow-query evaluate-answer`.
- [ ] Add deterministic answer checks for citation presence, citation reachability, unsupported-claim warnings, and abstention behavior.
- [ ] Add optional LLM/RAGAS-style backend as a deferred adapter.
- [ ] Add offline unit tests and fixture traces.

Exit criteria:

- Query orchestration can ask for clarification or reject out-of-scope requests without calling a generation model.
- Session enrichment is bounded, inspectable, and disabled unless session input is provided.
- Experimental agentic answer generation is disabled unless the user explicitly configures it.
- Host-assisted evidence remains backward-compatible.
- Generated answers can be evaluated with deterministic checks before any optional LLM evaluator is used.

## Phase 31: Runtime Resilience And Sanitized Reports

Goal: harden long-running live workflows, fallback behavior, runtime capability checks, and
report redaction.

Tasks:

- [ ] Add `ragflow-doc-to-md backend probe`.
- [ ] Classify conversion backends as `available`, `missing`, `wrong_protocol`, `timeout`, or `not_configured`.
- [ ] Add optional `ragflow-doc-to-md backend warmup` for tiny user-approved converter fixtures.
- [ ] Add timeout cleanup and leftover-process reporting for local CLI/process-backed conversion attempts.
- [ ] Preserve image fallback as `PASS_WITH_REVIEW` with source image retained when OCR/conversion is unavailable.
- [ ] Add `ragflow-kb-build model-providers probe`.
- [ ] Probe configured RAGFlow embedding/rerank provider registration and request shape when credentials are present.
- [ ] Warn when an embedding model change requires KB rebuild or re-parse.
- [ ] Add fake endpoint tests for empty-input embedding/rerank adapter behavior.
- [ ] Add `ragflow-query endpoint-report` for local/LAN/VPN/HTTPS endpoint classification and redacted reachability summaries.
- [ ] Add `ragflow-query fallback-test`.
- [ ] Cover LLM unavailable, malformed LLM JSON, network timeout, partial failure, direct retrieval fallback, and fallback metrics.
- [ ] Add retry/backoff policy helpers with retry budgets recorded in traces.
- [ ] Add token-bucket rate limiter for RAGFlow and optional LLM calls.
- [ ] Add circuit-breaker state for repeated service failures during a run.
- [ ] Add read-only cache helpers for list/probe operations.
- [ ] Add cache keys that include query text, dataset IDs, route/rewrite/fusion params, top-k, threshold, and relevant config version.
- [ ] Add cache stats and invalidation reports.
- [ ] Add metrics collector for counters, gauges, and latency histograms with p50/p95/p99 summaries.
- [ ] Add checkpoint/resume helpers for bounded long-running jobs such as centroid build, benchmark import, optimize, and report generation.
- [ ] Add partial-failure report schemas for timeout, partial, and skipped profiles.
- [ ] Add a shared report sanitizer for API keys, bearer tokens, configured private hosts, home paths, and local config paths.
- [ ] Add `--redaction-report` to relevant commands.
- [ ] Extend release hygiene to scan generated reports and examples.
- [ ] Add acceptance fixtures that intentionally include fake secrets and verify redaction.
- [ ] Add documentation for host agents explaining where sanitized reports should be stored.

Exit criteria:

- Runtime probes explain host readiness without installing services or supervising daemons.
- Fallback behavior is measurable and covered by acceptance fixtures.
- Model-provider probes distinguish service reachability from RAGFlow usability.
- Long-running live workflows fail with clear partial reports instead of silent or noisy failures.
- Bounded batch jobs can resume without duplicating completed work.
- Generated reports are safe to attach to issues or release validation summaries after redaction.
- Release artifacts and examples continue to contain only placeholders.

## Phase 32: Skill Suite Review And Drift Control

Goal: turn the old two-pass skill review methodology into an offline release check for the
three public skills.

Tasks:

- [ ] Add `tools/release_hygiene_check.py --suite-review`.
- [ ] Validate `SKILL.md` frontmatter in all three public skills.
- [ ] Detect stale references to removed, private, or old-skill names.
- [ ] Detect shared reference/template drift across the three skills.
- [ ] Detect broken relative links in `SKILL.md` and `references/`.
- [ ] Detect trigger/description overlap that could confuse host-agent skill selection.
- [ ] Detect version/date drift between docs, release manifest, and skill metadata.
- [ ] Detect repeated warnings that should be centralized in a single reference.
- [ ] Detect accidental naming drift from old or experimental product names.
- [ ] Validate compatibility references for deprecated aliases and schema names.
- [ ] Add fixture coverage for intentional drift, broken links, duplicate shared docs, and private references.

Exit criteria:

- A release candidate can prove the three public skills are structurally aligned.
- Suite review runs offline and never scans private old skill folders by default.
- Drift findings are actionable and do not require loading large project docs into `SKILL.md`.

## Phase 33: Contract, Packaging, And Compatibility Gates

Goal: make release readiness cover installed artifacts, handoff contracts, command manifests,
schema identity, and rename compatibility.

Tasks:

- [ ] Add a contract fixture gate from `ragflow-doc-to-md` rich/plain handoff into `ragflow-kb-build --dry-run`.
- [ ] Add installed archive smoke for every exported skill tarball, separate from source-tree smoke.
- [ ] Add command-manifest dry-run support for live acceptance flows.
- [ ] Include local configuration checks, redacted command arrays, expected artifacts, mutation labels, and cleanup notes in command manifests.
- [ ] Add schema identity checks for `doc_manifest`, `kb_manifest`, quality, benchmark, query, trace, diagnostic, and route reports.
- [ ] Add compatibility facade checks for deprecated command aliases or schema names when aliases exist.
- [ ] Add explicit rename policy documentation for CLI aliases, schema migration, docs updates, downstream gates, release notes, and rollback plan.
- [ ] Add release hygiene checks for accidental public rename drift.
- [ ] Add acceptance fixtures proving the command manifest does not leak secrets or private paths.
- [ ] Add forward-test prompt templates for Hermes/OpenClaw to validate installed artifacts from release archives.

Exit criteria:

- Release candidates prove that public archives work after installation, not only from the source tree.
- Handoff contracts between the three skills are validated with neutral fixtures.
- Live acceptance can be reviewed from a redacted dry-run command manifest before mutation.
- Public naming/schema changes cannot slip in without compatibility and rollback planning.

## Phase 34: KB Topology, Routing Activation, And Assistant Profiles

Goal: help users decide create/merge/split/activate workflows and prepare post-ingest
assistant tests without mutating user-owned routing config automatically.

Tasks:

- [ ] Add `kb_topology_advice_v1`.
- [ ] Add `kb_split_plan_v1`.
- [ ] Add `kb_activation_plan_v1`.
- [ ] Add `ragflow-kb-build topology advise`.
- [ ] Add create-vs-merge signals: terminology independence, minimum useful corpus size, future-growth hint, semantic overlap, and anchor query pairs.
- [ ] Add split signals: cross-domain chunk count, ambiguous-term score, dominant-document share, and domain-purity warnings.
- [ ] Add `ragflow-kb-build topology split-plan`.
- [ ] Add `ragflow-kb-build activation-plan`.
- [ ] Check content completeness, document count, chunk count, route config registration, hint coverage, optional centroid availability, and route-test readiness.
- [ ] Add `ragflow-query route-activation-check`.
- [ ] Consume rich-handoff `retrieval_hints.json` when present for keyword/question candidates and route-test starter suggestions.
- [ ] Add `ragflow-query assistant-profile recommend`.
- [ ] Recommend assistant retrieval settings such as similarity threshold, vector/BM25 weight, top-k, quote/citation settings, and no-answer policy.
- [ ] Add `ragflow-query assistant-test-plan`.
- [ ] Generate staged assistant tests for exact numeric facts, OCR/image facts, logical flow, paraphrase, summary, and negative/boundary questions.
- [ ] Keep all topology, activation, routing, and assistant outputs as plans or sidecars unless the user explicitly edits their config.
- [ ] Add offline tests with neutral KB names and synthetic route configs.

Exit criteria:

- Users can decide whether a new corpus should become a new KB, merge into an existing KB, or be split before upload.
- A newly built KB can produce a routing activation plan without private route tables.
- Assistant profiles and test plans can be reviewed by a host agent without mutating RAGFlow chat settings.

## Phase 35: Parser Performance And KB Health Telemetry

Goal: explain slow parsing, fragile parser settings, stale count fields, and KB health risks
without direct DB/Redis repair.

Tasks:

- [ ] Add `ragflow-kb-build parse-report`.
- [ ] Summarize document parse states, parse errors, and chunk counts.
- [ ] Report parse phase timings when RAGFlow exposes progress messages or the user supplies logs.
- [ ] Warn about expensive parser settings such as `auto_questions`, excessive `auto_keywords`, visual layout recognition on large Markdown, image/table context size, and unsupported parser keys.
- [ ] Compare KB detail counts with document-list counts to detect stale or lazy list fields.
- [ ] Add `ragflow-kb-build health-report`.
- [ ] Summarize embedding model distribution across selected KBs.
- [ ] Summarize zero-document, zero-chunk, stale-parse, and route-activation risks.
- [ ] Include parser performance recommendations as API/config-level suggestions only.
- [ ] Add tests proving public commands do not execute DB, Redis, Docker, or system-service repair.

Exit criteria:

- Users can distinguish parse success from slow-path or fragile parser configuration.
- KB health reports explain route activation, model distribution, and chunk completeness risks.
- Public reports can recommend private-operator checks without performing private repairs.

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
