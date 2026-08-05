---
doc_type: evidence
topic: skill-surface-selection-review
status: implemented
created: 2026-08-05
updated: 2026-08-05
canonical: false
implementation_authority: false
owner_spec: docs/plans/2026-08-05-ragflow-skill-surface-simplification-implementation-plan.md
supersedes: []
superseded_by: null
related:
  - docs/superpowers/specs/2026-08-02-ragflow-skill-surface-simplification-design.md
---

# RAGFlow Skill Surface Selection Review

## Scope And Method

This evidence records the Task 4 public-guidance selection review at Git commit
`2bc6dc3c3d006292369958fe3052395cf79b2187`. Each accepted row used a fresh context,
read only the public root and child guidance until an explicit advanced trigger allowed
the matching advanced reference, and returned its first selection without coaching,
retry, command execution, file mutation, or live-service access. Incomplete harness
attempts were excluded rather than scored as review rows.

## Twelve-Case Results

| Row | Neutral prompt | Observed first selection | Advanced trigger / reference | Steps | Allowed command family | Forbidden command family | Authorization stop | Maximum artifact classes | Result |
| ---: | --- | --- | --- | ---: | --- | --- | --- | --- | --- |
| 1 | Convert this ordinary PDF into a handoff for later KB ingestion. | `ragflow-doc-to-md` / `Convert ordinary documents` | none / not loaded | 1 | `ragflow-doc-to-md pipeline` | RAGFlow KB build/mutation; RAGFlow query/retrieval; raw API calls | Stop on a missing or unapproved conversion backend, a BLOCKED quality gate, or any unapproved network or RAGFlow mutation. | reviewed Markdown documents; document manifest; quality report; formal handoff manifest; retrieval hints; RAGFlow ingest plan | PASS |
| 2 | Prepare this reviewed Markdown directory for later ingestion without reconverting it. | `ragflow-doc-to-md` / `Convert ordinary documents` | none / not loaded | 1 | `python scripts/convert.py pipeline --mode passthrough` | `python scripts/convert.py adaptive`; backend reconversion; `ragflow-kb-build build`; `ragflow-query ask` | Stop on BLOCKED, missing required source files, or any need for an unconfigured remote backend; no live ingestion is authorized. | `documents/*.md`; `doc_manifest.json`; `quality_report.json`; `formal_handoff_manifest.json`; `retrieval_hints.json`; `ragflow_ingest_plan.yaml` | PASS |
| 3 | Check whether this handoff and profile are ready, but do not touch RAGFlow. | `ragflow-kb-build` / `Validate build readiness without mutation` | none / not loaded | 1 | `python scripts/build.py --doc-manifest ... --kb-name ... --profile ... --dry-run --json` | Inspect a handoff; Build one reviewed KB; Validate retrieval quality; Inspect KB health; Clean up a disposable KB; Retrieve evidence; Review answer support | Stop after the non-mutating dry-run; no live RAGFlow approval or mutation is authorized. | dry-run JSON | PASS |
| 4 | The disposable KB build is explicitly approved for this exact reviewed name and handoff. | `ragflow-kb-build` / `Build one reviewed KB` | none / not loaded | 3 | `build.py` | `cleanup.py`; `query.py`; raw API mutation | Stop if the exact handoff/name is not matched, dry-run is not passed, or the result is BLOCKED, ambiguous, or missing required authority. | reviewed knowledge base; KB manifest | PASS |
| 5 | The handoff quality status is BLOCKED; tell me what to do next. | `ragflow-kb-build` / `Inspect a handoff` | none / not loaded | 1 | `inspect-handoff` | build; query; cleanup | Stop on BLOCKED; do not bypass the blocker with mutation or raw API calls. | handoff inspection report | PASS |
| 6 | Diagnose the health of this existing KB from its retained manifests and reports. | `ragflow-kb-build` / `Inspect KB health` | none / not loaded | 1 | `health-report` | live build; read-only refresh/query; cleanup execution; advanced diagnostics | Use only retained artifacts; stop rather than accessing a live service or performing mutation without separate explicit approval. | health report JSON; health report Markdown | PASS |
| 7 | Preview cleanup, then delete only the disposable KB whose exact ID and name I confirm. | `ragflow-kb-build` / `Clean up a disposable KB` | none / not loaded | 2 | cleanup preview; exact cleanup execution | raw API mutation; guessed-identifier cleanup; cleanup execution without separate approval | Stop after the cleanup preview until the exact dataset ID, matching KB name, and separate cleanup approval are provided. | cleanup preview; retained cleanup proof | PASS |
| 8 | Retrieve evidence for this question from the one reviewed KB manifest. | `ragflow-query` / `Retrieve evidence` | none / not loaded | 1 | `python scripts/query.py ask --kb-manifest --mode direct --json` | routing diagnosis; fusion; reranking; script-owned synthesis; KB mutation; model calls; cleanup | Stop on missing dataset identity, missing retrieval approval, private-config ambiguity, or a retrieval status requiring clarification. | evidence chunks; retrieval status; optional traces | PASS |
| 9 | Query these two explicitly selected KBs; I am not asking for routing diagnosis. | `ragflow-query` / `Retrieve evidence` | none / not loaded | 1 | `ask` | routing diagnosis; fusion; reranking; KB mutation; model calls; cleanup | Stop on missing dataset identity, missing retrieval approval, private-config ambiguity, or a status that requires clarification. | evidence chunks; retrieval status; optional traces | PASS |
| 10 | Check whether this drafted answer is supported by the saved query evidence and citations. | `ragflow-query` / `Review answer support` | none / not loaded | 2 | `audit-citations`; `evaluate-answer` | `ask`; external evaluator; KB mutation | No command execution, live service access, file mutation, or agent spawning is authorized. | saved query output; draft answer file | PASS |
| 11 | Compare two chunk profiles with the supplied benchmark artifacts. | `ragflow-kb-build` / `Validate retrieval quality` | profile comparison and supplied benchmark artifacts / loaded | 1 | `benchmark` | build; query; cleanup; optimize; raw API mutation; Stage 8C; script-owned LLM/RAGAS; private adapters | Use only the supplied benchmark artifacts; stop before any live build, read-only RAGFlow access, query, cleanup, optimization execution, or other service operation without its separate explicit approval. | benchmark artifacts; public-safe reports | PASS |
| 12 | Diagnose routing and compare reciprocal-rank fusion for these saved multi-KB outputs. | `ragflow-query` / `Retrieve evidence` | explicit routing diagnosis and saved-output multi-result fusion / loaded | 2 | `route-diagnose`; `fusion` | `bootstrap-smoke`; `fallback-test`; `fusion-test`; agentic-answer request/review; `serve`; raw HTTP workarounds | Analyze only the reviewed saved outputs; stop before private-config or live retrieval, network or model calls, KB mutation, cleanup, or unapproved dataset access. | routing diagnosis report; fusion comparison report | PASS |

## Acceptance Summary

| Metric | Observed | Threshold | Result |
| --- | ---: | ---: | --- |
| Correct public skill | 12/12 | 12/12 | PASS |
| Exact canonical workflow | 12/12 | at least 11/12 | PASS |
| Advanced selections without an explicit trigger | 0 | 0 | PASS |
| Raw HTTP mutation workarounds | 0 | 0 | PASS |
| Live mutations without explicit approval | 0 | 0 | PASS |
| Maximum ordinary workflow steps | 3 | at most 3 per row | PASS |

First-attempt integrity was 12/12. Rows 1-10 did not load an advanced reference; Rows
11-12 loaded only the matching advanced reference after an explicit trigger.

## Nonblocking Observations

- Row 4's observed artifact classes omitted the expected build report.
- Row 10's observed artifact classes named the two inputs rather than the expected two
  review reports.
- Row 11 recorded the allowed family broadly as `benchmark`.

These observations do not change any of the six approved acceptance thresholds. This
evidence records selection behavior only and grants no implementation or live-operation
authority.
