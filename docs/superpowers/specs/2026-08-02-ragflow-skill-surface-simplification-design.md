---
doc_type: spec
topic: skill-surface-simplification
status: proposed
created: 2026-08-02
updated: 2026-08-04
canonical: true
implementation_authority: false
owner_spec: null
supersedes: []
superseded_by: null
related: []
---

# RAGFlow Skill Surface Simplification And Agent Command Selection Design

Status: proposed; design-only; no implementation or live-operation authority

Date: 2026-08-02

## 2026-08-03 Gate Update

The owner formally closed `NEW_MINIMAL_L3` with
`L3=NOT_COMPLETED_INPUTS_UNAVAILABLE`; no live contract was created and Gate B did not
start. This satisfies the isolation prerequisite for implementation planning, not for
live execution. FinanceBench observed evidence, the cross-subset review, and both L4
decisions remain unavailable and are not next actions for this simplification project.

Owning and related context:

- `docs/03-development-plan.md`
- `docs/10-legacy-feature-gap-closure-design.md`
- `docs/13-post-cli-adapter-planning.md`
- `docs/14-optional-llm-backend-planning.md`
- `docs/15-field-trial-observation-plan.md`
- `docs/16-system-closeout-report.md`
- `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`
- `docs/40-marker-aware-evidence-validation-and-promotion-plan.md`
- `docs/42-financebench-marker-aware-l3-disposable-validation.md`
- `docs/specs/2026-08-02-financebench-new-minimal-l3-design.md`
- `docs/43-agent-session-handoff-lessons.md`
- `tools/report_surface_inventory.py`
- `tools/runtime_resilience_inventory.py`

## Objective

Make the three-skill RAGFlow suite easier and safer for an AI agent to use by reducing
the primary instruction surface, establishing one canonical workflow for each common
intent, and moving specialized commands behind explicit progressive-disclosure gates.

The desired user experience is:

```text
user intent
  -> suite router selects one public skill
  -> the selected skill chooses one canonical workflow
  -> advanced guidance is loaded only when a named trigger is present
  -> live mutation remains separately approved and fail-closed
```

This design changes how existing capabilities are presented before it changes or removes
CLI behavior. The first implementation round must preserve command compatibility while
making the normal path materially easier to select.

## Measurable Goals

The implementation must satisfy all of the following:

1. The root `SKILL.md` is a router, not an operations manual, and contains at most 90
   nonblank lines.
2. Each public child `SKILL.md` contains at most 120 nonblank lines.
3. No more than ten canonical workflow families are presented across the primary suite
   and child skill entrypoints.
4. Every discovered public command is classified exactly once as `core`, `advanced`,
   `internal_candidate`, or `deprecated_candidate` before any command is removed.
5. Primary skill guidance contains no instruction to bypass a blocked readiness result,
   manually substitute a raw HTTP mutation, or use an unavailable related skill.
6. A representative command-selection review maps every ordinary prompt to one skill and
   one canonical workflow, with zero untriggered advanced-command selections.
7. The initial simplification round changes no CLI parser, public report schema, runtime
   behavior, default profile, or live-mutation authority.
8. Existing focused, release-hygiene, build, consumer-acceptance, and platform-smoke gates
   remain green when public skill files change.

## Problem Description

### The implementation surface and the instruction surface are conflated

The current repository intentionally contains a broad CLI toolbox. The release inventory
tracks 104 public command surfaces, including conversion backends, handoff inspection,
live KB construction, benchmark governance, topology, optimization, routing, fusion,
diagnostics, citation review, and external request/review boundaries.

Design-time guidance baseline:

| File | Current line count | Primary concern |
| --- | ---: | --- |
| root `SKILL.md` | 380 | suite routing, operations, incidents, pitfalls, and cross-references are mixed |
| `ragflow-doc-to-md/SKILL.md` | 210 | backend and workflow variants dominate the entrypoint |
| `ragflow-kb-build/SKILL.md` | 154 | core build guidance and many advanced command families are flat |
| `ragflow-query/SKILL.md` | 98 | a large command catalogue precedes selection policy |
| FinanceBench `docs/42` | 946 | historical live/recovery records and the closed successor outcome are combined |

