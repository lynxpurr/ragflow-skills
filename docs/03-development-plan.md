# RAGFlow Skills Phased Development Plan

Status: active roadmap
Date: 2026-07-02

## Objective

Implement a cross-platform public RAGFlow skill suite in the current workspace:

- `ragflow-doc-to-md`
- `ragflow-kb-build`
- `ragflow-query`
- shared `ragflow-skill-runtime`

The suite must be self-contained at release time and usable from Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent CLI tools.

Commercial SaaS agent sandboxes are excluded from the active public-skill roadmap. The user's own SaaS platform should implement document parsing, KB generation, validation, and retrieval as native backend capabilities, not by delegating first-class product workflows to portable skill scripts.

## Current Snapshot

Completed or closed for the current public command surface:

- Phase 0-2 architecture, runtime foundation, and release vendoring.
- Phase 4-12 core public skill MVPs, validation, cross-platform smoke, release hardening,
  stable v0.1.0 promotion, and CLI-agent integration polish.
- Phase 13-23 release-candidate repair, host-agent onboarding, document quality,
  read-only diagnostics, benchmark validation, profile engineering, routing,
  observability, query diagnostics, and MinerU local CLI support.
- Phase 24-29 rich handoffs, metadata/tagset governance, benchmark lifecycle,
  grounded QA validation, evidence mapping, optimization planning, gated
  disposable optimization build/validation/cleanup execution, retrieval enrichment
  reports, fusion/rewrite, and routing quality upgrades.
- Phase 32-36 skill-suite drift control, contract/package gates, topology and
  assistant review reports, parser/KB health telemetry, generated-report safety,
  primary manifest JSON Schema gates, and the first read-only runtime helper pilots.
- Phase 37 post-CLI adapter planning now ranks optional packaging, service, conversion,
  provider, reranker, and web/API adapters without changing the stable CLI baseline.
  Phase 37.1 adds a no-network runtime wheel build/install/import smoke gate and optional
  runtime wheel export while keeping archive release artifacts canonical. Phase 37.3 adds
  an intake gate for the remaining post-CLI product adapters so implementation starts only
  from concrete endpoint, provider, product, fixture, and acceptance evidence.
- Phase 38 optional LLM backend planning defines the unified config, deterministic
  fixture, advisory-output, citation-audit, redaction, and acceptance gate for future
  script-owned LLM/RAGAS execution without enabling model calls.
- Phase 39 field-trial metrics starts the real-use observation stage with an offline,
  explicit-run-root evidence aggregator instead of background telemetry.
- Phase 40 system closeout records the design-to-implementation calibration, completed
  work summary, remaining gated task audit, and ongoing observation/improvement backlog.
- Phase 41 closes the current RAGFlux retirement field-trial gates for the representative
  PDF sample after GPU pressure was reduced, the full MinerU FastAPI pipeline passed, a
  disposable RAGFlow KB live E2E passed, and the KB was cleaned up.
- The 2026-07-05 adaptive formal-ingest helper adds `ragflow-doc-to-md inspect-source`
  and `ragflow-doc-to-md adaptive` as deterministic offline report surfaces. They generate
  `ragflow_document_features_v1`, `ragflow_pipeline_decision_v1`, and
  `ragflow_adaptive_pipeline_summary_v1`, then reuse the existing formal `pipeline` and
  emit review commands for `inspect-handoff`, `asset-upload-plan`, and KB dry-run without
  enabling script-owned LLM calls or live RAGFlow mutation.

Partially completed and still active:

- Phase 3 `ragflow-query`
  - Direct, auto, host-assisted, routing, fusion, rewrite, session, and agentic
    planning paths exist as CLI surfaces.
  - Host-assisted agentic retrieval can execute bounded deterministic sub-query
    retrieval and return evidence plus traces; script-owned synthesis is not enabled.
  - V1 remains CLI-first; a local/OpenClaw `serve` command is still deferred until a
    real host workflow needs it.
  - Script-owned agentic answer generation remains gated behind future explicit LLM
    configuration.
- Phase 30 query orchestration
  - Deterministic planning, session handling, citation audit, and answer evaluation
    are implemented.
  - Agentic-answer request/review now packages host or external answer synthesis
    requests and validates returned answers without script-owned model calls.
  - Optional script-owned answer synthesis, reflection, and LLM/RAGAS-style evaluator
    backend execution remain future adapters.
- Phase 31 runtime resilience
  - Report redaction and generated-report safety are closed for the current inventory.
  - Runtime helper coverage currently tracks 97 public command surfaces: 21 `covered`,
    0 `candidate`, 0 `deferred`, and 76 `not_applicable`.
  - The bounded non-live checkpoint/resume and partial-failure candidate inventory plus
    the approved live mutation/query helper rollout are closed; any future resilience
    expansion is future adapter scope.
Deferred or outside the active public-suite completion path:

- Private dedao bridging stays out of public skills. A private bridge checkpoint now
  records that current dedao flows can use the public Markdown `doc_manifest.json`
  passthrough handoff, so no private adapter is needed unless that path proves
  insufficient.
- Optional LLM-assisted grounded-QA generation, script-owned agentic answers, reflection, and
  LLM/RAGAS evaluators must stay disabled until explicit LLM config and deterministic
  fixtures exist. Metadata suggestions, grounded-QA suggestions, agentic-answer
  synthesis, and answer-evaluator scoring now have no-LLM request/review boundaries, but
  no script-owned model call.
- Any future live mutation/query resilience checks remain gated by credentials plus
  explicit user approval.
- Wheel packaging now has a runtime-only no-network smoke/export gate. Web/UI wrappers,
  provider abstractions, and hosted service clients remain backlog items after the
  portable CLI suite is complete.

Completion priorities:

1. Keep the portable archive release path green while new work is added behind
   deterministic, no-network defaults.
2. Use `docs/15-field-trial-observation-plan.md` to collect real workflow evidence before
   opening any remaining gated implementation work.
3. Add optional LLM adapters as request/review boundaries before any script-owned model
   call. Metadata, grounded-QA, agentic-answer, and answer-evaluator boundaries are
   complete.
4. Consider `serve`, wheel packaging, provider abstractions, remote conversion clients,
   and web/API wrappers only as post-CLI product adapters.

Progress assessment:

- Roadmap checklist status is 571 completed items out of 586 tracked items, about 97%.
- The portable public CLI suite is complete for the planned portable archive
  release path: core commands, release packaging, redaction, report inventories, runtime
  helper pilots, contract gates, installed archive smoke, and primary manifest JSON Schema
  checks are all closed.
- The 15 remaining open checklist items are not ordinary implementation gaps. They are
  optional script-owned LLM/backend work, Phase 37 post-CLI adapter
  decisions/implementation, or private dedao bridge work outside the public release
  boundary.
- The next stage is field-trial observation: use real workflows to collect sanitized
  evidence before implementing any remaining gated task.

## Open Task Review

Review date: 2026-07-02

The remaining open checkboxes are intentionally gated. They should not be pulled into a
normal offline continuation unless their gate is satisfied.

| Category | Open items | Owning tasks | Gate before work starts | Next action |
| --- | ---: | --- | --- | --- |
| Local service / post-CLI host wrapper | 2 | Phase 3 optional `serve`, Backlog post-CLI service adapters | A real host workflow confirms that one-shot CLI commands are insufficient | Use the completed Phase 37.2 design gate and host-workflow intake checklist before any optional `serve` implementation. |
| Other post-CLI product adapters | 4 | Remote conversion client, provider abstraction, reranker abstraction, web/API wrapper | Known endpoint/provider/product requirements plus fake fixtures and acceptance gates | Use the Phase 37.3 intake gate; keep deferred until one concrete contract has fixtures and acceptance criteria. |
| Optional script-owned LLM/backend execution | 7 | Grounded-QA LLM adapter, agentic-answer execution, reflection, evidence-only synthesis, LLM/RAGAS evaluator, related Phase 30 synthesis backlog | Explicit LLM config, deterministic fixtures, advisory-output marking, citation-audit compatibility, and redaction gates | Use the Phase 38 planning gate; keep request/review boundaries as the default before any script-owned model call. |
| Private dedao bridge | 2 | Optional private adapter and verified private handoff output | A private adapter is explicitly needed because the Markdown passthrough handoff is insufficient, and the adapter remains outside public release artifacts | Keep outside public `skills/`; consume public handoff contracts only. |
Observation source: use `docs/15-field-trial-observation-plan.md` to record sanitized
run evidence and trigger thresholds before starting any of these gated tracks.

Closeout source: `docs/16-system-closeout-report.md` records the system-level
design-to-implementation calibration, completed work summary, remaining gated task audit,
and sustained observation/improvement backlog for the post-build operating mode.

## System Closeout Checkpoint

Checkpoint date: 2026-07-02

The concentrated development round is complete for the portable public CLI/archive
release path. This checkpoint does not add command behavior, start `ragflow-query serve`,
enable script-owned LLM/RAGAS execution, mutate RAGFlow, or add private dedao adapter
code.

Closeout decision:

- Use the current CLI/archive path as the canonical baseline for real workflows.
- Keep the 15 remaining open checklist items gated until observation evidence satisfies a
  documented trigger rule.
- Use `docs/15-field-trial-observation-plan.md` and `tools/field_trial_metrics.py` to
  collect and summarize explicit run evidence.
- Run the release-facing validation chain before changing public commands, contracts,
  release artifacts, or generated report surfaces.

## Release Path Checkpoint

Checkpoint date: 2026-07-01

The release path remains green after the Phase 37.2 serve design gate. This checkpoint did
not start live disposable mutation, script-owned LLM/RAGAS execution, `ragflow-query serve`
implementation, or private dedao bridge work.

Validated commands:

- `python3 -m pytest packages/ragflow-skill-runtime/tests -q`
- `git diff --check`
- `python3 tools/manifest_schema_check.py`
- `python3 tools/release_hygiene_check.py`
- `python3 tools/build_release.py --check`
- `python3 tools/export_release_archives.py`
- `python3 tools/consumer_acceptance.py --work-dir /tmp/ragflow-consumer-acceptance-20260701-phase37-serve-design --overwrite`
- `python3 tools/platform_smoke_matrix.py --profile strict-vendor-env --work-dir /tmp/ragflow-platform-strict-vendor-20260701-phase37-serve-design`

