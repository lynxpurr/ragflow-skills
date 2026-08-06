---
doc_type: plan
topic: optional-llm-backends
status: gated
created: 2026-07-02
updated: 2026-08-04
canonical: true
implementation_authority: false
owner_spec: null
supersedes: []
superseded_by: null
related: []
gate: explicit_backend_implementation_request_with_deterministic_fixtures_and_safety_gates
---

# Optional LLM Backend Planning

Status: planning gate; script-owned backend execution deferred
Date: 2026-07-02

## Objective

Define the gate for any future script-owned LLM or RAGAS-style backend execution without
changing the current safe default: public commands remain deterministic, no-network by
default, and do not call generation or evaluator models unless a later implementation
meets this gate.

This gate covers the remaining optional LLM/backend work:

- metadata suggestion backend execution beyond request/review artifacts;
- grounded-QA LLM generation;
- `ragflow-query agentic-answer` script-owned execution;
- optional reflection with a strict iteration budget;
- evidence-only synthesis from retrieved chunks;
- script-owned agentic-answer execution after request/review;
- optional LLM/RAGAS-style evaluator backend execution.

## Current Safe Boundary

The suite already has request/review contracts that let a host-approved external model be
used without the public scripts invoking that model:

| Surface | Current behavior | Required review before use |
| --- | --- | --- |
| `ragflow-kb-build metadata suggest-request` / `suggest-review` | Packages advisory metadata requests and reviews external candidates. | Metadata lint, advisory/generated markings, path checks, Markdown/report redaction. |
| `ragflow-kb-build qa suggest-request` / `suggest-review` | Packages grounded-QA requests and reviews external QA candidates. | `qa validate`, evidence-map compatibility, advisory/generated markings, redaction. |
| `ragflow-query agentic-answer request` / `review` | Packages evidence and citation rules for external answer synthesis. | Citation audit, `evaluate-answer`, advisory/generated markings, redaction. |
| `ragflow-query evaluator request` / `review` | Packages deterministic answer-evaluation context for external evaluator scoring. | Advisory/generated markings; external verdicts must not override deterministic failures. |
| `ragflow-query evaluate-answer` and `audit-citations` | Deterministic answer and citation gates. | These remain non-overridable by optional evaluator scores. |

Any script-owned backend must consume and emit the same contracts rather than inventing a
parallel prompt or result format.

## Unified Config Contract

A future implementation may read LLM config only from explicit config files, environment
variables, or command flags. There must be no default hosted endpoint or default model.

Required config fields before any model call:

| Field | Requirement |
| --- | --- |
| `llm.base_url` or equivalent flag/env | Required; no default endpoint. |
| `llm.api_key` or host secret reference | Required for non-local endpoints; never printed. |
| provider label | Required in generated artifacts for auditability. |
| model label | Required in generated artifacts for auditability. |
| timeout | Required bounded value with a conservative default only after execution is explicitly enabled. |
| max input/output budget | Required; enforce bounded prompt and output sizes. |
| temperature or decoding mode | Required; deterministic or near-deterministic defaults for tests. |
| execution flag | Required; request/review remains the default when the flag is absent. |

Redaction requirements:

- redact API keys, bearer tokens, provider endpoints, private hosts, home paths, config
  paths, and prompt fragments that contain private paths or private URLs;
- write sanitizer sidecars for JSON and Markdown reports;
- never persist raw prompts or raw model responses in public examples;
- bound retrieved chunk text included in prompts and reports.

## Deterministic Fixture Gate

Before code opens for any script-owned backend, add neutral fixtures that prove:

- success with a valid candidate payload;
- timeout and direct fallback behavior;
- HTTP 401/403 or missing credential handling;
- malformed JSON or wrong schema rejection;
- unsupported claims are caught by deterministic review;
- missing or invalid citations are caught by citation audit;
- prompt-injection-like output remains advisory and cannot bypass review;
- overlong output is rejected or truncated with an explicit warning;
- generated reports and redaction sidecars do not leak fake secrets, fake private hosts,
  home paths, config paths, or raw private endpoints.

Tests must use fake clients or fake HTTP servers. Live provider calls are not required for
closing a public implementation and must remain opt-in if added later.

## Candidate Priority

| Candidate | Priority | Reason |
| --- | --- | --- |
| Grounded-QA LLM adapter | First code candidate after this gate is satisfied. | Output can be validated by `qa validate`, evidence mapping, advisory markings, and benchmark preflight before it affects retrieval gates. |
| Metadata suggestion backend | Possible early candidate. | Output is advisory and already has deterministic metadata lint, but it affects governance sidecars rather than retrieval or answers. |
| Agentic-answer execution | Later candidate. | User-facing answer generation requires citation audit, `evaluate-answer`, evidence-only synthesis, strict token limits, and strong fallback behavior. |
| Reflection | Later candidate, tied to agentic-answer execution. | It can amplify bad retrieval or prompt drift unless iteration budgets and trace review are strict. |
| LLM/RAGAS evaluator backend | Later candidate. | External evaluator scores must not override deterministic answer-evaluation failures, so value is lower until concrete evaluator acceptance exists. |
| General provider abstraction | Last. | A broad abstraction without a named provider contract creates compatibility burden before value is proven. |

## Implementation Acceptance Checklist

A script-owned backend item can be marked implemented only when all of these are true:

- One candidate is selected; do not implement multiple backend surfaces in one slice.
- Existing request/review artifacts remain available and remain the default path.
- Execution requires explicit config plus an explicit execution flag.
- Fake-client or fake-server tests cover success, auth failure, timeout, malformed output,
  overlong output, unsupported claims, missing citations, and redaction.
- Generated outputs are marked advisory/generated and must pass the existing review gate
  before downstream use.
- Agentic answers synthesize only from retrieved evidence and emit numeric citations
  compatible with `audit-citations`.
- Deterministic gates such as `qa validate`, `evaluate-answer`, and `audit-citations`
  cannot be bypassed by model output.
- Runtime traces record model labels, latency, bounded token estimates, fallback path,
  and script-owned call counts without logging secrets.
- Consumer acceptance and strict-vendor platform smoke are updated before closing the
  public command surface.

## Current Decision

No script-owned LLM/RAGAS backend code should start yet. The next code slice, if this track
is approved later, should be grounded-QA LLM generation with a fake provider because it has
the strongest deterministic review path and the lowest user-facing answer risk.