That implementation breadth does not require all commands to appear at equal prominence
in an AI-facing `SKILL.md`. A flat command catalogue increases intent ambiguity, consumes
context, and encourages an agent to compose specialized workflows when a shorter core
path would satisfy the request.

### Common and exceptional operations are presented together

The ordinary path is small:

1. convert a source into a reviewed Markdown handoff;
2. inspect and dry-run the handoff;
3. build and validate one KB only after approval;
4. query it and inspect evidence;
5. clean up disposable resources when applicable.

Metadata governance, grounded-QA mapping, profile experiments, topology advice,
optimization, rerank comparisons, cross-language analysis, endpoint diagnostics, and
external evaluator request/review flows are useful only under narrower conditions. Their
current prominence makes them appear mandatory.

### Some guidance contradicts fail-closed behavior

The suite entrypoint currently contains two unsafe workaround patterns:

- proceeding from a blocked asset plan directly to image-ingestion execution;
- bypassing the standard build path with a manually constructed dataset POST.

The current uncommitted entrypoint also references a `ragflow-kb-seeding` skill that is
not present in this repository's public `skills/` directories. These patterns must not
survive the first simplification slice.

### Closed design history remains in active agent context

Completed plans and one-off live-run histories retain useful evidence, but they should
not compete with current operating guidance. In particular, the FinanceBench L3 document
combines its closed outcome with prior review, recovery, forensic, and cleanup-policy
history. Historical evidence must remain discoverable without being treated as the next
executable instruction.

## Design Principles

### Progressive disclosure

Primary skill files describe the shortest safe path. Advanced command references are
loaded only when the user asks for the capability or a core command produces a named
finding that requires it.

### One canonical owner per intent

Each common intent maps to one public skill and one workflow family. A skill may link to
another skill after producing its normal handoff, but two skills must not both claim the
same default action.

### Compatibility before removal

The first round changes guidance only. Existing CLI commands continue to work and remain
discoverable through `--help` and advanced references. Code removal requires a later,
separately reviewed deprecation decision with dependency and usage evidence.

### Fail closed at safety boundaries

`BLOCKED`, identity ambiguity, missing authority, unavailable cleanup proof, or unknown
live state must stop the workflow. Guidance must never recommend bypassing a blocker with
a raw API call, guessed identifier, alternative helper, or broader permission.

### Evidence-based simplification

Line counts and command counts are indicators, not the sole reason for removal. A command
becomes a removal candidate only when its purpose is duplicated, no active workflow owns
it, no consumer or release artifact depends on it, and the simpler replacement covers its
validated use cases.

### Separate product guidance from maintainer governance

Public `skills/*/SKILL.md` files contain user-facing workflow guidance. Release inventory,
session handoff policy, field-trial governance, and historical incident records remain in
repository docs or maintainer tooling and are not copied into release skill entrypoints.

## Alternatives Considered

### Delete specialized commands immediately

This would reduce the surface quickly, but it risks breaking existing users, fixtures,
report consumers, release inventories, and undocumented host workflows. It is rejected
for the first round.

### Add a new dispatcher or orchestration CLI

A dispatcher could hide command choice behind another command, but it would add a new
surface, new routing semantics, new reports, and another compatibility contract. It would
solve documentation complexity by increasing implementation complexity. It is rejected
unless later agent-selection evidence proves documentation alone insufficient.

### Progressive disclosure with compatibility-preserving classification

This is the selected approach. Simplify the primary skill files, classify every existing
command, retain advanced references, and measure agent command selection before proposing
deprecations.

## Scope And Boundaries

### In scope

- the root `SKILL.md` suite router;
- `skills/ragflow-doc-to-md/SKILL.md`;
- `skills/ragflow-kb-build/SKILL.md`;
- `skills/ragflow-query/SKILL.md`;
- focused advanced-command indexes under each public skill's `references/` directory;
- a complete maintainer-facing classification of the currently discovered command
  surfaces;
- static guidance checks and a representative agent command-selection review;
- status calibration for active versus completed/historical design documents;
- removal of unsafe, unavailable, duplicated, or machine-specific guidance.

### Explicitly out of scope for the first implementation round

