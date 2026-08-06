# Advanced RAGFlow Query Workflows

Load one section only for an explicit request or a named core retrieval finding. Advanced
analysis does not broaden dataset, network, model, or mutation authority.

## Routing and centroid diagnosis

Trigger: the user explicitly asks to inspect KB routing, route tests, activation, or a
centroid tie-breaker. Use `list-kbs`, `route`, `route-test`, `route-report`,
`route-diagnose`, `route-activation-check`, or `centroid build`. Centroid work consumes
user-owned vectors and does not call an embedding service.

## Query planning and context

Trigger: the user asks for deterministic rewriting, intent/session inspection, or a
host-assisted plan. Use `rewrite`, `intent classify|route`, `session inspect|enrich`,
`agentic-plan`, or `table-strategy`. These helpers do not call an LLM or mutate RAGFlow.
Agentic-answer request/review commands remain maintainer-facing compatibility candidates.

## Fusion, reranking, and cross-language comparison

Trigger: the user explicitly requests multi-result fusion or saved-output A/B analysis.
Use `fusion`, `rerank-ab`, `cross-language-ab`, or `pollution-report` on reviewed outputs.
`fusion-test` and `fallback-test` are maintainer/developer surfaces, not normal user steps.

## Saved-output and assistant diagnosis

Trigger: a saved query needs explanation or the user supplies assistant handoff artifacts.
Use `diagnose-result`, `cache-report`, `assistant-profile recommend`,
`assistant-test-plan`, or `validation-suggestions`. Use `endpoint-report` only with an
explicit endpoint-review request; network checking is separately opt-in.

## External evaluator boundary

Trigger: the user explicitly supplies or requests a host-owned evaluator candidate after
deterministic answer checks. Use `evaluator request` and `evaluator review`. The scripts
do not call a model, and advisory output cannot override citation or deterministic failures.

## Boundaries

`bootstrap-smoke`, `fallback-test`, `fusion-test`, and agentic-answer request/review are
internal candidates retained for compatibility and release coverage. Do not enable
script-owned synthesis, `serve`, raw HTTP workarounds, or unapproved dataset access. See
[Host agent setup](host-agent-setup.md) for private configuration and smoke rules.
