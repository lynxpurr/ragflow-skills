# Agent Session Handoff And Bounded-Execution Lessons

Status: active maintainer guidance

Date: 2026-07-14

## Purpose

This document records process lessons from a long-running agent session whose handoff
expanded into repeated governance, review, implementation, and archival batches. It is
public-safe maintainer guidance. It does not record private execution values, change any
technical task state, or create authority for live work.

The central lesson is simple:

> A handoff should transfer enough state for the next session to perform one useful
> task. It must not become a second implementation project.

## What Went Wrong

The original need was ordinary session continuity: preserve completed work, identify
remaining tasks, retain unique evidence, and give a new session a reliable starting
point. The first inventory and successor summary served that purpose.

The process then continued beyond handoff:

- authorization semantics were redesigned;
- several request revisions and exact-SHA review sidecars were created;
- repository attestation became a separate batch;
- new transaction, contract-generation, recovery, and supervisor code was developed;
- full focused and package test suites were run;
- rejected candidates generated additional successor drafts and archive manifests.

Those later activities may have produced useful engineering evidence, but they were not
handoff work. Calling all of them handoff obscured progress, made completion difficult to
recognize, and allowed every new finding to create another preparatory batch.

## Separate The Four Kinds Of Work

Every session-continuity request should classify work before acting.

| Work class | Purpose | Typical output |
| --- | --- | --- |
| Handoff | Transfer known state and one next task | One concise summary or tracked document |
| Diagnosis | Determine why a known problem exists | Evidence-backed finding and correction boundary |
| Implementation | Change code, tests, or behavior | Reviewed diff and validation results |
| Authorization | Permit a gated external or live action | Explicit approval bound to the actual authority object |

Archival is a supporting activity, not a fifth project phase. Archive only unique evidence
that would otherwise be lost. Do not archive every intermediate explanation merely
because it exists.

One batch may contain closely coupled work, but its work class and terminal outcome must
remain clear. A batch that only prepares another batch should be exceptional.

## Handoff Definition Of Done

A handoff is complete when the next session can answer all of these questions without
reading the prior conversation:

1. What repository, branch, and commit are in scope?
2. Is the tracked worktree clean, and are there known uncommitted user changes?
3. What work is complete and supported by current evidence?
4. What remains incomplete or blocked?
5. What is the single next useful task?
6. What actions are allowed, forbidden, or separately approval-gated?
7. Which small set of files or artifacts must be read, and how is their identity checked?
8. What exact result should the next session return before stopping?

Ordinarily, this requires one human-readable record. Add a machine-readable manifest only
when a genuinely large artifact set needs deterministic inventory or retention rules.
Do not create review sidecars, successor chains, or approval objects for an ordinary
status summary.

## Dependency Closure Before Gated Execution

A hash-pinned executable inventory does not by itself prove that an execution package is
runnable. Before handing off a credential-reading or live-capable stage, classify every
file the process can require as one of:

- preexisting executable or test input;
- preexisting staged read-only input;
- external read-only reference;
- runtime-produced file;
- final output; or
- forbidden input.

The resulting dependency closure must account for every preexisting read and every
runtime-produced prerequisite. Missing, unexpected, or implicit inputs must be zero
before authority is requested.

Test setup is part of this review. If a passing test copies fixtures into a temporary
root before invoking the code, the production orchestration must contain an equivalent,
explicitly authorized staging step or the test does not prove production feasibility.
Do not confuse an executable-file allowlist with the complete pre-dispatch filesystem
contract.

## Batch Size And Stop Rules

Use these defaults for agent-driven continuation:

- Each batch must produce a user-visible result, not merely another plan to produce it.
- Give the batch one primary objective and one terminal stop.
- Permit at most one correction round unless the user explicitly requests more.
- A rejected candidate remains rejected; do not automatically manufacture a successor.
- Do not start the next batch automatically, even when its direction appears obvious.
- When a small, well-evidenced correction is already known, combine confirmation and the
  correction in one bounded offline batch instead of creating separate audit, design,
  implementation, and handoff batches.
- If evidence is insufficient, return one clear blocker. Do not widen filesystem,
  network, service, or authorization scope to avoid stopping.
- If repeated request revisions reveal another structural contradiction at execution
  time, stop creating successor requests automatically. Treat that as an architecture or
  integration-test problem and require an explicit decision before another correction.

For an in-flight process that has already been split too far, allow an already-running,
safe, bounded read-only batch to finish. Then switch to direct problem solving. Do not
add another archive-only or handoff-only batch unless new unique evidence must be saved.

## When Exact-SHA Review Is Appropriate

Exact-SHA binding and independent review are valuable when changed bytes materially
change authority or risk. Appropriate examples include:

- a live-mutation run contract;
- a credential-reading helper or executable package;
- a destructive cleanup request;
- a release artifact or public schema contract;
- an immutable object that the user will explicitly authorize by digest.

They are usually excessive for:

- ordinary handoff prose;
- progress summaries;
- read-only diagnostic notes;
- archive indexes that create no authority;
- restatements of facts already bound by a controlling artifact.

If a reviewed object changes, repeat review only when the object still carries a real
authority or compatibility boundary. Do not propagate exact-SHA review recursively to
every document that mentions another reviewed object.

## Independent Review Policy

Independent reviewers should answer materially different questions, such as governance
and execution safety. They should not exist merely to duplicate file hashing.

Use two independent reviews when both are true:

1. the object can authorize or materially shape a high-risk action; and
2. disagreement would change whether the action may proceed.

For normal offline changes, use ordinary code review plus relevant tests. For handoff,
the receiving session can independently verify the small controlling set as part of its
normal start-state check.