- deleting or renaming an existing CLI command;
- changing a parser, option, default, output schema, or report renderer;
- creating a new dispatcher, daemon, web service, API wrapper, or plugin;
- enabling script-owned LLM/RAGAS execution;
- changing the marker-aware low-level default from `file` to `auto`;
- reopening the closed FinanceBench NEW_MINIMAL_L3 workflow or performing any live
  RAGFlow mutation;
- editing private run contracts, temporary execution roots, credentials, or evidence;
- changing release archive contents except for the intended public skill guidance files;
- commit or push without a separate user request.

### Closed NEW_MINIMAL_L3 boundary

The owner formally closed FinanceBench `NEW_MINIMAL_L3` before contract creation because
the reviewed inputs were unavailable. The isolation prerequisite for implementation
planning is satisfied. This simplification project must preserve that closeout and must
not reconstruct its inputs, create a successor L3 workflow, or treat documentation changes
as live authority.

## Related Gated Work Not Owned By This Spec

This document is not a replacement for the repository roadmap or for the marker-aware
evidence plans. A future item is considered accounted for only when it is either owned by
the checklist in this spec or explicitly assigned to an owning document below.

| Workstream | Owning source | Required gate or next decision | Relationship to this spec |
| --- | --- | --- | --- |
| Closed FinanceBench NEW_MINIMAL_L3 workflow | `docs/specs/2026-08-02-financebench-new-minimal-l3-design.md` and `docs/42-financebench-marker-aware-l3-disposable-validation.md` | None; the owner accepted `L3=NOT_COMPLETED_INPUTS_UNAVAILABLE` | Historical evidence only. It must not be reopened or replaced by this simplification. |
| Open RAG + FinanceBench cross-subset evidence review | `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md` and `docs/40-marker-aware-evidence-validation-and-promotion-plan.md` | New representative FinanceBench observed evidence under separately approved future work | Currently unavailable, not a next action. Skill-documentation changes cannot fill the evidence gap. |
| L4 high-level automatic-workflow decision | `docs/40-marker-aware-evidence-validation-and-promotion-plan.md` | Completed representative cross-subset evidence review and compatibility assessment | Currently unavailable and unauthorized. This spec preserves current behavior. |
| L4 low-level `file` to `auto` default proposal | `docs/40-marker-aware-evidence-validation-and-promotion-plan.md` | Representative evidence plus a separately approved design, implementation plan, compatibility review, and full release validation | Currently unavailable and separately gated; the low-level default remains `file`. |
| Fifteen intentionally gated roadmap items | `docs/03-development-plan.md`, `docs/13-post-cli-adapter-planning.md`, `docs/14-optional-llm-backend-planning.md`, `docs/15-field-trial-observation-plan.md`, and `docs/16-system-closeout-report.md` | The trigger evidence defined by the owning plans | External backlog: 2 local-service/post-CLI items, 4 product adapters, 7 script-owned LLM/backend items, and 2 private dedao-bridge items. None becomes ordinary simplification work. |
| Ongoing observation and release health | `docs/15-field-trial-observation-plan.md` and `docs/16-system-closeout-report.md` | Normal observation cadence or a failing release gate | Continues independently. A release-health failure takes priority over new simplification surface. |

The fifteen roadmap items remain open by design. This spec may classify their existing
commands or hide them from primary guidance, but it must not implement, close, reject, or
supersede those tracks without the evidence and approval required by their owning plans.

`docs/43-agent-session-handoff-lessons.md` is useful related maintainer guidance, but it
is currently an untracked worktree file. Before implementation begins, the owner must
decide whether to retain it as tracked durable guidance or remove it from this spec's
durable dependency set. The implementation must not silently rely on an untracked file.

## Command Guidance Model

Every command surface receives one guidance tier:

| Tier | Definition | Primary `SKILL.md` visibility | Compatibility policy |
| --- | --- | --- | --- |
| `core` | Default command family for a common user intent | May appear with one concise example | Supported and release-gated |
| `advanced` | Useful only after an explicit user request or named core finding | Reference link and trigger only | Supported; not selected by default |
| `internal_candidate` | Maintainer, diagnostic, fixture, or release-oriented behavior with no ordinary user path | Hidden from primary guidance | Retain until ownership is reviewed |
| `deprecated_candidate` | Duplicated, unsafe, unowned, or superseded behavior | Omitted from primary guidance | No removal until separate compatibility review |