## Live Disposable Validation Checkpoint

Checkpoint date: 2026-07-01

Credentialed local RAGFlow validation completed against a disposable KB after explicit user
approval. Artifacts were retained under `/tmp/ragflow-live-disposable-20260701`.

Validated flow:

- Read-only `ragflow-kb-build probe` against the local RAGFlow endpoint passed.
- `ragflow-kb-build optimize --plan-only` produced a command manifest with disabled
  mutation commands.
- `optimize cleanup-plan` plus `optimize readiness` passed before live build execution.
- `optimize --execute --validate-benchmark` created one disposable KB, uploaded one tiny
  Markdown fixture, waited for parse, and passed one benchmark query.
- `optimize summarize` produced `ragflow_profile_experiment_results_v1`.
- Post-build `optimize cleanup-plan` found one ready cleanup target.
- `optimize readiness --require-cleanup-ready` passed with exact dataset ID and KB name
  confirmation.
- Cleanup verification found that the wrapper's original single-dataset DELETE path was
  incompatible with the current local RAGFlow API; the disposable KB was then removed with
  the compatible batch delete endpoint and read-back verification showed zero matches.

Follow-up fix:

- `RAGFlowClient.delete_dataset` now uses the current batch delete endpoint.
- Cleanup execution paths now reject non-zero RAGFlow API response codes instead of
  reporting deletion success on a `405 Method Not Allowed` payload.

Phase 27 live enrichment checkpoint:

- A second approved local live validation run was retained under
  `/tmp/ragflow-live-enrichment-20260701`.
- The run used one tiny Markdown fixture, two benchmark queries, and two disposable
  candidate KBs: a baseline profile and an `auto_keywords=1` enrichment profile.
- `optimize --plan-only`, `optimize cleanup-plan`, and `optimize readiness` passed before
  live execution; the command manifest kept mutation commands disabled.
- `optimize --execute --validate-benchmark` built both disposable KBs, triggered parse,
  waited for completion, and passed benchmark validation for both candidates.
- `optimize summarize` produced `ragflow_profile_experiment_results_v1`; both candidates
  tied on hit rate, MRR, recall, nDCG, MAP, and empty-result rate, so the baseline profile
  won by stable tie order.
- Post-build `optimize cleanup-plan` and
  `optimize readiness --require-cleanup-ready` passed with exact dataset ID and KB name
  confirmations for both disposable KBs.
- `optimize cleanup-execute` deleted both disposable KBs through the batch delete endpoint,
  and read-back verification found zero remaining matching dataset IDs or names.
- Operational note: use an unsanitized local workflow plan for follow-up commands such as
  `optimize summarize` and `optimize cleanup-plan`; sanitized/redacted plan copies are
  suitable for sharing, but redacted artifact paths are not reusable as workflow state.

Phase 31 live runtime resilience checkpoint:

- A final approved local live validation run was retained under
  `/tmp/ragflow-live-resilience-20260701`.
- Read-only `ragflow-kb-build probe` passed before mutation.
- Top-level `ragflow-kb-build` created one disposable KB, uploaded one tiny Markdown
  fixture, triggered parse, waited for completion, and emitted `runtime_partial_failure`
  plus `runtime_metrics` in both stdout and `kb_manifest.json`.
- `ragflow-query ask --mode direct` retrieved the fixture marker with explicit retry
  budget enabled and emitted retrieval-level `runtime_partial_failure`,
  `runtime_metrics`, and runtime metadata in stdout and trace artifacts.
- Cleanup used exact dataset ID and KB name confirmation, the delete response reported
  one successful deletion, and post-cleanup read-back verification found zero remaining
  matching dataset IDs or names.

## Remaining Work Ledger

This ledger reviews the open task list without duplicating it. The authoritative checkboxes
remain in their owning phases below.

| Track | Existing open items | Current status | Completion rule |
| --- | --- | --- | --- |
| Runtime resilience closure | Phase 31 checkpoint/resume and partial-failure umbrellas | Non-live candidate inventory and approved live mutation/query coverage closed | Runtime inventory stays at 21 `covered`, 0 `candidate`, 0 `deferred`, and 76 `not_applicable` command surfaces after read-only comparison/report commands, including retained-package and adaptive-summary comparison, were classified as not-applicable for runtime helpers. `ragflow-doc-to-md` runtime reports now include offline performance telemetry for conversion, asset, postprocess, package, hints, and ingest-plan stages without adding live mutation. |
| RAGFlux retirement observation | docs/20 multi-sample observation matrix | Complete as an offline explicit-run-root summary path | `tools/field_trial_metrics.py` now emits `ragflow_retirement_observation_matrix_v1` for scanned, long-document, paper, contract, complex-table, image-heavy, low-quality-OCR, and multi-document handoff evidence without scanning user directories or running live mutation; field-trial and retirement matrix schema identities are covered by the release gate. |
| Document split packaging | Phase 16 optional manifest rewrite/package mode | Complete for current CLI scope | Split outputs can be resumed and optionally repackaged without breaking existing segment-directory ingestion. |
| Query service and agentic adapters | Phase 3 `serve`, Phase 21/30 script-owned synthesis and reflection | Host-assisted agentic retrieval and agentic-answer request/review complete; local service and script-owned answer synthesis deferred | Implement script-owned synthesis only behind explicit local-service or LLM config, with deterministic offline fixtures and citation audit compatibility. |
| Live disposable optimization | None currently open; Phase 31 live mutation/query resilience is closed | Probe, disposable optimization build/validate/cleanup, Phase 27 enrichment validation, and Phase 31 live runtime resilience are complete | Future live runs still require credentials, explicit confirmation, exact cleanup confirmation, retained artifacts, and user approval. |
| Optional LLM-assisted adapters | Phase 26 grounded QA, Phase 30 agentic answer synthesis, Phase 30 LLM/RAGAS-style evaluator | Metadata, grounded-QA, agentic-answer, and answer-evaluator request/review boundaries complete; script-owned LLM/RAGAS backends remain deferred | Must preserve deterministic defaults, mark generated outputs advisory, and pass the same lint/validation gates as hand-authored artifacts. |
| Contract and manifest schema gates | Phase 33 release governance | Complete for primary handoff manifests and current release reports | Keep `tools/manifest_schema_check.py`, schema identity, rename governance, release hygiene, installed archive smoke, consumer acceptance, and platform smoke green whenever public contracts change. |
| Packaging and platform adapters | Phase 37 plus backlog wheel path, `serve`, remote conversion service client, provider abstractions, reranker abstraction, web/API wrapper | Runtime wheel smoke implemented and priority validated against controlled CLI-agent handoff; other adapters deferred | Rank adapters by host workflow, release impact, testability, and risk before implementation; keep archive CLI release green. |
| Private dedao bridge | Deferred private adapter tasks | Outside public release scope; private checkpoint recorded that current flows can use Markdown passthrough into `doc_manifest.json` and public `skills/` remains dedao-free | Keep private examples and adapter logic outside public `skills/`; consume only public handoff shapes. |

Recommended completion queue:

1. Run field trials with the current public CLI/archive path, record sanitized evidence
   using `docs/15-field-trial-observation-plan.md`, and keep release validation green.
2. If a concrete host needs a persistent local endpoint, implement optional
   `ragflow-query serve` from the completed Phase 37.2 design gate: lifecycle, auth
   boundary, health/direct/host-assisted schemas, shutdown behavior, redaction, and local
   fake-client smoke.
3. If optional script-owned LLM/RAGAS execution is approved, use the Phase 38 planning gate
   in `docs/14-optional-llm-backend-planning.md` before code starts. Grounded-QA LLM
   generation is the first candidate only after fake-provider fixtures, advisory-output
   marking, citation/evidence compatibility, and redaction gates are recorded.
4. If a private dedao bridge is needed, first prove that the current Markdown passthrough
   handoff is insufficient, then implement any adapter outside public release artifacts
   and make it emit the public `doc_manifest.json` handoff shape.
5. Otherwise, keep the public CLI/archive/wheel release path green with periodic release
   validation rather than adding ungated product adapters.

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
- [x] Port bounded agentic retrieval as `ask --mode agentic --host-assisted`, returning
  evidence, plan, and trace artifacts without script-owned synthesis.

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

- [x] Leave current dedao skills in place.
- [ ] Add private adapter only if needed.
- [ ] Make dedao private output match `doc_manifest.json` handoff shape.
- [x] Do not add dedao references to public SKILL.md files.

Exit criteria:

- Dedao workflows remain private.
- Public skills can consume dedao-produced handoff bundles as ordinary Markdown handoffs.

Status note: The 2026-07-02 private bridge checkpoint verified that existing dedao skills
remain in the private skill tree and that public `skills/` files contain no dedao
references. The current bridge path is Markdown materialization followed by public
`ragflow-doc-to-md --mode passthrough` to produce `doc_manifest.json`; no private adapter
code has been added. The remaining work is gated on a real need for a private exporter or
adapter and a verified handoff output.

## Backlog

- [x] Formal JSON Schema for primary `doc_manifest.json` and `kb_manifest.json`
  contracts, with public template files and release hygiene checks.
- [ ] Post-CLI service adapters beyond the optional Phase 3 `serve` wrapper, with no
  required daemon in release artifacts.
- [x] Runtime wheel-based release path for platforms that support package installation.
  Public skill entrypoint wheels remain future adapter scope.
- [ ] Remote document conversion service client with fake-client tests and no default
  hosted endpoint.
- [ ] LLM provider abstraction beyond OpenAI-compatible APIs, starting with
  request/review artifacts before script-owned calls.
- [ ] Reranker provider abstraction with fake adapter contracts and no assumed local
  model service.
- [ ] Optional web UI or hosted API wrapper after the CLI archive path remains green.

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
- [x] Add optional manifest rewrite/package mode for split outputs after the basic segment-directory path is validated.

Exit criteria:

- Empty or broken Markdown handoffs are prevented from reaching live RAGFlow upload unless the user explicitly accepts the risk.
- Long Markdown files can be split into `segments/*.md`, then ingested by passing the segment directory to `ragflow-kb-build --input` or by generating a split `doc_manifest.json` with `--manifest-output`.
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
- [x] Add live disposable probe tests where credentials are present.

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
- [ ] Revisit script-owned LLM synthesis only through the Phase 30 adapter tasks after
  real-use tracing and citation-audit behavior are stable.

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

## Spec Coding Rules For Phase 24-36

The detailed design source for Phase 24 through Phase 36 is
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
- Phase 36 is a post-Phase-35 safety closure. It should first audit report-producing
  commands across all public skills, then add remaining redaction sidecars where reports
  may echo host inputs, and only then pilot small retry/backoff or metrics helpers in one
  read-only command before broader runtime primitives are attempted.

Reusable implementation gate for future phases. These are standing rules, not
task-completion status:

- Add or update versioned runtime schemas and dataclasses first.
- Add neutral fixtures with placeholder KB names, placeholder endpoints, and fake keys only.
- Add CLI command surfaces with `--help`, JSON output, and report file options when relevant.
- Add non-mutating plan/dry-run behavior before any live RAGFlow mutation.
- Add deterministic unit tests and CLI tests before live-service tests.
- Add or update consumer acceptance and platform smoke checks when command surfaces or release artifacts change.
- Update `SKILL.md` only with concise routing instructions; put detailed workflows in `references/` or repo docs.
- Update shared templates/references in all three skills when a shared config or onboarding rule changes.
- Run `git diff --check`, `tools/release_hygiene_check.py`, and a sensitive-pattern scan for public-release safety.

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
- [x] Add optional LLM-assisted metadata suggestion adapter boundary as a deferred-by-default request/review workflow.
- [x] Add offline tests for schema validation, merge precedence, and redaction.
- [x] Add sample public metadata and tagset templates with placeholder-only values.

MVP note: `metadata suggest-request` creates an advisory, no-LLM request artifact for a
host-approved external model call, and `metadata suggest-review` checks external
candidates with deterministic lint, advisory marking, path checks, generated Markdown, and
redaction sidecars. The public script still does not invoke a model itself.

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
- [x] Add deterministic offline `ragflow-kb-build qa generate` for grounded QA scaffolds.
- [ ] Add optional LLM adapter for grounded QA generation.
- [x] Add a no-LLM grounded-QA suggestion request artifact for external or host-approved
  model calls.
- [x] Add a grounded-QA suggestion review gate that validates external candidates with
  `qa validate`, evidence mapping compatibility, advisory markings, redaction, and
  deterministic reports.
- [x] Add consumer acceptance or platform smoke coverage for the grounded-QA
  request/review boundary before enabling any script-owned generation.
- [x] Add `ragflow-kb-build qa validate` to reject ungrounded generated evidence before benchmark use.
- [x] Add `ragflow-kb-build qa map-evidence` to map evidence spans onto chunk snapshots.
- [x] Add `ragflow-kb-build segment-metadata report`.
- [x] Add `ragflow-kb-build optimize --plan-only` for non-mutating experiment planning.
- [x] Add candidate profile set loading from files, directories, and generated recommendations.
- [x] Add disposable KB naming conventions and collision checks.
- [x] Require `--execute` before creating any experiment KB.
- [x] Add command-manifest dry-run output before live disposable optimization execution.
- [x] Build each candidate profile into an isolated disposable KB.
- [x] Run benchmark validation for each candidate.
- [x] Run `diagnose` automatically for failed builds or zero-chunk cases.
- [x] Produce `optimization_plan.json`.
- [x] Produce `profile_experiment_results.json`.
- [x] Produce `best_profile_report.md` with metric tradeoffs and recommendation rationale.
- [x] Add `optimize cleanup-plan` for non-mutating `cleanup_plan.json` generation with exact-confirmation commands.
- [x] Add `optimize readiness` for non-mutating live execution gate review before disposable KB mutation.
- [x] Add exact-confirmation cleanup execution for optimization disposable KBs.
- [x] Add `ragflow-kb-build snapshot-chunks`.
- [x] Add chunk snapshot schema with stable content hashes.
- [x] Extend qrels to support `expected_chunks`.
- [x] Add strict chunk recall, expected chunk hit rate, and expected evidence rank metrics.
- [x] Add evidence mapping confidence, segment metadata coverage, and chunk coverage metrics.
- [x] Add unit tests with fake RAGFlow clients and deterministic chunk snapshots.
- [x] Add live disposable tests gated by credentials and explicit confirmation.

MVP note: `qa suggest-request` creates an advisory, no-LLM request artifact with source
hashes, QA policy, optional bounded excerpts, and redaction metadata for host-approved
external model calls. `qa suggest-review` checks external `ragflow_grounded_qa_v1`
candidates with deterministic `qa validate`, optional evidence-map compatibility,
advisory/generated markings, generated Markdown, redaction sidecars, and consumer/platform
coverage. The public script still does not invoke a model for QA generation.

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

- [x] Add an experiment matrix schema for retrieval enrichment settings.
- [x] Support experiments for `auto_keywords`, `auto_questions`, and parser enrichment options.
- [x] Support user-provided `tag_kb_ids` experiments without shipping private tag IDs.
- [x] Support retrieval parameter sweeps for `vsw`, `threshold`, `top_k`, and rerank flags.
- [x] Include query latency, parse time, empty-result rate, and benchmark quality metrics in reports.
- [x] Warn when an experiment enables slow or LLM-backed RAGFlow paths.
- [x] Add tag pollution rate, wrong-document rate, expected-tag hit rate, and unexpected-tag hit rate metrics.
- [x] Add `ragflow-kb-build suppression-report` for bridge-term, source, and tag suppression candidates.
- [x] Add risk scoring for low-risk suppression and high-risk allowed-tag review candidates.
- [x] Add `ragflow-query pollution-report` for likely BM25 translation/keyword pollution symptoms.
- [x] Add `ragflow-query rerank-ab` to compare RAGFlow ordering with optional external reranker output.
- [x] Keep suppression candidates as review artifacts, not automatic deletes or hidden filters.
- [x] Integrate enrichment experiments into `optimize` or add `profile experiment`.
- [x] Add no-network tests with fake reports.
- [x] Add live tests only for disposable KBs and explicit user approval.

Exit criteria:

- Users can explain whether enrichment improved retrieval quality or only increased cost/latency.
- Users can distinguish recall gaps from pollution, bridge-term, source-boundary, or rerank-ordering problems.
- Enrichment experiments are reproducible from public config files.
- No private tagset, model provider, or KB naming assumptions are shipped.

## Phase 28: Multi-KB Fusion And Query Rewrite MVP

Goal: migrate the highest-value smart-query and agentic-rag retrieval ideas while keeping raw
evidence output available without an LLM key.

Tasks:

- [x] Add `ragflow_fusion_report_v1`.
- [x] Add `ragflow-query ask --fusion rrf`.
- [x] Add `ragflow-query fusion` for explicit multi-KB result merging.
- [x] Add `ragflow-query fusion-test` with offline fixture coverage.
- [x] Normalize per-KB scores and preserve original score components.
- [x] Deduplicate near-identical chunks across KBs.
- [x] Add reciprocal rank fusion with explainable rank contributions.
- [x] Preserve source KB, document, chunk ID/hash, and route metadata in output.
- [x] Add `ragflow-query rewrite`.
- [x] Add `ask --rewrite simple`, `ask --rewrite translate`, and `ask --rewrite hyde`.
- [x] Add `ask --multi-query queries.json`.
- [x] Ensure generated queries are always recorded in trace output.
- [x] Keep original query retrieval visible in outputs.
- [x] Add deterministic offline rewrite stubs for tests.
- [x] Gate LLM-backed rewrite/HyDE behind explicit LLM config.

Exit criteria:

- Multi-KB fusion works without an LLM key.
- Fusion reports explain why each evidence chunk was ranked.
- Query rewrite is opt-in, traceable, and never hides the original query.

## Phase 29: Routing Quality Upgrade

Goal: bring the useful routing discipline from smart-query into the public suite without
shipping private route tables or private centroids.

Tasks:

- [x] Add `ragflow-query route-report`.
- [x] Report hint coverage, missing route tests, ambiguous patterns, and low-confidence routes.
- [x] Add `ragflow-query route-diagnose`.
- [x] Classify route failures as missing hint, regex-order issue, priority conflict, acceptable ambiguity, missing KB config, or low-confidence semantic fallback.
- [x] Add regex ordering and substring-conflict checks.
- [x] Add word-boundary checks for short English names, acronyms, and product terms.
- [x] Add English hint coverage reporting by category and KB.
- [x] Add comprehensive route-test categories: exact, fuzzy, short query, long query, mixed-language, negative, substring conflict, wildcard shadowing.
- [x] Report per-KB retrieval parameter coverage and missing defaults.
- [x] Add optional centroid index schema generated from user-owned KB snapshots or manifests.
- [x] Add `ragflow-query centroid build --plan-only` with user-owned snapshots or KB manifests.
- [x] Add bounded centroid build execution with `--batch-size`, checkpoint, resume, and dynamic embedding config.
- [x] Add centroid scoring as a tie-breaker after explicit hints and user-specified KBs.
- [x] Add route regression summaries by category, locale, and negative-query class.
- [x] Add cross-language A/B reports for retrieval setting changes, including zero-result rate, chunk count delta, top-1 stability, similarity delta, and latency.
- [x] Add benchmark-derived retrieval parameter suggestions.
- [x] Add config linting for `kb_routing_hints` versus per-KB descriptive `hints` confusion.
- [x] Add tests proving no private routing examples are embedded in public fixtures.

Exit criteria:

- Users can assess whether their routing config is complete and stable.
- Centroid routing is optional and user-generated.
- Cross-language and route-hint changes are backed by A/B or route-test reports.
- Public artifacts contain only neutral route examples and placeholder KB names.

## Phase 30: Query Orchestration Safety, Experimental Agentic Synthesis, And Generation Evaluation

Goal: add safe query orchestration and an opt-in agentic layer while preserving
host-assisted evidence as the default recommended workflow.

Tasks:

- [x] Add `ragflow_query_intent_v1` and `ragflow_query_route_decision_v1`.
- [x] Add `ragflow-query intent classify`.
- [x] Add `ragflow-query intent route`.
- [x] Classify `knowledge_query`, `comparison`, `clarification_needed`, and `out_of_scope`.
- [x] Return confidence and low-confidence disclaimers in structured JSON.
- [x] Add normalized retrieval statuses: `success`, `empty`, `low_quality`, `needs_refinement`, `clarification`, `rejected`, `error`, `timeout`, and `partial`.
- [x] Add `ragflow_query_session_v1`.
- [x] Add `ragflow-query session enrich`.
- [x] Add `ragflow-query session inspect`.
- [x] Implement deterministic pronoun/follow-up detection for recent session context.
- [x] Enforce session turn count and token budget limits.
- [x] Add `ragflow_agentic_plan_v1` and `ragflow_agentic_trace_v1`.
- [x] Add `ragflow-query agentic-plan`.
- [ ] Add `ragflow-query agentic-answer` behind explicit LLM config.
- [x] Implement query complexity classification with deterministic fallback.
- [x] Implement bounded query decomposition and sub-query retrieval.
- [ ] Implement optional reflection with a strict iteration budget.
- [ ] Synthesize answers only from retrieved evidence.
- [x] Add an agentic-answer request artifact that packages evidence, citation rules,
  trace context, model config labels, and redaction metadata without calling an LLM.
- [x] Add an agentic-answer review gate that validates host or external answers against
  returned evidence and numeric citations before acceptance.
- [ ] Add script-owned agentic-answer execution only after the request/review boundary,
  explicit LLM config, deterministic fixtures, redaction, and release gates exist.
- [x] Emit citations compatible with `audit-citations`.
- [x] Emit latency, token, model, and estimated cost traces.
- [x] Add `ragflow-query evaluate-answer`.
- [x] Add deterministic answer checks for citation presence, citation reachability, unsupported-claim warnings, and abstention behavior.
- [ ] Add optional LLM/RAGAS-style backend as a deferred adapter.
- [x] Add an LLM/RAGAS evaluator request/review boundary before any backend invocation.
- [x] Add offline unit tests and fixture traces.

MVP note: `agentic-answer request` creates a no-LLM advisory request artifact from a
saved query output, retrieved evidence, citation policy, model/provider labels, and
redaction metadata for a host-approved external model call. `agentic-answer review`
checks an external candidate answer with deterministic citation audit and
`evaluate-answer` compatibility, advisory/generated markings, Markdown, redaction
sidecars, consumer acceptance, and platform smoke coverage. The public script still does
not invoke a model or synthesize answers itself. `evaluator request` now packages a
deterministic `evaluate-answer` gate, answer hash/text preview, evidence, requested
RAGAS-style metric names, model/provider labels, and redaction metadata for an external
evaluator call. `evaluator review` validates advisory/generated external evaluator scores
and refuses to let a candidate verdict override a deterministic `evaluate-answer` failure.
The optional script-owned LLM/RAGAS backend remains deferred.

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

- [x] Add `ragflow-doc-to-md backend probe`.
- [x] Classify conversion backends as `available`, `missing`, `wrong_protocol`, `timeout`, or `not_configured`.
- [x] Add optional `ragflow-doc-to-md backend warmup` for tiny user-approved converter fixtures.
- [x] Add timeout cleanup and leftover-process reporting for local CLI/process-backed conversion attempts.
- [x] Preserve image fallback as `PASS_WITH_REVIEW` with source image retained when OCR/conversion is unavailable.
- [x] Add `ragflow-kb-build model-providers probe`.
- [x] Probe configured RAGFlow embedding/rerank provider registration and read-only provider response shape when credentials are present.
- [x] Probe configured embedding/rerank adapter request shape when explicit adapter endpoints are present.
- [x] Warn when an embedding model change requires KB rebuild or re-parse.
- [x] Add fake endpoint tests for empty-input embedding/rerank adapter behavior.
- [x] Add `ragflow-query endpoint-report` for local/LAN/VPN/HTTPS endpoint classification and redacted reachability summaries.
- [x] Add `ragflow-query fallback-test`.
- [x] Cover LLM unavailable, malformed LLM JSON, network timeout, partial failure, direct retrieval fallback, and fallback metrics.
- [x] Add retry/backoff policy helpers with retry budgets recorded in traces.
- [x] Add token-bucket rate limiter for RAGFlow and optional LLM calls.
- [x] Add circuit-breaker state for repeated service failures during a run.
- [x] Add read-only cache helpers for list/probe operations.
- [x] Add query-output cache-key reports that include query text, dataset IDs, route/rewrite/fusion params, top-k, threshold, and relevant config version.
- [x] Add cache stats and dry-run invalidation reports for local query-output cache stores.
- [x] Add active query-output cache write and invalidation execution for host-owned cache stores.
- [x] Add metrics collector for counters, gauges, and latency histograms with p50/p95/p99 summaries.
- [x] Add a static runtime-resilience inventory that classifies public commands by covered,
  candidate, deferred, or not-applicable helper coverage.
- [x] Add checkpoint/resume coverage for verified bounded offline candidates such as
  centroid build, benchmark import, deterministic QA generation, profile experiment,
  optimize plan-only, and document split.
- [x] Add partial-failure report schemas for verified non-live or read-only timeout,
  partial, skipped, warning, invalid, and not-checked outcomes.
- [x] Add live mutation/query resilience only after explicit approval for live
  `ragflow-kb-build` and `ragflow-query ask` helper rollout.
- [x] Add a shared report sanitizer for API keys, bearer tokens, configured private hosts, home paths, and local config paths.
- [x] Add `--redaction-report` to relevant commands.
- [x] Add `--redaction-report` to `ragflow-query route-test` route fixture reports.
- [x] Add `--redaction-report` to `ragflow-query route-report` route quality reports.
- [x] Add `--redaction-report` to `ragflow-query route-diagnose` route diagnosis reports.
- [x] Add `--redaction-report` to `ragflow-query fusion-test` saved-output fixture reports.
- [x] Add `--redaction-report` to `ragflow-query route-activation-check` activation and route sidecar reports.
- [x] Add `--redaction-report` to `ragflow-query assistant-profile recommend` review reports.
- [x] Add `--redaction-report` to `ragflow-query assistant-test-plan` review reports.
- [x] Add `--redaction-report` to `ragflow-query rewrite` query planning reports.
- [x] Add `--redaction-report` to `ragflow-query intent classify` and `ragflow-query intent route` planning reports.
- [x] Add `--redaction-report` to `ragflow-query session inspect` and `ragflow-query session enrich` context reports.
- [x] Add `--redaction-report` to `ragflow-query agentic-plan` orchestration planning reports.
- [x] Add `--redaction-report` to `ragflow-query audit-citations` citation audit reports.
- [x] Add `--redaction-report` to `ragflow-query fallback-test` fallback coverage reports.
- [x] Add `--redaction-report` to `ragflow-query centroid build --plan-only` centroid plan reports.
- [x] Add `--redaction-report` to `ragflow-query centroid build` centroid build reports.
- [x] Extend release hygiene to scan generated reports and examples.
- [x] Add acceptance fixtures that intentionally include fake secrets and verify redaction.
- [x] Add documentation for host agents explaining where sanitized reports should be stored.

Status note: `--redaction-report` currently covers `ragflow-query endpoint-report`,
`ragflow-query evaluate-answer`, `ragflow-query diagnose-result`,
`ragflow-query pollution-report`, `ragflow-query rerank-ab`,
`ragflow-query cross-language-ab`, `ragflow-query fusion`, `ragflow-query fusion-test`,
`ragflow-query cache-report`, `ragflow-query route-test`, `ragflow-query route-report`,
`ragflow-query route-diagnose`, `ragflow-query route-activation-check`,
`ragflow-query assistant-profile recommend`, `ragflow-query assistant-test-plan`,
`ragflow-query rewrite`, `ragflow-query intent classify`, `ragflow-query intent route`,
`ragflow-query session inspect`, `ragflow-query session enrich`, `ragflow-query agentic-plan`,
`ragflow-query audit-citations`, `ragflow-query fallback-test`,
`ragflow-query centroid build --plan-only`, `ragflow-query centroid build`,
`ragflow-kb-build model-providers probe`, `ragflow-kb-build parse-report`,
`ragflow-kb-build health-report`, `ragflow-kb-build metadata lint`,
`ragflow-kb-build metadata merge`, `ragflow-kb-build tagset lint`,
`ragflow-kb-build tagset report`, `ragflow-kb-build topology advise`,
`ragflow-kb-build topology split-plan`, `ragflow-kb-build activation-plan`,
`ragflow-kb-build optimize --plan-only`, `ragflow-kb-build optimize cleanup-plan`,
`ragflow-kb-build optimize readiness`, `ragflow-kb-build optimize summarize`,
`ragflow-doc-to-md`, `ragflow-doc-to-md inspect`,
`ragflow-doc-to-md backend probe`, `ragflow-doc-to-md backend warmup`,
`ragflow-doc-to-md postprocess`, `ragflow-doc-to-md segment-plan`, and
`ragflow-doc-to-md split`. The Phase 36 inventory now records no remaining public
`needs_redaction` report surfaces. Release hygiene now scans generated reports/examples
for raw sensitive literals and validates redaction sidecars; consumer acceptance includes a
fake generated-report redaction fixture. Public host-agent setup references document where
sanitized reports and redaction sidecars should be stored and what must stay out of shared
transcripts.
`tools/runtime_resilience_inventory.py` now emits
`ragflow_runtime_resilience_inventory_v1` and is run by release hygiene to track Phase 31
runtime helper coverage without broadening live behavior. The current inventory names 97
public commands: 21 `covered`, 0 `candidate`, 0 `deferred`, and 76 `not_applicable`, with
no stale classification findings. Covered surfaces include `ragflow-query endpoint-report`,
`ragflow-query ask`, `ragflow-query fallback-test`, `ragflow-query cache-report`,
`ragflow-query centroid build`, top-level live `ragflow-kb-build`,
`ragflow-doc-to-md` process cleanup reporting, `ragflow-doc-to-md backend probe`,
`ragflow-doc-to-md backend warmup`, `ragflow-doc-to-md split` checkpoint/resume,
`ragflow-kb-build model-providers probe`,
`ragflow-kb-build probe`, `ragflow-kb-build inspect-kb`, `ragflow-kb-build validate`,
`ragflow-kb-build snapshot-chunks`, `ragflow-kb-build qa validate`,
`ragflow-kb-build qa map-evidence`, offline `ragflow-kb-build benchmark import`
checkpoint/resume, deterministic `ragflow-kb-build qa generate` checkpoint/resume, and
offline `ragflow-kb-build profile experiment` and `ragflow-kb-build optimize --plan-only`
checkpoint/resume.
No public command surface remains in candidate or deferred status; the approved Phase 31
live mutation/query resilience rollout is closed, and any future expansion is optional
adapter scope.

