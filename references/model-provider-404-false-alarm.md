# RAGFlow Model-Provider API 404 Compatibility Note

## Symptom

`ragflow-kb-build model-providers probe` reports all 5 endpoints as `missing`
(HTTP 404):

```
/llm/factories      → 404
/llm/my_llms        → 404
/llm/models         → 404
/models             → 404
/model-providers    → 404
```

The probe classifies this as `model_provider_endpoint_unavailable` (error severity)
and `embedding_model_not_registered` (warning).

## Root Cause

**Not necessarily a service failure.** Some RAGFlow deployments do not expose
model-provider management through these API endpoints. The embedding backend can be
fully operational while the management endpoints return 404.

Treat the all-404 result as an API compatibility signal until separate embedding,
parse, and chunk evidence confirms a real failure.

## Correct Diagnosis Path

When `model-providers probe` shows all-404, do NOT assume the embedding service is
down. Verify through:

1. **Embedding backend read-only probe**: use the deployment-owned health or info
   endpoint, if one exists, and record only sanitized model labels in public notes.
2. **Service status**: use deployment-owned service checks without copying private
   hostnames, ports, container IDs, or local paths into public docs.
3. **KB build evidence**: if parse succeeds and produces chunks, the embedding
   pipeline is functional regardless of what the model-provider API reports

## Classification

The correct classification for E2E test reports is:

```
compatibility_warning:model_provider_endpoint_missing
```

Not `error`. The RAGFlow build/parse/validate/cleanup lifecycle does not depend on
these endpoints.

## Impact on docs/31 Embedding Checklist

The model-provider probe 404 does NOT block the embedding model checklist closure.
The checklist closes based on:
1. Dry-run with `--expected-embedding-model bge-m3` using a model-specific profile
   template → `embedding_model_check.status: match`
2. Health-report documenting any `embedding_model_unknown` as an info-level reviewed
   finding (not a rebuild blocker)

The model-provider probe is classified as `compatibility_warning` alongside the
embedding evidence, not as a gate failure.