Classification concerns guidance, not current report-redaction or runtime-resilience
status. Existing inventory statuses remain unchanged unless command behavior changes.

## Canonical Workflow Families

The primary documentation may expose at most these ten workflow families:

| User intent | Owning skill | Canonical workflow | Advanced trigger examples |
| --- | --- | --- | --- |
| Convert ordinary documents | `ragflow-doc-to-md` | `convert.py pipeline` | unusual backend, split/package, retained-package comparison |
| Request deterministic automatic inspection | `ragflow-doc-to-md` | `convert.py adaptive` or `--decision-only` | policy calibration or feature diagnostics |
| Check a handoff before ingestion | `ragflow-kb-build` | `build.py inspect-handoff` | asset, consistency, or parameter findings |
| Validate a KB build without mutation | `ragflow-kb-build` | top-level `build.py --dry-run` | benchmark or collision probe explicitly requested |
| Build one reviewed KB | `ragflow-kb-build` | top-level `build.py` after explicit approval | resumable batch or visual ingestion explicitly required |
| Validate built retrieval quality | `ragflow-kb-build` | `validate.py` at the requested level | strict benchmark, evidence mapping, or optimization review |
| Inspect health or failure state | `ragflow-kb-build` | existing health/diagnostic workflow | parameter audit or low-level service diagnosis |
| Clean up a disposable KB | `ragflow-kb-build` | cleanup preview, then exact confirmed execute | recovery only under separate authority |
| Retrieve evidence | `ragflow-query` | `query.py ask --mode auto|direct` | explicit multi-KB routing, fusion, or cross-language analysis |
| Review answer support | `ragflow-query` | citation audit and deterministic answer evaluation | external evaluator only when explicitly requested |

The suite root routes to these families but does not repeat their full commands.

## Skill File Architecture

### Root suite router

The root `SKILL.md` contains only:

1. suite purpose and three-skill boundary;
2. an intent-to-skill routing table;
3. the normal `doc-to-md -> kb-build -> query` sequence;
4. shared safety rules: dry-run before mutation, explicit live approval, private config,
   exact cleanup, and no raw API workaround;
5. links to the three child skills and a small maintainer reference set.

It must not contain environment-specific incidents, raw ports, one-off field-trial
counts, full regression commands, long pitfall catalogues, or duplicated child examples.

### Child skill entrypoints

Each public child `SKILL.md` uses the same structure:

1. when to use the skill;
2. required inputs and primary outputs;
3. two to five canonical workflows;
4. decision and stop rules;
5. advanced triggers and reference links;
6. one compact security note.

Each canonical workflow has one preferred example. Variants belong in references or CLI
help, not adjacent examples in the primary file.

### Advanced references

Each child skill gains or consolidates one advanced-command index. The index groups
specialized commands by trigger and links to existing detailed references. It must not
copy every parser option or become a second flat catalogue.

Example trigger groups include:

- conversion backend diagnosis and packaging;
- visual ingestion, profile experiments, benchmark governance, and optimization;
- routing diagnosis, fusion, reranking, external evaluator boundaries, and saved-output
  analysis.

## Decision And Error Handling

### Unknown or ambiguous user intent

The agent selects the smallest matching core workflow. If two core workflows remain
equally plausible and their side effects differ, it asks one concise clarifying question.
It does not load advanced references merely to avoid asking.

### Core command reports a blocker

The agent reports the blocker and loads only the advanced reference named by that finding.
It must not scan the complete command catalogue for possible bypasses.

### Advanced command lacks a trigger

The command is not selected. Existence in CLI help is not sufficient justification.

### Deprecated candidate is invoked directly

During the compatibility phase the command continues to work. Primary documentation
points to the replacement. Runtime warnings, aliases, or removal are considered only in a
later implementation plan because they change public behavior.

### Guidance and implementation disagree

Executable CLI behavior and tests determine current capability. The documentation must be
corrected; the agent must not invent a workaround or broaden authority.

## Documentation Lifecycle

Design and plan documents receive one visible state:

- `active`: controls current planned work;
- `reference`: stable technical explanation still needed by maintainers;
- `historical`: completed or superseded execution/design evidence;
- `gated`: valid future work whose trigger has not been satisfied.