Recommended next slices:

1. Treat Phase 36 generated-report safety and the first metrics/retry helper pilot as
   closed for the current public surface inventory.
2. `ragflow-query endpoint-report` now pilots the shared `ragflow_runtime_metrics_v1`
   metrics helper, `ragflow_runtime_retry_trace_v1` bounded retry helper, and
   `ragflow_runtime_cache_report_v1` opt-in read-only endpoint reachability cache, plus
   `ragflow_runtime_rate_limit_report_v1` token-bucket rate limiting for explicit
   reachability attempts and `ragflow_runtime_circuit_breaker_report_v1` per-run
   circuit-breaker summaries for repeated reachability failures. It also pilots
   `ragflow_runtime_partial_failure_report_v1` for endpoint timeout, skipped, failed, and
   partial reachability outcomes without echoing raw URLs or credentials. The same
   partial-failure schema is now also consumed by offline `ragflow-query fallback-test`
   reports for timeout, malformed, skipped, and partial fallback profiles, and by
   `ragflow-doc-to-md backend probe` for available, missing, wrong-protocol, timeout, and
   not-configured backend readiness profiles. `ragflow-kb-build model-providers probe`
   now also emits the schema for default candidate endpoint sweeps and explicit adapter
   empty-input probes. `ragflow-kb-build probe` now emits the schema for read-only dataset
   list diagnostics, including completed-with-warnings probes when fake or live responses
   expose short dataset IDs. `ragflow-kb-build inspect-kb` now emits the schema for
   manifest-only not-checked rows and optional live parsed, failed, in-progress, and
   missing document rows. `ragflow-kb-build validate` now emits the schema for passed,
   semantic-warning, error, and timeout query outcomes. `ragflow-kb-build snapshot-chunks`
   now emits the schema for snapshotted, duplicate-skipped, and missing-content chunk
   profiles. `ragflow-kb-build qa validate` now emits the schema for validated, invalid,
   warning, and skipped source-check rows. `ragflow-kb-build qa map-evidence` now emits
   the schema for mapped, unmapped, partially mapped, invalid, and warning evidence-map
   rows.
3. Keep broad checkpoint/resume helpers and cross-skill partial-failure rollout bounded
   to the verified Phase 31 surfaces. Offline `ragflow-kb-build benchmark import`,
   `ragflow-kb-build qa generate`, `ragflow-kb-build profile experiment`, and
   `ragflow-kb-build optimize --plan-only`
   checkpoint/resume are now covered, `ragflow-doc-to-md split` now supports bounded
   checkpoint/resume, `inspect-kb`, `validate`, `snapshot-chunks`, `qa validate`,
   plus `qa map-evidence` now have partial-failure coverage, and approved live
   `ragflow-kb-build` plus `ragflow-query ask` now record runtime resilience blocks. The
   Phase 31 inventory now records 21 `covered`, 0 `candidate`, 0 `deferred`, and 76
   `not_applicable` public command surfaces in
   `ragflow_runtime_resilience_inventory_v1`.

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

- [x] Add `tools/release_hygiene_check.py --suite-review`.
- [x] Validate `SKILL.md` frontmatter in all three public skills.
- [x] Detect stale references to removed, private, or old-skill names.
- [x] Detect shared reference/template drift across the three skills.
- [x] Detect broken relative links in `SKILL.md` and `references/`.
- [x] Detect trigger/description overlap that could confuse host-agent skill selection.
- [x] Detect version/date drift between docs, release manifest, and skill metadata.
- [x] Detect repeated warnings that should be centralized in a single reference.
- [x] Detect accidental naming drift from old or experimental product names.
- [x] Validate compatibility references for deprecated aliases and schema names.
- [x] Add fixture coverage for intentional drift, broken links, duplicate shared docs, and private references.
- [x] Add a private `ragflow-skills-maintainer` Codex skill outside the public release tree to preserve development workflow, validation-chain, task-selection, and release-governance guidance.

Status note: Phase 32 suite-review coverage is complete for the currently planned static
drift checks. Future suite-review work should stay release-local, offline, and focused on
new public-surface drift modes rather than private maintainer paths.

Exit criteria:

- A release candidate can prove the three public skills are structurally aligned.
- Suite review runs offline and never scans private old skill folders by default.
- Drift findings are actionable and do not require loading large project docs into `SKILL.md`.
- Maintainer-only workflow guidance stays outside public release artifacts.

## Phase 33: Contract, Packaging, And Compatibility Gates

Goal: make release readiness cover installed artifacts, handoff contracts, command manifests,
schema identity, and rename compatibility.

Implementation order:

1. Start with an offline contract fixture gate from release/dist skill scripts: create a
   neutral plain handoff and rich handoff with `ragflow-doc-to-md`, then prove
   `ragflow-kb-build --dry-run` accepts both. This should emit a small
   `ragflow_contract_fixture_gate_v1` report and must not require RAGFlow credentials.
2. Add explicit installed-archive smoke after the contract gate is stable, so each exported
   tarball is checked independently from source-tree smoke.
3. Add command-manifest dry-run and redaction gates after the archive smoke path exists.
   Command manifests should describe live mutations before any live acceptance run executes.
4. Add schema identity, compatibility facade, rename policy, and naming-drift gates as
   static release checks once the contract and archive gates define the release surface.

Tasks:

- [x] Add a contract fixture gate from `ragflow-doc-to-md` rich/plain handoff into `ragflow-kb-build --dry-run`.
- [x] Add installed archive smoke for every exported skill tarball, separate from source-tree smoke.
- [x] Add command-manifest dry-run support for live acceptance flows.
- [x] Include local configuration checks, redacted command arrays, expected artifacts, mutation labels, and cleanup notes in command manifests.
- [x] Add schema identity checks for `doc_manifest`, `kb_manifest`, quality, benchmark, query, trace, diagnostic, route, topology, KB health, and release-governance reports.
- [x] Add public JSON Schema templates for primary `doc_manifest.json` and
  `kb_manifest.json`, plus a release hygiene check that validates template/runtime
  drift and example compatibility.
- [x] Add compatibility facade checks for deprecated command aliases or schema names when aliases exist.
- [x] Add explicit rename policy documentation for CLI aliases, schema migration, docs updates, downstream gates, release notes, and rollback plan.
- [x] Add release hygiene checks for accidental public rename drift.
- [x] Add acceptance fixtures proving the command manifest does not leak secrets or private paths.
- [x] Add forward-test prompt templates for Hermes/OpenClaw to validate installed artifacts from release archives.

Exit criteria:

- Release candidates prove that public archives work after installation, not only from the source tree.
- Handoff contracts between the three skills are validated with neutral fixtures.
- Live acceptance can be reviewed from a redacted dry-run command manifest before mutation.
- Public naming/schema changes cannot slip in without compatibility and rollback planning.
- Primary handoff manifests have public JSON Schema templates in release archives.

## Phase 34: KB Topology, Routing Activation, And Assistant Profiles

Goal: help users decide create/merge/split/activate workflows and prepare post-ingest
assistant tests without mutating user-owned routing config automatically.

Tasks:

- [x] Add `kb_topology_advice_v1`.
- [x] Add `kb_split_plan_v1`.
- [x] Add `kb_activation_plan_v1`.
- [x] Add `ragflow-kb-build topology advise`.
- [x] Add create-vs-merge signals: terminology independence, minimum useful corpus size, future-growth hint, semantic overlap, and anchor query pairs.
- [x] Add split signals: cross-domain chunk count, ambiguous-term score, dominant-document share, and domain-purity warnings.
- [x] Add `ragflow-kb-build topology split-plan`.
- [x] Add `ragflow-kb-build activation-plan`.
- [x] Check content completeness, document count, chunk count, route config registration, hint coverage, optional centroid availability, and route-test readiness.
- [x] Add `ragflow_route_activation_check_v1`.
- [x] Add `ragflow-query route-activation-check`.
- [x] Let `route-activation-check` consume `kb_activation_plan_v1`, user-owned route config, route-test output or queries, and optional centroid index to report activation drift without mutation.
- [x] Consume rich-handoff `retrieval_hints.json` when present for keyword/question candidates and route-test starter suggestions.
- [x] Add `ragflow-query assistant-profile recommend`.
- [x] Recommend assistant retrieval settings such as similarity threshold, vector/BM25 weight, top-k, quote/citation settings, and no-answer policy.
- [x] Add `ragflow-query assistant-test-plan`.
- [x] Generate staged assistant tests for exact numeric facts, OCR/image facts, logical flow, paraphrase, summary, and negative/boundary questions.
- [x] Keep all topology, activation, routing, and assistant outputs as plans or sidecars unless the user explicitly edits their config.
- [x] Add offline tests with neutral KB names and synthetic route configs for topology, split, and activation planning.
- [x] Add offline tests with neutral KB names and synthetic route configs for route activation checks.
- [x] Add offline tests with neutral KB names and synthetic route configs for assistant profile recommendation artifacts.
- [x] Add offline tests with neutral KB names and synthetic route configs for assistant test-plan artifacts.

Exit criteria:

- Users can decide whether a new corpus should become a new KB, merge into an existing KB, or be split before upload.
- A newly built KB can produce a routing activation plan without private route tables.
- Assistant profiles and test plans can be reviewed by a host agent without mutating RAGFlow chat settings.

## Phase 35: Parser Performance And KB Health Telemetry