## Goal Mode Guidance

A persistent goal is useful when the objective is concrete, authorized, and measurable,
for example implementing one feature and passing a defined test chain. It is a poor fit
for handoff reconstruction or an open-ended series of approval gates.

Before using a persistent goal, define:

- one objective stated as an outcome, not a broad topic;
- the files, systems, and authority in scope;
- the validation that proves completion;
- the conditions that require an immediate stop;
- the external decisions that cannot be inferred;
- a bounded correction policy.

Do not use goal persistence to bridge user-authorization boundaries. When the next step
requires a new exact approval, end the current task and ask for that approval. Do not keep
an active goal alive merely to wait for future authority.

Handoff itself should normally not use goal mode. Its completion criterion is the
successful transfer of state, not the completion of the underlying engineering project.

## Permission Design

Permissions should follow risk categories rather than individual prose steps.

Reasonable categories include:

- local read-only inspection;
- tracked offline edits and tests;
- private temporary-file handling;
- network or Git remote access;
- credential or live-config access;
- live service mutation;
- destructive cleanup.

Keep network, credential, mutation, and cleanup authority explicit. Avoid requiring a
new approval for every harmless metadata read or every internal document revision. Too
many microscopic permission gates encourage agents to build elaborate authorization
objects instead of completing the useful work.

An authorization must still be narrow enough that it cannot silently migrate into a
different stage. In particular, offline preparation, credential-backed preparation,
and live mutation remain separate decisions.

## Storage And Cross-Session Discoverability

Conversation history is not automatically available to a new CLI session. Private local
files also do not help unless the new session is explicitly told where they are and why
they matter.

Use this hierarchy:

1. Put durable, public-safe process guidance in tracked repository documentation.
2. Put current task state in one concise handoff message that the user can transfer.
3. Keep sensitive or content-bearing evidence in private storage and reference it by a
   small, explicit path-and-identity list.
4. Treat temporary directories as evidence locations, not as an implicit session memory
   database.

The handoff message must remain self-contained even when supporting files exist. Disk
bytes outrank narrative for identity and technical facts, but narrative is still needed
to tell the receiving session which bytes are controlling.

## Superseding Stale Continuity Records

A handoff becomes stale when a later accepted request, execution blocker, or owner
decision changes its stated next action. Do not edit an exact-SHA-reviewed handoff in
place. Create one concise, non-overwriting successor that:

- identifies the superseded path and digest;
- records the later blocker or accepted authority object;
- states one current next task and one terminal stop;
- explicitly says whether it creates operational authority; and
- leaves all historical files unchanged.

An ordinary session-continuity successor should not acquire recursive independent-review
requirements merely because earlier authority objects were reviewed. The receiving
session should verify the small controlling set at startup, while the user's transferred
message supplies any new exact authorization. Only one session may consume that
authorization.

## Compact Handoff Template

Use the following structure unless the task genuinely requires more.

```text
Objective
- One sentence describing the unfinished outcome.

Current state
- Repository, branch, commit, worktree status.
- Last verified user-visible result.

Completed
- Only facts supported by current files or fresh validation.

Blocked or incomplete
- One list, with the actual blocking condition.

Next task
- One bounded task that produces a useful result.

Allowed
- Read/write/test categories permitted in this batch.

Forbidden or separately gated
- Network, credentials, live mutation, deletion, commit/push, or unrelated scope.

Required inputs
- The smallest controlling file set, with identity checks where material.

Stop conditions
- Drift, failed validation, missing authority, or scope expansion.

Return
- Exact files changed, validation results, remaining blocker, and whether the next
  authorization is required.
```

## Review Questions Before Sending A Handoff

Before sending the handoff to another session, ask:

- Can the receiving session start useful work from this message alone?
- Does this instruction accidentally ask it to redo completed inventory?
- Is the next task engineering work, or merely preparation for more preparation?
- Are exact-SHA and dual review protecting a real authority boundary?
- Can an obvious correction be handled in the same bounded batch?
- Does any permission restriction prevent the stated objective from being completed?
- Is there a clear terminal stop that prevents automatic batch proliferation?

If the handoff fails any of these checks, simplify it before sending.

## Operating Standard Going Forward

For this repository, future agent-session handoffs should follow these defaults:

- one tracked public-safe lessons document, not repeated private governance prose;
- one self-contained manual handoff message per session transition;
- one useful next task per batch;
- no automatic successor or follow-on batch;
- exact-SHA review only at real authority, release, compatibility, or destructive-action
  boundaries;
- private evidence retained only when unique and necessary;
- direct implementation resumes as soon as the handoff has transferred enough state.

The quality of a handoff is measured by how quickly the next session can safely produce
a useful result, not by the number of manifests, reviews, or archived intermediate files
created around it.

## 2026-08-06 Fresh-Context Review And Ref-Cleanup Lessons

The skill-surface review and compatibility closeout added several reusable boundaries:

- A reviewer-harness failure is its own result. Missing native reviewers, unavailable
  terminal payloads, or fallback context contamination must not be scored as a guidance
  failure or converted into passing evidence.
- When one logical review batch spans sessions, preserve its baseline identities, batch
  identifier, first-attempt payloads, and immutable row results. Split collection does not
  authorize reusing, rewriting, or silently completing missing rows.
- Functional supersession is different from Git ancestry. Before merging or cherry-picking
  a stale branch, compare behavior, tests, and retained value; a stronger merged fix may
  make an unmerged commit redundant even when its patch is not equivalent.
- Merge, push, and local or remote ref deletion are separate authorization objects. A
  successful code push does not authorize destructive branch cleanup.
