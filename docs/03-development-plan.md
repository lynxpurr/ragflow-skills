# RAGFlow Skills Phased Development Plan

Status: draft
Date: 2026-06-22

## Objective

Implement a cross-platform public RAGFlow skill suite in the current workspace:

- `ragflow-doc-to-md`
- `ragflow-kb-build`
- `ragflow-query`
- shared `ragflow-skill-runtime`

The suite must be self-contained at release time and usable from Hermes, OpenClaw, Claude Code, and SaaS agent code sandboxes.

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

- [ ] Add `packages/ragflow-skill-runtime/pyproject.toml`.
- [ ] Add `ragflow_skill_runtime/__init__.py`.
- [ ] Add `ragflow_skill_runtime/bootstrap.py`.
- [ ] Add `ragflow_skill_runtime/config.py`.
- [ ] Add `ragflow_skill_runtime/auth.py`.
- [ ] Add `ragflow_skill_runtime/paths.py`.
- [ ] Add `ragflow_skill_runtime/http.py`.
- [ ] Add `ragflow_skill_runtime/ragflow_client.py`.
- [ ] Add `ragflow_skill_runtime/manifests.py`.
- [ ] Add tests for env/config loading.
- [ ] Add tests for manifest validation.
- [ ] Add a tiny script that imports `ragflow_skill_runtime` through vendor bootstrap.

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

- [ ] Implement `tools/build_release.py`.
- [ ] Copy each public skill into `dist/`.
- [ ] Vendor `ragflow_skill_runtime` into each skill's `scripts/_vendor/ragflow_skill_runtime`.
- [ ] Exclude caches, virtualenvs, private config, `.git`, and dedao folders.
- [ ] Add `--check` mode that verifies every public script can bootstrap core.
- [ ] Add release smoke test using a clean temp directory.

Exit criteria:

- `python tools/build_release.py --check` passes.
- Release artifact can run import smoke with no installed `ragflow_skill_runtime`.
- No private skills are present in release output.

## Phase 3: `ragflow-query` MVP

Goal: consolidate smart-query and agentic-rag into one portable public query skill.

Tasks:

- [ ] Create `skills/ragflow-query/SKILL.md`.
- [ ] Create `skills/ragflow-query/scripts/query.py`.
- [ ] Add bootstrap code to `query.py`.
- [ ] Implement `ask --mode direct`.
- [ ] Implement normalized JSON output.
- [ ] Implement `--kb`, `--kb-manifest`, and `--top-k`.
- [ ] Move direct retrieval logic into `ragflow_skill_runtime/retrieval.py`.
- [ ] Add `--mode auto` classification placeholder with conservative direct fallback.
- [ ] Add `--host-assisted` response shape for SaaS agent synthesis.
- [ ] Add optional `serve` subcommand for local/OpenClaw use.
- [ ] Port agentic retrieval after direct mode is stable.

Validation:

- [ ] Import smoke in vendor mode.
- [ ] CLI help renders.
- [ ] Direct query works against a configured RAGFlow endpoint.
- [ ] Missing auth fails with a clear message.
- [ ] Host-assisted mode returns chunks/evidence without requiring an LLM key.

Exit criteria:

- One command can perform direct retrieval from a configured RAGFlow endpoint.
- `--mode auto|direct|agentic` command surface is stable, even if agentic is initially marked experimental.

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

- [ ] Create `skills/ragflow-doc-to-md/SKILL.md`.
- [ ] Create `scripts/convert.py`.
- [ ] Implement passthrough mode for existing Markdown.
- [ ] Implement basic text/HTML to Markdown conversion.
- [ ] Add local backend adapter for installed tools where available.
- [ ] Add remote backend adapter interface.
- [ ] Write `doc_manifest.json`.
- [ ] Record source sha256 and conversion warnings.
- [ ] Add templates for manifest examples.

Validation:

- [ ] Passthrough mode works in a clean SaaS-like environment.
- [ ] Missing optional converters produce clear warnings.
- [ ] `doc_manifest.json` can be consumed by `ragflow-kb-build`.

Exit criteria:

- Existing Markdown can become a valid handoff bundle.
- Non-Markdown conversion is optional and backend-driven.

## Phase 6: Validation and Benchmark Consolidation

Goal: keep quality engineering as a product feature without preserving script sprawl.

Tasks:

- [ ] Inventory existing benchmark and regression scripts.
- [ ] Classify each as `smoke`, `regression`, `benchmark`, `legacy`, or `private`.
- [ ] Move reusable metrics into `ragflow_skill_runtime/validation.py`.
- [ ] Expose a stable `validate` command surface.
- [ ] Support user-provided query sets.
- [ ] Generate compact JSON and Markdown reports.
- [ ] Keep heavy benchmark datasets out of default release unless explicitly included.

Exit criteria:

- Public validation has one stable command.
- Heavy evaluation remains available but opt-in.
- Existing quality lessons are preserved without 70+ scripts in the main public scripts directory.

## Phase 7: Cross-Platform Smoke Matrix

Goal: prove the suite can run across target platforms.

Tasks:

- [ ] Hermes local smoke: installed core and vendor mode.
- [ ] OpenClaw smoke: HTTP serve mode.
- [ ] Claude Code smoke: CLI mode with vendored core.
- [ ] SaaS sandbox simulation: no pip install, no daemon, HTTPS-style base URL config.
- [ ] Manus-like artifact smoke: CLI produces files in a declared output directory.

Exit criteria:

- Each target has a documented invocation pattern.
- Failure modes are clear and actionable.
- Release artifacts pass vendor import checks.

## Phase 8: Private Dedao Bridge

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

## Definition of Done

The public suite is ready for first external use when:

- [ ] Three public skills have concise `SKILL.md` files.
- [ ] `ragflow-skill-runtime` contains no private environment assumptions.
- [ ] Release artifacts vendor `ragflow_skill_runtime`.
- [ ] `ragflow-query ask --mode direct` works from a clean release artifact.
- [ ] `ragflow-kb-build build` produces `kb_manifest.json`.
- [ ] `ragflow-kb-build validate --level smoke` works.
- [ ] `ragflow-doc-to-md --mode passthrough` produces `doc_manifest.json`.
- [ ] SaaS sandbox simulation works without daemon or editable install.
- [ ] Dedao skills remain private and untouched.