Goal: explain slow parsing, fragile parser settings, stale count fields, and KB health risks
without direct DB/Redis repair.

Tasks:

- [x] Add `ragflow-kb-build parse-report`.
- [x] Add `ragflow_parse_report_v1`.
- [x] Let `parse-report` consume `kb_manifest.json`, optional user-supplied document status JSON, optional user-supplied parse logs, and optional parser profile/config sidecars.
- [x] Summarize document parse states, parse errors, and chunk counts.
- [x] Report parse phase timings when RAGFlow exposes progress messages or the user supplies logs.
- [x] Warn about expensive parser settings such as `auto_questions`, excessive `auto_keywords`, visual layout recognition on large Markdown, image/table context size, and unsupported parser keys.
- [x] Compare KB detail counts with document-list counts to detect stale or lazy list fields.
- [x] Add offline tests proving `parse-report` does not execute DB, Redis, Docker, system-service repair, or RAGFlow mutation.
- [x] Add `ragflow-kb-build health-report`.
- [x] Summarize embedding model distribution across selected KBs.
- [x] Summarize zero-document, zero-chunk, stale-parse, and route-activation risks.
- [x] Include parser performance recommendations as API/config-level suggestions only.
- [x] Add offline tests proving `health-report` does not execute DB, Redis, Docker, system-service repair, or RAGFlow mutation.

Exit criteria:

- Users can distinguish parse success from slow-path or fragile parser configuration.
- KB health reports explain route activation, model distribution, and chunk completeness risks.
- Public reports can recommend private-operator checks without performing private repairs.

## Phase 36: Generated Report Safety Closure And Runtime Helper Pilot

Goal: close the remaining generated-report redaction gap across public commands and prove a
minimal shared runtime helper path before larger resilience primitives are added.

Tasks:

- [x] Add a report-surface inventory that classifies public commands with JSON, Markdown,
  runtime, plan, or sidecar outputs as `covered`, `not_applicable`, or `needs_redaction`.
- [x] Add `--redaction-report` coverage to the highest-risk remaining `ragflow-kb-build`
  report families that read host-supplied manifests, reports, parser configs, parse logs,
  or work paths.
- [x] Add `--redaction-report` coverage to `ragflow-kb-build benchmark import`,
  `benchmark sample`, `benchmark preflight`, `benchmark summarize`, `benchmark gate`,
  `benchmark trend`, `benchmark delta`, and `benchmark suggest`.
- [x] Add `--redaction-report` coverage to `ragflow-kb-build validate`, `diagnose`,
  `probe`, `inspect-kb`, and `inspect-handoff` report surfaces.
- [x] Add `--redaction-report` coverage to `ragflow-kb-build profile lint`,
  `profile explain`, `profile recommend`, `profile compare`, and `profile experiment`
  report surfaces.
- [x] Add `--redaction-report` coverage to `ragflow-kb-build snapshot-chunks`,
  `qa generate`, `qa validate`, `qa map-evidence`, `segment-metadata report`, and
  `suppression-report` report surfaces.
- [x] Add `--redaction-report` coverage to `ragflow-kb-build append` and `cleanup`
  plan surfaces after confirming which generated artifacts remain raw user-owned outputs.
- [x] Add `--redaction-report` coverage to `ragflow-kb-build parse-report` and
  `ragflow-kb-build health-report`, including sanitized Markdown rendering.
- [x] Add `--redaction-report` coverage to `ragflow-kb-build metadata lint`,
  `ragflow-kb-build metadata merge`, `ragflow-kb-build tagset lint`, and
  `ragflow-kb-build tagset report` generated reports. The `metadata merge --output`
  artifact remains a raw user-owned `ragflow_metadata_v1` file for downstream build
  workflows.
- [x] Add `--redaction-report` coverage to `ragflow-kb-build topology advise`,
  `ragflow-kb-build topology split-plan`, and `ragflow-kb-build activation-plan` advisory
  plan reports.
- [x] Add `--redaction-report` coverage to `ragflow-kb-build optimize --plan-only`,
  `ragflow-kb-build optimize cleanup-plan`, `ragflow-kb-build optimize readiness`, and
  `ragflow-kb-build optimize summarize`
  offline optimization report surfaces.
- [x] Add `--redaction-report` coverage to remaining `ragflow-doc-to-md` report surfaces
  that may echo local paths, converter endpoints, runtime process details, or fixture
  paths.
- [x] Add `--redaction-report` coverage to `ragflow-doc-to-md inspect` and
  `ragflow-doc-to-md backend warmup`, including sanitized Markdown rendering.
- [x] Add `--redaction-report` coverage to `ragflow-doc-to-md postprocess`,
  `ragflow-doc-to-md segment-plan`, and `ragflow-doc-to-md split`, including sanitized
  JSON stdout and plan/report artifacts.
- [x] Ensure every redacted Markdown report is rendered from the sanitized JSON payload,
  not from the raw pre-redaction report.
- [x] Add consumer acceptance or platform smoke coverage for at least one newly redacted
  non-query report family with fake secrets, fake endpoints, and fake host paths.
- [x] Add a minimal retry/backoff helper with an explicit retry budget and deterministic
  tests in one read-only probe or report command.
- [x] Add a minimal metrics summary helper for counters and latency samples in one
  read-only probe or report command.
- [x] Keep cache invalidation, checkpoint/resume, and broad partial-failure schemas
  deferred until the helper pilot is covered by tests and release gates.

Status note: `tools/report_surface_inventory.py` now emits
`ragflow_report_surface_inventory_v1`, dynamically enumerates public argparse command
leaves, and overlays an explicit Phase 36 classification. The verified inventory currently
names 97 public commands: 88 `covered`, 0 `needs_redaction`, and 9 `not_applicable`, with
no uncatalogued or stale classification findings. Generated-report redaction coverage is
now closed across inventoried public command surfaces; `ragflow-doc-to-md`
and `ragflow-query` report commands are currently classified as covered or not applicable.
`ragflow-kb-build parse-report` and
`ragflow-kb-build health-report` now sanitize JSON and Markdown from the same sanitized
payload when `--redaction-report` is enabled. `ragflow-doc-to-md inspect` and
`ragflow-doc-to-md backend warmup` now do the same, with focused CLI tests covering fake
source URLs, fake fixture names, fake secrets, private hosts, and sanitized Markdown.
`ragflow-doc-to-md postprocess`, `ragflow-doc-to-md segment-plan`, and
`ragflow-doc-to-md split` now sanitize JSON stdout and report/plan artifacts when
`--redaction-report` is enabled; focused CLI tests cover fake path tokens and fake local
URLs, while consumer acceptance exercises the new sidecars.
Top-level `ragflow-doc-to-md` conversion now supports `--redaction-report` for
`quality_report.json`, optional quality Markdown, runtime reports, runtime Markdown, and
JSON stdout. The sanitizer also redacts derived Markdown filenames when an input filename
contains assignment-style fake secrets.
`ragflow-kb-build metadata lint`, `ragflow-kb-build metadata merge`,
`ragflow-kb-build tagset lint`, and `ragflow-kb-build tagset report` now emit
`ragflow_report_redaction_report_v1` sidecars for generated JSON/Markdown/stdout reports;
focused CLI tests cover fake assignment-style path tokens and verify that raw
`metadata merge --output` stays user-owned while shareable reports stay sanitized.
`ragflow-kb-build topology advise`, `ragflow-kb-build topology split-plan`, and
`ragflow-kb-build activation-plan` now emit redaction sidecars and render Markdown from
the sanitized advisory plan payload when redaction is enabled; focused CLI tests cover
fake local path tokens, private hosts, and query-style fake secrets.
`ragflow-kb-build optimize --plan-only`, `ragflow-kb-build optimize cleanup-plan`,
`ragflow-kb-build optimize readiness`, and `ragflow-kb-build optimize summarize` now emit
redaction sidecars for offline optimization plan/readiness/result surfaces. JSON stdout,
JSON artifacts, and Markdown reports are rendered from the sanitized payload when
redaction is enabled, including plan-derived candidate artifact paths, cleanup artifact
state, and validation report paths.
`ragflow-kb-build benchmark import`, `ragflow-kb-build benchmark sample`,
`ragflow-kb-build benchmark preflight`, `ragflow-kb-build benchmark summarize`,
`ragflow-kb-build benchmark gate`, `ragflow-kb-build benchmark trend`,
`ragflow-kb-build benchmark delta`, and `ragflow-kb-build benchmark suggest` now emit
redaction sidecars for shareable benchmark lifecycle reports. JSON stdout, optional JSON
report paths, and Markdown reports are rendered from sanitized payloads when redaction is
enabled. Raw normalized benchmark dataset outputs (`manifest.json`, `queries.json`,
`qrels.json`, and `qa.json`) remain user-owned artifacts for downstream benchmark
workflows.
`ragflow-kb-build validate`, `ragflow-kb-build diagnose`, `ragflow-kb-build probe`,
`ragflow-kb-build inspect-kb`, and `ragflow-kb-build inspect-handoff` now emit redaction
sidecars for validation and diagnostic report surfaces. JSON stdout, JSON report files,
and Markdown reports are rendered from sanitized payloads when redaction is enabled, and
stdout-only `inspect-kb` still writes a sidecar for its generated inspection payload.
`ragflow-kb-build profile lint`, `ragflow-kb-build profile explain`,
`ragflow-kb-build profile recommend`, `ragflow-kb-build profile compare`, and
`ragflow-kb-build profile experiment` now emit redaction sidecars for offline profile
report surfaces. Shareable JSON stdout, report JSON, and Markdown reports are rendered
from sanitized payloads when redaction is enabled; raw `recommend --output` profiles and
`experiment --candidate-set` profile sets remain user-owned artifacts for downstream
experiments.
`ragflow-kb-build snapshot-chunks`, `ragflow-kb-build qa generate`,
`ragflow-kb-build qa validate`, `ragflow-kb-build qa map-evidence`,
`ragflow-kb-build segment-metadata report`, and `ragflow-kb-build suppression-report`
now emit redaction sidecars for offline snapshot, grounded-QA, enrichment, and suppression
report surfaces. JSON stdout, optional JSON reports, and Markdown reports are rendered
from sanitized payloads when redaction is enabled; raw chunk snapshot, generated QA, and
evidence-map output artifacts remain user-owned inputs for downstream benchmark workflows.
`ragflow-kb-build append` and `ragflow-kb-build cleanup` now emit redaction sidecars for
their generated plan/execution report surfaces. Their `--output` JSON files and stdout are
sanitized when `--redaction-report` is enabled because these outputs are shareable review
plans/reports rather than canonical downstream artifacts; no additional raw user-owned
append/cleanup artifact is produced by these commands.
Consumer acceptance now verifies newly redacted non-query fake-sensitive fixtures, and
platform smoke retains doc-to-md conversion, backend warmup, and KB metadata/tagset plus
topology/activation, optimization, benchmark lifecycle, validation/diagnostic, profile,
snapshot/QA/enrichment, and append/cleanup redaction sidecars as artifacts.
The `ragflow-query endpoint-report` command now pilots shared runtime helpers:
`ragflow_runtime_metrics_v1` for counters, gauges, and deterministic latency p50/p95/p99
summaries, and `ragflow_runtime_retry_trace_v1` for opt-in bounded reachability retries
with explicit retry budget, attempt count, retry count, and final status. It also pilots
`ragflow_runtime_cache_report_v1` for opt-in read-only reachability cache summaries via
explicit `--cache-dir` and `--cache-ttl-seconds` settings; cache reports expose digest
keys and hit/miss/stale/write counters without echoing cache paths, endpoint URLs, or API
keys. The same command now emits `ragflow_runtime_rate_limit_report_v1` when explicit
`--rate-limit-per-second` settings are supplied, using a token-bucket limiter around
read-only RAGFlow/LLM endpoint reachability attempts. It also emits
`ragflow_runtime_circuit_breaker_report_v1` when explicit
`--circuit-breaker-threshold` settings are supplied, recording per-run open,
short-circuit, failure, and recovery state while leaving the breaker disabled by default.
`ragflow_runtime_partial_failure_report_v1` is now emitted by the same endpoint report
surface to summarize timeout, skipped, failed, warning, and partial endpoint outcomes
without echoing raw URLs, API keys, or cache paths. Offline `ragflow-query fallback-test`
reports now also emit the same schema for non-endpoint timeout, malformed, skipped, and
partial fallback profiles. `ragflow-doc-to-md backend probe` also emits the same schema
for backend readiness profiles while preserving its default no-network behavior.
`ragflow-kb-build model-providers probe` emits it for model-provider endpoint candidates
and explicit adapter empty-input probes, distinguishing completed single-endpoint probes
from partial default compatibility sweeps.
`ragflow-kb-build probe` emits it for read-only dataset-list diagnostics, so warning-only
probe runs are visible as completed-with-warnings instead of being collapsed into a plain
OK diagnostic report.
`ragflow-kb-build validate` emits it for passed, semantic-warning, error, and timeout query
outcomes, while keeping semantic validation failures separate from runtime failures.
`ragflow-kb-build snapshot-chunks` emits it for snapshotted, duplicate-skipped, and
missing-content chunk profiles without changing the raw `ragflow_chunk_snapshot_v1`
artifact.
`ragflow-kb-build qa validate` emits it for validated, invalid, warning, and skipped
source-check rows while keeping the offline exact-span validation gate semantics unchanged.
`ragflow-kb-build qa map-evidence` emits it for mapped, unmapped, partially mapped,
invalid, and warning evidence-map rows while keeping the raw evidence-map artifact focused
on deterministic chunk mapping.
`ragflow-kb-build inspect-kb` emits it for manifest-only not-checked rows and optional
live parsed, failed, in-progress, and missing document rows without mutating RAGFlow.
`tools/generated_markdown_audit.py`
now emits `ragflow_generated_markdown_audit_v1` and is
run by release hygiene alongside generated-report safety. It audits 62 covered Markdown
report surfaces from the report-surface inventory and requires each to have explicit
sanitized-rendering evidence, with 0 missing and 0 stale entries in the verified suite.
Broader runtime primitives remain deferred outside Phase 36.

