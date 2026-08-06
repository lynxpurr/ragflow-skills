---
name: ragflow-query
description: Retrieve evidence from one or more reviewed RAGFlow knowledge bases and check citation or answer support. Use when Codex needs direct or deterministic auto retrieval; routing diagnosis, fusion analysis, reranking, and external evaluator boundaries require explicit advanced triggers.
---

# RAGFlow Query

## When to use

Use this skill after a reviewed KB or KB manifest exists. It owns evidence retrieval and
deterministic citation or answer-support checks; it does not upload documents, build KBs,
or synthesize answers with a script-owned LLM.

## Inputs and outputs

Inputs are a question, one or more reviewed dataset selections or a KB manifest, and a
private RAGFlow config for approved retrieval. Outputs are evidence chunks, retrieval
status, optional traces, citation audits, and deterministic answer-evaluation reports.

## Canonical workflows

### Canonical workflow: retrieve evidence

```bash
python scripts/query.py --config /private/path/ragflow-config.local.yaml ask "Question" --kb-manifest ./run/kb_manifest.json --mode direct --json
```

Use `--mode auto` only when the reviewed routing config should choose a KB. Explicitly
selected multiple datasets still use `ask`; they do not require routing diagnosis.

### Canonical workflow: review answer support

```bash
python scripts/query.py audit-citations --query-output ./run/query.json --answer-file ./run/answer.md --report-json ./run/citation-audit.json --report-md ./run/citation-audit.md --redaction-report ./run/citation-audit-redaction.json
python scripts/query.py evaluate-answer --query-output ./run/query.json --answer-file ./run/answer.md --require-citation --report-json ./run/answer-evaluation.json --report-md ./run/answer-evaluation.md --redaction-report ./run/answer-evaluation-redaction.json --json
```

## Decision and stop rules

- Use the smallest direct or deterministic-auto retrieval matching the user's selection.
- Ask one concise question if two dataset choices are equally plausible and materially
  change the result.
- Stop on missing dataset identity, missing retrieval approval, private-config ambiguity,
  or a status that requires clarification; do not broaden to routing or fusion to bypass it.
- Script-owned synthesis and evaluator calls remain disabled; external candidate artifacts
  are advisory and cannot override deterministic failures.

## Advanced triggers

Open [Advanced workflows](references/advanced-workflows.md) only for explicit routing
diagnosis, centroid planning, fusion, reranking, cross-language comparison, saved-output
diagnosis, session/intent planning, assistant review, or an external evaluator boundary.
For private config and smoke setup, use [Host agent setup](references/host-agent-setup.md).

## Security

Keep endpoints, keys, dataset identifiers, raw chunks, and private query artifacts outside
tracked files. Retrieval approval does not authorize KB mutation, model calls, or cleanup.