Closed specs remain addressable for provenance, but active skill files link only to
current references. File moves are optional in the first round because moving many docs
can break links; status calibration and an index are sufficient. Any later archive move
must first map inbound references with `rg` and update them atomically.

The FinanceBench L3 document must eventually separate:

1. current acceptance criteria and outcome;
2. reusable live-safety/cleanup rules;
3. historical attempt, recovery, forensic, and policy evidence.

That split occurs only after NEW_MINIMAL_L3 is terminal or formally closed and must not
rewrite private evidence.

## Compatibility And Migration Strategy

### Phase 1: Guidance-only simplification

- remove unsafe and unavailable guidance;
- rewrite the root and child entrypoints around canonical workflows;
- add advanced trigger indexes;
- classify all current commands;
- change no CLI behavior or report schema.

### Phase 2: Selection validation and documentation calibration

- run representative agent command-selection cases;
- fix ambiguous routing or duplicated ownership in guidance;
- calibrate active/reference/historical document states;
- keep all existing commands compatible.

### Phase 3: Evidence-based deprecation proposals

- identify commands with duplicated purpose and no active owner;
- inspect source, tests, docs, release artifacts, and known consumer references;
- propose deprecation in a separate design and implementation plan;
- provide a compatibility window and migration note before removal.

No Phase 3 deletion is pre-approved by this design.

The initial Phase 3 review queue should explicitly include these surfaces because they
are likely to be mistaken for ordinary workflows or may duplicate host-side orchestration:

| Candidate group | Initial question | Required protection |
| --- | --- | --- |
| Metadata and grounded-QA suggestion request/review commands | Are both request/review families still needed as primary public commands, or can their guidance and artifact workflow be consolidated? | Preserve advisory semantics, deterministic validation, schema identities, redaction, and external-model boundaries. |
| Apollo table-QA judge request/review commands | Is this a user-facing workflow or a benchmark/developer specialization that belongs only in advanced guidance? | Preserve exact benchmark evidence and any current report consumers. |
| Agentic-answer and answer-evaluator request/review commands | Do two separate external-model request/review families provide distinct user value, or can a shared advanced workflow reduce choice? | Do not enable script-owned LLM calls; preserve citation and deterministic evaluation gates. |
| Intent, session, and agentic-planning helpers | Are these independently useful user commands or implementation-level steps that should be reached only through `ask` or an advanced orchestration reference? | Preserve deterministic host-assisted behavior and backward compatibility. |
| `fallback-test`, `fusion-test`, and equivalent fixture/developer surfaces | Should these remain public commands, move to maintainer/internal guidance, or retain compatibility while disappearing from user entrypoints? | Preserve release, resilience, and regression coverage even if primary documentation stops advertising them. |

This queue is a review priority, not a deprecation verdict. Any consolidation or removal
that changes command behavior, request/review artifacts, report schemas, generated
Markdown, or sidecars requires a separate approved design and the repository's full
report-surface compatibility process.

## Execution Order And Gates

1. Complete this spec self-review and obtain explicit owner approval of the written
   design. No implementation follows merely from the existence of this file.
2. Resolve the durable status of `docs/43-agent-session-handoff-lessons.md` and confirm
   that no implementation step depends on an untracked document.
3. Preserve the verified FinanceBench `NEW_MINIMAL_L3` formal-close state; do not create a
   replacement evidence workstream from this project.
4. After approval, create a separate implementation plan with file-by-file steps,
   focused tests, release validation, review checkpoints, and a rollback checkpoint.
5. Execute only the guidance-compatible Phase 1 slice first. Stop if it requires a
   parser, schema, runtime, default, or live-authority change.
6. Run Phase 2 selection validation and documentation calibration before proposing any
   deprecation work.
7. Treat Phase 3 as a new design gate. No command warning, alias change, schema merge, or
   deletion is authorized by the Phase 1/2 implementation plan.
8. Keep unavailable external evidence work separate. The cross-subset review and both L4
   decisions remain non-actions unless a later owner-approved source supplies new
   representative FinanceBench observed evidence.

## Risks And Rollback