Near-term task list:

- [x] Add a small shared runtime metrics helper for counters and deterministic latency
  summaries, including p50/p95/p99 behavior with unit tests.
- [x] Pilot the metrics helper in `ragflow-query endpoint-report` because it is read-only,
  defaults to no network work, and already has JSON, Markdown, and redaction surfaces.
- [x] Add deterministic `endpoint-report` unit and CLI tests for the emitted runtime
  metrics using no-network CLI and fake HTTP-server cases.
- [x] Decide whether the same pilot should add opt-in retry/backoff in this slice or in the
  next slice; preserve current behavior with a default single attempt.
- [x] If retry/backoff is included, record retry budget, attempt count, retry count, and
  final status in the emitted report without adding live RAGFlow mutation.
- [x] Keep consumer acceptance and platform smoke changes scoped to schema or CLI-surface
  changes from the helper pilot.
- [x] Run a final generated-Markdown audit before marking the sanitized Markdown umbrella
  task complete.
- [x] Pilot a default-off circuit breaker in `ragflow-query endpoint-report`, with fake
  HTTP failure tests and release gate checks that verify no-network short-circuit counts.
- [x] Add `ragflow-query cache-report` for offline saved query-output cache keys and
  baseline invalidation diffs without storing or replaying query results.

Exit criteria:

- The project can name every public generated-report surface and explain whether redaction
  is covered, unnecessary, or intentionally deferred.
- High-risk non-query reports produce sanitized JSON, sanitized Markdown when applicable,
  and a valid `ragflow_report_redaction_report_v1` sidecar.
- The first retry/backoff or metrics helper is consumed by a narrow read-only command with
  offline deterministic tests.
- No new live RAGFlow mutation, LLM answer generation, or private repair workflow is added.

## Phase 37: Post-CLI Adapter Planning

Goal: choose optional post-CLI adapters only after an offline decision gate ranks real host
workflow value, release impact, testability, and operational risk.

Design source: `docs/13-post-cli-adapter-planning.md`.

Tasks:

- [x] Create a post-CLI adapter planning document and candidate matrix.
- [x] Classify wheel packaging, `ragflow-query serve`, remote conversion clients,
  provider abstractions, reranker adapters, and web/API wrappers by value, risk,
  testability, and release impact.
- [x] Recommend wheel packaging as the lowest-risk first implementation slice unless a
  real host workflow requires `ragflow-query serve` first.
- [x] Validate the selected adapter priority against a concrete user or host workflow.
- [x] Implement Phase 37.1 wheel packaging design gate with no-network build/install smoke
  and optional runtime wheel export.
- [x] Document Phase 37.2 `ragflow-query serve` design gate for a future host workflow
  that needs a local service wrapper.
- [x] Keep remote conversion, provider abstraction, reranker adapter, and web/API wrapper
  deferred until their fixture shapes and acceptance gates are known.

Exit criteria:

- The next adapter implementation starts from a ranked decision, not from generic backlog
  pressure.
- The first adapter slice remains no-network by default and does not require a daemon.
- Existing archive release gates remain green.

Status note: `tools/wheel_packaging_smoke.py` now builds the runtime wheel with
`--no-index`, `--no-deps`, and `--no-build-isolation`, installs it into an isolated
temporary environment, and imports `ragflow_skill_runtime` without relying on editable
installs. On hosts with `python3-venv`, the installer uses a temporary venv; on minimal
Ubuntu hosts without `ensurepip`, it falls back to `pip install --target` plus
`python -I` import smoke. `tools/export_runtime_wheel.py` now copies the smoke-validated
wheel into an optional runtime-wheel artifact directory and writes
`ragflow_runtime_wheel_export_v1`. The gate is optional and does not replace the canonical
public skill archive release path. The selected priority is validated against the current
Hermes/OpenClaw/Claude Code/opencode-style controlled CLI-agent handoff workflow. Phase
37.2 now documents the optional `ragflow-query serve` design gate: health, direct query,
host-assisted query, shutdown, localhost binding, auth/redaction boundaries, and
fake-client no-network smoke. It also defines the host-workflow intake and implementation
acceptance checklist that must be satisfied before service code can close the optional
surface. The `serve` command implementation remains deferred until a host confirms it
needs a persistent local tool endpoint instead of one-shot artifact-producing CLI
commands. Phase 37.3 now defines the intake, go/no-go, minimum implementation, and
acceptance requirements for remote conversion clients, provider abstraction, reranker
adapters, and web/API wrappers. Those adapters remain explicitly deferred until concrete
endpoint, provider, product, fixture, and acceptance shapes are known. The Phase 37.1
wheel smoke and full offline release-facing validation chain passed on 2026-07-01, so the
archive release path remains green after the post-CLI adapter planning work.

## Phase 38: Optional LLM Backend Planning Gate

Goal: define the gate for future script-owned LLM/RAGAS backend execution while keeping
the current request/review boundaries and deterministic no-network defaults intact.

Design source: `docs/14-optional-llm-backend-planning.md`.

Status note: Phase 38 is a planning gate only. It does not enable model calls, add default
hosted endpoints, add script-owned answer synthesis, or close any of the remaining
optional LLM/backend checklist items. The first implementation candidate, if the gate is
approved later, should be grounded-QA LLM generation with a fake provider because it can be
validated by `qa validate`, evidence mapping, advisory/generated markings, redaction
sidecars, consumer acceptance, and strict-vendor platform smoke before affecting
benchmarks.

## Field Trial Observation Gate

Design source: `docs/15-field-trial-observation-plan.md`.

Status note: The next stage is real-use observation, not new public feature expansion.
Record sanitized workflow evidence for CLI sufficiency, handoff quality, KB build
stability, query quality, private handoff needs, post-CLI product adapter needs, optional
LLM/backend pressure, and release health. Open a remaining gated implementation only when
the observation plan's trigger rules are satisfied.

## Phase 39: Field Trial Metrics MVP

Goal: make field-trial observation maintainable with a no-network, explicit-run-root
metrics aggregator that summarizes existing reports without collecting private content.

Design source: `docs/15-field-trial-observation-plan.md`.

Tasks:

