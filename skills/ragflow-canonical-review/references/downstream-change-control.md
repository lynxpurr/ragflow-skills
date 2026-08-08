# Downstream Change Control

Use this reference when canonical meaning, representation, source ownership, or asset
identity changes.

## Invalidate atomically

Inventory dependent handoffs, content and package hashes, chunk snapshots, qrels,
benchmarks, preflights, staging conclusions, and release claims.

When a dependency reflects pre-change canonical content:

1. Mark it as pre-change evidence in its owning status record.
2. Preserve its payload, hashes, qrels, reports, and runtime evidence unchanged.
3. Distinguish architecture-only or delivery findings that remain valid for limited scope.
4. Generate a new versioned passthrough handoff from accepted canonical content.
5. Create a stable chunk snapshot before binding new qrels.
6. Rerun the required smoke, regression, benchmark, modality, routing, and answer gates.

Do not edit historical evidence to make it appear current.

## Benchmark ownership

- Bind a single-document question to one expected document and only decisive answer facts.
- Declare every expected document and contributed fact for cross-document questions.
- Split compound questions when source ownership or failure attribution is ambiguous.
- Treat generated queries and answer keys as candidates until reviewed.
- Do not create placeholder qrels before stable chunk evidence exists.
- Keep table dimensions, units, scope, and notes exact in answer keys.

Snapshot counts detect accidental drift but do not override source-supported changes.

## Stage boundaries

A static audit does not prove retrieval quality; a dry-run does not create a live manifest;
a staging build does not authorize production routing; direct retrieval does not prove
answer-layer behavior; and image recall does not prove front-end delivery. Report each
stage as a separate outcome.