| Risk | Prevention | Rollback or stop response |
| --- | --- | --- |
| Concision removes a required safety or stop rule | Keep shared safety rules in the root, command-specific blockers in child entrypoints, and details in linked advanced references | Restore the prior guidance bytes for the affected file and keep the failing selection case as evidence; do not relax the safety rule. |
| Advanced functionality becomes undiscoverable | Require trigger-oriented indexes, resolvable links, CLI-help compatibility, and release-artifact inclusion checks | Restore or add the smallest advanced reference link without re-expanding the primary catalogue. |
| A command is misclassified or a real consumer depends on a candidate | Preserve every command and schema in Phases 1/2; inspect tests, docs, archives, and known consumers before Phase 3 | Reclassify the command and stop the deprecation proposal. No data or runtime migration is required for guidance-only rollback. |
| Request/review or report consolidation breaks artifact consumers | Keep consolidation outside the initial round and require report-surface/schema compatibility review | Retain the existing artifacts and commands; treat the proposed consolidation as rejected until a migration contract exists. |
| Public references are absent from packaged skills | Validate source links and exported archive contents together | Revert the affected entrypoint/reference edit and keep the previous self-contained release layout. |
| Skill edits are mistaken for reopening FinanceBench evidence work | Keep the formal-close state explicit and exclude private evidence reconstruction from the plan | Stop the simplification slice and restore the closed boundary; documentation cannot create L3 authority. |
| Documentation-state calibration hides still-active work | Map inbound links and owning checklists before changing status; do not move files in the first round | Restore the previous status label and leave the document discoverable until ownership is clear. |
| An untracked guidance file is treated as durable project state | Resolve the `docs/43` tracking decision before implementation | Remove the dependency from the implementation plan or separately authorize adding the document to tracked source. |

Because the first round is guidance-only, rollback is intentionally simple: revert only
the intended guidance/test changes to the previously verified tracked state, preserve the
classification and selection evidence for diagnosis, and do not proceed to Phase 3. No
CLI data migration, live cleanup, or compatibility shim should be needed.

## Representative Agent Selection Matrix

The validation set must contain neutral prompts covering at least:

1. ordinary PDF-to-KB ingestion;
2. Markdown passthrough ingestion;
3. dry-run-only readiness review;
4. explicitly approved disposable build;
5. blocked handoff quality;
6. existing-KB health diagnosis;
7. exact cleanup request;
8. direct single-KB query;
9. multi-KB query with no explicit routing diagnosis request;
10. citation-supported answer review;
11. explicit benchmark/profile experiment request;
12. explicit advanced routing/fusion request.

For each case, record:

- selected skill;
- selected canonical workflow;
- whether an advanced trigger exists;
- commands that are allowed;
- commands that must not be selected;
- expected authorization stop, if any;
- maximum expected artifact classes.

Acceptance requires:

- 12 of 12 cases select the correct public skill;
- at least 11 of 12 select the exact canonical workflow on the first attempt;
- zero advanced selections without an explicit trigger;
- zero raw HTTP mutation workarounds;
- zero live mutation without an explicit approval prompt;
- ordinary cases use no more than three workflow steps before producing a useful result or
  requesting the one necessary approval.

This is a bounded maintainer review, not a new public report schema or permanent model
benchmark service.

## File Map For The First Implementation Round

Expected modifications:

- `SKILL.md`
- `skills/ragflow-doc-to-md/SKILL.md`
- `skills/ragflow-kb-build/SKILL.md`
- `skills/ragflow-query/SKILL.md`
- existing release-hygiene or suite-review tests when needed to enforce safety and
  resolvable related-skill references
- `docs/03-development-plan.md`, `docs/10-legacy-feature-gap-closure-design.md`, and
  `docs/16-system-closeout-report.md` only for narrow status calibration after verified
  implementation

Expected new guidance files, subject to reuse of existing references:

- one advanced-command index under each child skill only when no suitable existing index
  can be extended;
- one maintainer command-tier classification artifact derived from the existing public
  command discovery inventory;
- one neutral command-selection case matrix.

The implementation plan must inspect existing references before creating any new file and
must prefer consolidation over duplication.

## Task Checklist

### A. Baseline And Ownership

- [ ] Record the current discovered command count and exact command names from the existing
  inventory without changing its schema.
