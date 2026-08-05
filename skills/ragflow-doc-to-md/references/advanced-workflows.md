# Advanced RAGFlow Doc To MD Workflows

Load one section only when its trigger is explicit or a core report names the matching
finding. These commands preserve existing compatibility; they are not extra default steps.

## Backend or protocol diagnosis

Trigger: the user asks to inspect a converter, or a core conversion reports backend,
protocol, timeout, or resource uncertainty.

Use `backend probe`, then `backend warmup` only with a reviewed tiny fixture and explicit
network/conversion approval. Backend flags remain host-owned; do not probe every backend.

## Source and adaptive-policy diagnosis

Trigger: source features or an adaptive decision need explanation.

Use `inspect-source`, `adaptive --decision-only`, or `compare-adaptive-summaries`. These
commands inspect or compare reports; they do not create RAGFlow authority.

## Existing handoff review and deterministic cleanup

Trigger: the user asks to regenerate handoff quality or apply a named postprocess profile.

Use `inspect` for an existing manifest and `postprocess` for a reviewed output path. Keep
in-place rewriting behind its explicit write confirmation.

## Long-document splitting and packaging

Trigger: a long document requires segmentation, resumable split materialization, or a rich
handoff package.

Use `segment-plan` before `split`; use `package` only for the requested handoff form. Keep
the generated manifest and checkpoint with the handoff.

## Retained-package comparison

Trigger: the user explicitly asks for a read-only replacement comparison.

Use `compare-retained-package`. It records static comparison evidence only and must not be
described as paired live A/B evidence.

## Boundaries

Do not contact MinerU, use credentials, or run conversion without the authority required
by the selected backend. Stop on missing inputs, unsafe output paths, or `BLOCKED` quality.
See [Host agent setup](host-agent-setup.md) for private configuration and smoke rules.