- [x] Document the field-trial metrics tool scope and usage.
- [x] Add `tools/field_trial_metrics.py` as an offline evidence aggregator.
- [x] Aggregate handoff, KB build/runtime, query/citation, release health, and explicit
  field-trial record signals from user-specified run roots.
- [x] Emit sanitized JSON and Markdown summaries plus a redaction sidecar.
- [x] Add fake-fixture tests for pass, blocked quality, zero-result, citation failure,
  release health, gated trigger, and redaction behavior.
- [x] Keep the tool no-network, non-daemon, and opt-in only.
- [x] Keep checklist and open gated implementation counts unchanged unless observation
  evidence satisfies a trigger rule.

Exit criteria:

- The tool reads only explicit run directories or JSON files.
- The tool never scans user home directories by default.
- Generated summaries do not leak fake secrets, private hosts, home paths, or config paths.
- Remaining gated work stays gated until field-trial evidence crosses a documented
  trigger threshold.

Status note: `tools/field_trial_metrics.py` now scans only explicit run roots or JSON
files, summarizes existing public reports into `ragflow_field_trial_metrics_v1`, renders a
Markdown summary, can write a `ragflow_report_redaction_report_v1` sidecar, and has
field-trial plus retirement-matrix report schema identities covered by release hygiene.
Focused tests cover blocked quality, zero-result query output, citation audit failure,
release health, explicit gated-trigger records, CLI output files, and redaction behavior.

## Phase 40: System Closeout Review And Observation Backlog

Goal: close the concentrated development round with a system-level design review, task
audit, and sustained observation/improvement plan.

Design source: `docs/16-system-closeout-report.md`.

Tasks:

- [x] Review design intent against the current public skill, runtime, tooling, and release
  surfaces.
- [x] Record the release-path completion decision and the field-trial operating mode.
- [x] Audit the remaining open checklist items by gated category.
- [x] Preserve the 15 gated implementation items as open until their trigger evidence
  exists.
- [x] Publish an ongoing observation and improvement backlog for `serve`, product
  adapters, optional LLM/backend work, private bridge work, and release health.
- [x] Link the closeout report from the active development plan and design calibration
  docs.

Exit criteria:

- The closeout report names what is complete, what remains, and why the remaining items
  should not be implemented without evidence.
- The checklist count reflects the docs-only closeout work while leaving gated
  implementation tasks open.
- Future work has an explicit observation or validation trigger instead of a broad
  "continue development" default.

Status note: Phase 40 is a docs-only closeout checkpoint. It does not broaden the public
command surface or close the remaining gated product/private implementation items.

## Phase 41: RAGFlux Retirement Field-Trial Gates

Goal: convert the completed RAGFlux capability-parity work from an offline-verified
candidate path into a field-trial-backed default replacement path.

Design source: `docs/19-ragflux-capability-parity-plan.md`.

Status note: Phase 41 does not add new public command behavior by default. It collects
real MinerU/RAGFlow evidence for the already implemented `ragflow-doc-to-md pipeline`,
`ragflow-kb-build` handoff inspection/dry-run, and `ragflow-query` validation surfaces.
RAGFlow mutation remains gated by explicit user approval.

Tasks:

- [x] Record the remaining RAGFlux retirement tasks in
  `docs/19-ragflux-capability-parity-plan.md`.
- [x] Add the Phase 41 task list to the active development plan.
- [x] Preserve the full offline release-facing validation result as the baseline before
  field-trial work starts.
- [x] Run a real MinerU FastAPI field-trial on a representative PDF with images, tables,
  page numbers, and Chinese headings, using `ragflow-doc-to-md pipeline --backend
  mineru-fastapi --mineru-asset-mode markdown_assets --postprocess-profile chunk-markers`.
- [x] Verify the real MinerU response shape is covered by existing offline fixtures; no
  focused parser-extension task is required for this sample.
- [x] Run `ragflow-kb-build inspect-handoff` and `build.py --dry-run` on the real handoff;
  require ready ingestion status or explicitly accepted review items, without relying on
  `--allow-blocked`.
- [x] After explicit user approval, run a disposable RAGFlow KB live E2E: build, parse
  wait, smoke validation, direct query, host-assisted query, and retained redacted reports.
- [x] Compare the same sample against the retained RAGFlux baseline for image count,
  quality gate, chunk markers, retrieval hints, and the new path's live parse/query
  evidence.
- [x] Clean up the disposable KB, or record dataset id / KB name for user cleanup if
  automatic cleanup is unavailable.
- [x] Record the field-trial evidence through `docs/15-field-trial-observation-plan.md`
  and only then decide whether RAGFlux can move from candidate replacement to retired
  default path.

Implementation record, 2026-07-03:

- Read-only MinerU FastAPI backend probe succeeded against the local field-trial service.
- The first full-sample run exposed MinerU CUDA out-of-memory while another unused MinerU
  service was resident. After stopping the unused service and keeping the active FastAPI
  backend available, the full representative PDF completed through `pipeline`.
- Full pipeline output reported `quality_gate.status: PASS`, 21 local image assets, 9
  chunk markers, 10 section boundaries, 21 image artifact signals, 26 question
  candidates, rich sidecars, and `ragflow_ingest_plan.yaml`.
- `ragflow-kb-build inspect-handoff` reported `ingestion_readiness.status: ready`;
  `build.py --dry-run` passed with the reviewed `default-zh-512` profile.
- The approved disposable RAGFlow live E2E created one temporary KB, triggered and waited
  for parse, produced 13 chunks, passed smoke validation, returned evidence for direct
  and host-assisted query modes, and then deleted the temporary KB successfully.
- The retained RAGFlux package comparison showed both paths at quality `PASS`. RAGFlux
  had 15 package images and denser chunk markers; the new pipeline had 21 local assets,
  enhanced retrieval hints, a non-secret ingest plan, and successful live parse/query
  evidence. The lower marker density is a follow-up observation point, not a blocker for
  this sample because live chunking and smoke retrieval passed.
- A private RAGFlow config credential was stale during live probing; the operator used a
  temporary private config with a current credential and removed it after cleanup. No
  endpoint, token, run root, dataset id, or private source path is recorded in this public
  plan.

Exit criteria:

- Representative MinerU FastAPI field-trial evidence confirms local image assets land and
  quality gate is not blocked by landed images.
- Handoff inspection and dry-run reports show the pipeline output is ready for ingestion.
- A user-approved disposable KB live E2E passes and is cleaned up or explicitly recorded.
- RAGFlux baseline comparison shows no critical regression in the retirement metrics.
- Sanitized evidence is retained under an explicit run root and summarized by the
  field-trial observation process.

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
- [x] Dedao integration remains private and outside public release artifacts.

## 2026-07-03 Ingest Quality Optimization Closeout

This closeout summarizes the `docs/20-ragflow-doc-to-md-ingest-quality-plan.md` round.
It is a roadmap note, not a new unchecked implementation phase.

Completed changes:

- `ragflow-doc-to-md` now distinguishes `handoff_mode: thin_preview` from
  `handoff_mode: formal_ingest`; ordinary `convert` emits preview advisory signals, while
  `pipeline` emits formal ingest readiness signals.
- Formal handoff quality now includes HTML table statistics, chunk boundary profiles,
  marker density warnings, image semantics, retrieval hints, assistant test-plan inputs,
  ingest readiness reports, package-level formal manifests, and retained-package static
  comparison reports.
- The table-quality follow-up adds `--table-quality high|auto|standard` for MinerU
  FastAPI, table-safe postprocess protection, table integrity reporting, and
  table-aware `profile_suggestions.json` entries that recommend dense chunk markers,
  the exact RAGFlow delimiter value (`<!-- chunk -->` wrapped in backticks), larger parent chunks, and no
  `children_delimiter` for complex-table handoffs.
- Runtime reports now expose performance timing for conversion, asset handling,
  postprocess, package, hints, and ingest-plan stages, with local CLI cold-start versus
  persistent service reuse called out where the backend can report it.
- Field-trial metrics now include the offline
  `ragflow_retirement_observation_matrix_v1` summary for explicit run roots, and both
  field-trial metrics plus retirement matrix schema identities are covered by release
  hygiene.
- The implementation path added tests, schema identity coverage, consumer/platform smoke
  coverage where public surfaces changed, and documentation updates without adding
  default live RAGFlow mutation.

Ongoing observation:

- Keep collecting sanitized run evidence across scanned files, long documents, papers,
  contracts, complex tables, image-heavy inputs, low-quality OCR, and multi-document
  handoff batches before treating the replacement path as broad corpus-quality evidence.
- Watch chunk marker density, table/image semantic retention, readiness-to-live-parse
  agreement, smoke/query/citation stability, cleanup reliability, and cold/warm runtime
  performance deltas.
- Continue to use `tools/field_trial_metrics.py` only on explicit run roots or JSON files;
  public docs may record sanitized metrics, artifact names, and failure classes, but not
  endpoints, credentials, dataset/document ids, KB names, private paths, or raw chunks.
- Keep archive release, runtime-wheel smoke/export, schema identity, manifest schema,
  release hygiene, consumer acceptance, and strict-vendor platform smoke green whenever
  public reports, contracts, or artifacts change.

Future work summary:

- Default continuation remains field-trial observation and release-path maintenance.
- `ragflow-query serve` stays gated until real host-agent evidence shows one-shot CLI
  handoff is insufficient; implementation must start from the Phase 37.2 lifecycle,
  localhost, auth, health/direct/host-assisted/shutdown, redacted-log, and fake-client
  design gate.
- Remote conversion, provider abstraction, reranker adapter, and web/API wrapper work
  stay deferred until a concrete endpoint/provider/product contract has fake fixtures,
  error handling, config/auth shape, and acceptance criteria.
- Optional script-owned LLM/RAGAS execution remains deferred until explicit LLM config,
  deterministic fixtures, advisory marking, citation-audit compatibility, redaction, and
  release gates are planned together.
- Private bridge work remains outside public `skills/`; start it only if a private
  workflow proves Markdown passthrough into `doc_manifest.json` is insufficient.
- Any paired live A/B, disposable KB workflow, or other live RAGFlow mutation still
  requires separate explicit approval, cleanup confirmation, and sanitized evidence.