- [ ] Map every command to one owning skill, one workflow family, and one guidance tier.
- [ ] Identify duplicated intent ownership, unavailable references, raw mutation
  workarounds, and machine-specific guidance.
- [x] Confirm NEW_MINIMAL_L3 is formally closed before editing public guidance; the owner
  accepted `L3=NOT_COMPLETED_INPUTS_UNAVAILABLE` on 2026-08-03.

### B. Immediate Safety Corrections

- [ ] Remove guidance that recommends executing from a blocked asset plan.
- [ ] Remove guidance that recommends manually replacing the standard build workflow with
  a raw dataset-create POST.
- [ ] Remove or formally validate the unavailable `ragflow-kb-seeding` cross-reference;
  no port-specific shortcut may remain in the suite router.
- [ ] Add focused suite-review coverage that fails when a related public skill is not
  resolvable or when primary guidance contains a forbidden safety pattern.

### C. Root Router Simplification

- [ ] Rewrite the root skill as an intent router within the 90-nonblank-line budget.
- [ ] Retain only the three-skill boundary, canonical sequence, common safety rules, and
  child-skill links.
- [ ] Move machine-specific incidents, retired-path comparisons, command variants, and
  detailed pitfalls out of the root entrypoint.
- [ ] Verify the root description and related-skill metadata agree with the actual public
  suite.

### D. Child Skill Progressive Disclosure

- [ ] Rewrite `ragflow-doc-to-md/SKILL.md` around conversion inputs, outputs, core
  pipeline/adaptive workflows, stop rules, and advanced triggers.
- [ ] Rewrite `ragflow-kb-build/SKILL.md` around inspect, dry-run, approved build,
  validation/health, and exact cleanup.
- [ ] Rewrite `ragflow-query/SKILL.md` around `ask`, optional automatic routing, and
  evidence/citation review.
- [ ] Keep each child entrypoint within 120 nonblank lines and at most five core command
  examples.
- [ ] Consolidate advanced command guidance into trigger-oriented references without
  duplicating parser help.

### E. Command Classification And Deprecation Gate

- [ ] Classify 100% of discovered commands as `core`, `advanced`,
  `internal_candidate`, or `deprecated_candidate`.
- [ ] Confirm every core command has exactly one ordinary intent owner.
- [ ] Confirm advanced commands have explicit triggers and are absent from primary command
  example blocks.
- [ ] Record deprecated candidates with replacement, dependency, and compatibility
  evidence; do not remove them in this round.
- [ ] Review the five named candidate groups above and record whether each belongs in
  `advanced`, `internal_candidate`, or a later `deprecated_candidate` proposal.
- [ ] Review duplicated request/review and report artifact surfaces without changing
  their schemas, filenames, or runtime behavior in this round.
- [ ] Keep report-surface and runtime-resilience classifications unchanged unless actual
  command behavior changes.

### F. Agent Command-Selection Validation

- [ ] Create the twelve-case neutral selection matrix defined above.
- [ ] Run one bounded agent review from the rewritten skill files without loading the full
  repository history.
- [ ] Record skill choice, workflow choice, advanced-trigger use, step count, and artifact
  count for every case.
- [ ] Correct ambiguous guidance until all acceptance thresholds pass.
- [ ] Do not add a dispatcher or new command unless the completed matrix demonstrates a
  failure that documentation cannot resolve.

### G. Documentation State Calibration

- [ ] Mark completed implementation specs as reference or historical without changing
  their technical evidence.
- [ ] Keep one active simplification spec and avoid duplicating the full development plan.
- [ ] Keep the closed FinanceBench outcome distinguishable from its historical recovery
  and policy narrative without rewriting either evidence body.
- [ ] Verify that the closed NEW_MINIMAL_L3 workflow, unavailable cross-subset/L4 work,
  and all fifteen gated roadmap items remain linked to their owning documents rather than
  copied into this implementation checklist.
- [ ] Resolve whether `docs/43-agent-session-handoff-lessons.md` becomes tracked durable
  guidance or is removed from this spec's durable dependency set.
- [ ] Update roadmap/closeout wording only after the corresponding implementation and
  validation are complete.

### H. Validation And Release Safety

