# Field Trial Observation Plan

Status: active observation gate
Date: 2026-07-02

## Objective

Use the existing public skill suite in real workflows before opening any remaining gated
implementation work. The goal is to collect enough sanitized evidence to decide whether a
local service wrapper, product adapter, optional script-owned LLM backend, or private
bridge is actually needed.

This plan is intentionally observational. It does not add public command behavior, default
hosted services, script-owned model calls, live mutation, or private product logic.

## Observation Boundary

Public records may include:

- command names and sanitized flags;
- source type, approximate document count, and approximate size;
- artifact type and relative artifact names;
- elapsed time, pass/fail status, and summarized report metrics;
- redacted error classes and friction notes;
- a gated-work recommendation.

Public records must not include:

- API keys, bearer tokens, cookies, or secret fragments;
- real private endpoints, private IPs, or private hostnames;
- full home paths or private config paths;
- private KB names, private corpus names, or proprietary document titles;
- raw retrieved chunk text, raw model prompts, or raw model responses;
- private adapter implementation notes that belong outside public release artifacts.

Raw local artifacts can be retained under a private run directory, but public summaries
should keep only sanitized findings and paths that are safe to share.

## Signals To Watch

| Track | Signals | Evidence to collect |
| --- | --- | --- |
| CLI sufficiency | Repeated command spawning is slow, artifact handoff is brittle, or host agents struggle to preserve paths between steps. | Workflow name, command count, elapsed time, failed step, and whether one-shot CLI was enough. |
| `ragflow-query serve` | A host needs health checks, request IDs, persistent state, high request volume, explicit shutdown, or lower per-call latency than CLI spawning can provide. | Target host, CLI insufficiency, request profile, lifecycle owner, auth/redaction expectations, and success/failure criteria. |
| Handoff quality | `doc_manifest.json` is missing, invalid, blocked by quality gate, references missing assets, or contains empty/garbled Markdown. | `convert --json`, `inspect` summary, quality gate status, document count, warning classes, and sanitized report paths. |
| KB build stability | `build --dry-run` fails, parser settings are unclear, live parse stalls, cleanup is risky, or runtime partial failures repeat. | Dry-run result, profile ID, probe result, runtime metrics, parse report summary, and cleanup readiness summary. |
| Query quality | Zero results, wrong top document, unstable top-k, weak citation coverage, unsupported answer claims, or poor follow-up behavior. | Query mode, validation report summary, trace summary, `audit-citations` result, `evaluate-answer` result, and expected metric movement. |
| Private handoff bridge | Private content can or cannot become an ordinary Markdown handoff without a custom adapter. | Sanitized source shape, handoff result, whether passthrough produced `doc_manifest.json`, and why adapter code would be needed. |
| Remote conversion | Existing builtin, MinerU, generic remote, and local CLI conversion paths do not match a real converter contract. | Endpoint protocol summary, auth shape, request/response examples with fake values, error model, and fake-server fixture requirements. |
| Provider abstraction | A concrete non-current provider contract is needed and cannot fit existing OpenAI-compatible or request/review paths. | Provider label, API shape, config keys, fake-provider fixture, fallback behavior, and downstream acceptance criteria. |
| Reranker adapter | Saved-query or benchmark evidence shows retrieval/fusion/rewrite/profile tuning is insufficient and reranking has a measurable target. | Saved query output, external rerank JSON if available, benchmark delta, expected metric movement, and direct-retrieval fallback policy. |
| Optional LLM backend | Request/review workflows work but manual external model use becomes repetitive or error-prone. | Request/review frequency, failure classes, fake-provider requirements, advisory marking, citation compatibility, and redaction needs. |
| Release health | Real use changes assumptions about archives, runtime wheels, vendoring, platform smoke, or generated report safety. | Validation command list, pass/fail result, generated artifact list, and release-hygiene notes. |

## Per-Run Record Template

Create one short record per meaningful real workflow. Keep private details outside the
public repository and paste only sanitized summaries into public planning notes.

```markdown
## YYYY-MM-DD run-NNN

Workflow:
- doc-to-md / kb-build / query / private-handoff / host-agent / release-validation

Input summary:
- Source type:
- Approximate document count:
- Approximate size:
- Private details removed:

Commands:
- Sanitized command or command group:

Artifacts:
- Public-safe artifact names:
- Private artifact location retained outside public repo:

Results:
- Pass/fail:
- Elapsed time:
- Quality gate:
- Build/probe/parse status:
- Query or validation summary:

Friction:
- What was slow, brittle, unclear, repetitive, or unsafe:

Gated trigger:
- none / serve / private bridge / remote conversion / provider / reranker / LLM backend

Decision:
- keep observing / open design gate / implement focused slice / reject for now
```

## Trigger Rules

Open gated implementation only when observation evidence crosses one of these thresholds:

- `ragflow-query serve`: at least three real host-agent runs show one-shot CLI is the
  wrong shape, or one critical host workflow requires health, lifecycle, request
  correlation, or persistent endpoint semantics.
- Private bridge: at least one real private workflow cannot reliably produce a public
  Markdown `doc_manifest.json` handoff through passthrough conversion.
- Remote conversion client: a user-owned converter endpoint has a concrete protocol,
  auth shape, request/response examples, error model, and fake-server fixture plan.
- Provider abstraction: one named provider contract cannot fit current config,
  OpenAI-compatible behavior, or request/review artifacts, and has a fake-provider test
  plan.
- Reranker adapter: saved-query or benchmark evidence defines a measurable ranking target
  that current retrieval, fusion, rewrite, profile tuning, or `rerank-ab` comparison
  cannot cover.
- Optional LLM backend: request/review artifacts are stable, manual external model use is
  a real bottleneck, and fake-provider fixtures can prove auth failure, timeout,
  malformed output, unsupported claims, missing citations, overlong output, and redaction.

If none of these triggers is met, keep using the current CLI/archive path and run periodic
release validation instead of adding more product surface.

## Review Cadence

Use this lightweight loop during the field trial:

1. Record sanitized findings after each meaningful workflow.
2. Review accumulated records after five runs, after a repeated failure pattern, or before
   any request to implement gated work.
3. Update `docs/03-development-plan.md` only when a gate is satisfied, rejected, or
   intentionally deferred with evidence.
4. Run docs-only validation for planning updates and the release-facing chain for public
   command, artifact, or release-surface changes.

## Current Decision

The next stage is observation, not feature expansion. The public CLI/archive path remains
the canonical baseline. The remaining open tasks should stay gated until this plan
produces concrete evidence that one of them is needed.
