# Advanced RAGFlow KB Build Workflows

Load one section only for an explicit request or a named core finding. All listed commands
remain compatible, but none becomes part of the default build sequence.

## Asset and image ingestion

Trigger: the handoff contains image assets and the user asks for an asset plan or reviewed
image ingestion. Use `image-ingestion-readiness`, then `image-ingestion-execute` only when
the readiness artifact is acceptable and exact execution authority exists. A blocker is a
stop, not a reason to bypass the standard path.

## Append, refresh, parse, health, and diagnostics

Trigger: an existing KB needs an append preview, read-only state refresh, parse review, or
failure diagnosis. Use `append`, `refresh-report`, `parse-report`, `probe`, `inspect-kb`,
`diagnose`, `consistency-check`, `parameter-audit`, or `model-providers probe` according to
the named finding. Mutation and read-only access remain separately approved.

## Profiles, metadata, tags, and topology

Trigger: the user explicitly asks for profile selection, metadata/tag governance, corpus
topology, or activation review. Use `profile` commands, `metadata` commands, `tagset`
commands, `topology advise`, `topology split-plan`, or `activation-plan`. Suggestion
request/review commands package external candidates and do not call an LLM.

## Benchmark and grounded-QA governance

Trigger: the user supplies benchmark artifacts or asks for strict evidence work. Use
`benchmark` commands, `snapshot-chunks`, `suppression-report`, `segment-metadata report`,
and `qa generate|validate|map-evidence|suggest-request|suggest-review` as required. Use
Apollo validation/evaluation only for an explicitly supplied Apollo fixture; Apollo judge
request/review commands are maintainer-facing compatibility candidates, not normal user
workflows. Preserve deterministic gates and public-safe reports.

## Optimization and disposable experiments

Trigger: the user explicitly requests a reviewed profile experiment and has separate live
and cleanup authority. Begin with `optimize --plan-only`, then `optimize cleanup-plan` and
`optimize readiness`. Execution, summary, and cleanup remain distinct checkpoints; never
promote a result while cleanup or benchmark evidence is unresolved.

## Boundaries

Do not enable Stage 8C, script-owned LLM/RAGAS work, raw API mutation, or private adapters.
See [Host agent setup](host-agent-setup.md) for private configuration and live-operation
rules.