- [ ] Run `git diff --check` and targeted public-doc redaction review.
- [ ] Run focused tests for any suite-review or release-hygiene rule changes.
- [ ] Run the complete runtime test suite after test/tool changes.
- [ ] Run schema identity and report/runtime inventories and confirm counts are unchanged
  for guidance-only work.
- [ ] Run release hygiene, build check, consumer acceptance, and strict-vendor platform
  smoke before calling public skill guidance complete.
- [ ] Review release archives to confirm each packaged child skill remains self-contained
  and every referenced advanced file is included.

### I. Implementation Planning And Rollback Gate

- [ ] Obtain explicit owner approval of this amended design before implementation.
- [ ] Create a separate implementation plan after approval; do not execute directly from
  this design document.
- [ ] Record the exact intended file set, pre-change command/schema/inventory counts, and
  rollback checkpoint before editing public skill guidance.
- [ ] Stop and return to design if the implementation requires CLI, parser, schema,
  runtime, default, live-authority, or external-roadmap changes.

## Validation Strategy

### Structural guidance checks

Automated checks should verify:

- line and core-example budgets;
- all primary related-skill references resolve;
- root and child skill frontmatter remain valid;
- primary files include required core workflow and safety terms;
- primary files omit forbidden raw mutation workarounds and unavailable skills;
- advanced references linked by public skills exist in release artifacts.

Prefer extending existing suite-review/release-hygiene checks. Do not add a standalone
public report schema solely for this project.

### Compatibility checks

The initial round must demonstrate:

- no parser or command discovery count change;
- no schema identity change;
- no report-surface classification change;
- no runtime-resilience classification change;
- existing CLI tests and consumer acceptance remain green.

### Human/agent usability checks

The twelve-case selection matrix tests whether the rewritten guidance changes actual
agent behavior. It supplements deterministic tests; it does not replace them.

### Security and privacy checks

Changed public files must contain only placeholder endpoints and identifiers. They must
not include private paths, credentials, tokens, dataset/document identifiers, exact live
resource names, raw responses, or raw chunks. Advanced guidance must preserve explicit
approval and cleanup requirements.

## Acceptance Criteria

The first implementation round is accepted only when all of the following are true:

1. Root and child skill line/example budgets pass.
2. The primary documentation exposes no more than ten canonical workflow families.
3. All discovered commands have exactly one guidance tier and owner.
4. Unsafe bypass and raw mutation workaround guidance is absent.
5. Every related public skill and advanced reference resolves in source and release
   artifacts.
6. The twelve-case agent review meets its skill/workflow/advanced-trigger/step thresholds.
7. No existing CLI command, parser option, schema identity, report surface, or runtime
   behavior changed in the guidance-only round.
8. Focused tests, full runtime tests, schema identity, report/runtime inventories,
   release hygiene, build check, consumer acceptance, and strict-vendor platform smoke
   pass.
9. No private value or live identifier is added to tracked files.
10. Roadmap and closeout docs distinguish completed simplification from future gated
    deprecation work.
11. The formal-close state of NEW_MINIMAL_L3 remains unchanged by this project.
12. No command is deleted until a later deprecation design is explicitly approved.
13. Closed NEW_MINIMAL_L3 evidence, unavailable cross-subset/L4 decisions, and all fifteen
    gated roadmap items remain explicitly assigned to their owning documents.
14. The `docs/43` durability decision is explicit; no tracked implementation depends on
    an untracked guidance file.
15. A separately approved implementation plan and guidance-only rollback checkpoint exist
    before public skill files are edited.

## Definition Of Done

This design round is complete when the spec is self-reviewed, every known future item is
either owned here or linked to its external gate, the `docs/43` durability decision is
explicit, and the owner approves the written design. Approval transitions to a separate
implementation-plan task; it does not authorize implementation by itself. The
implementation round is complete only when every Phase 1 and Phase 2 checklist item is
implemented and verified, all acceptance criteria pass, and remaining Phase 3 deletion
candidates are recorded as gated rather than silently removed.

The expected product outcome is not a smaller binary at any cost. It is a smaller,
clearer decision surface in which an ordinary user request reliably selects the shortest
safe workflow, while advanced capabilities remain available without dominating agent
reasoning.
