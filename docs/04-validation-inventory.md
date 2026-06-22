# Validation Inventory

Phase 6 keeps public validation as one stable command surface instead of shipping the old script sprawl.

| Source family | Public classification | Public path |
|---|---|---|
| Retrieval smoke and KB existence checks | `smoke` | `ragflow-kb-build/scripts/validate.py --level smoke` |
| Query-set hit checks, route regression, watchdog-style checks | `regression` | `validate.py --level regression --queries queries.json` |
| Comparative profile runs, gates, trend reports, RAGAS-style suites | `benchmark` | `validate.py --level benchmark --queries queries.json`; heavier runners stay opt-in backlog |
| Data repair, private KB audits, personal datasets | `private` | Not shipped in public skills |
| One-off experiments and migration helpers | `legacy` | Not shipped in public skills |

The public query-set contract is intentionally small:

```json
{
  "queries": [
    {
      "id": "q1",
      "question": "Question text",
      "min_chunks": 1,
      "expected_terms": ["term"],
      "expected_documents": ["source.md"]
    }
  ]
}
```

Formal metric plugins and large benchmark datasets are deferred until external users need them.
