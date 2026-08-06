# ragflow-skills E2E Checklist Closure Workflow

When closing remaining checklist items in `docs/31-hermes-e2e-improvement-follow-up-plan.md`
(or similar docs/N-*.md improvement plans), follow this systematic offline verification workflow.

## Principles

1. **Only check items when evidence is sufficient.** If an input is missing or a scope is
   gated (e.g., `ROUTING_SCOPE=no`), leave the checkbox unchecked and document why.
2. **Private artifacts stay private.** Raw reports go to `PRIVATE_RUN_ROOT`; public docs
   only record sanitized conclusions (no paths, endpoints, dataset IDs, API keys, raw chunks).
3. **Run the full verification chain, then update docs, then re-verify.**

## Verification Chain (per checklist category)

### Refresh API Compatibility

Confirms `refresh-report` / `parse-report` / `health-report` handle zero-document
document-list API responses when build/parse/chunk evidence exists.

```bash
cd <ragflow-skills-repo>

# 1. Compile check
python3 -m py_compile \
  packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py \
  packages/ragflow-skill-runtime/src/ragflow_skill_runtime/parse_report.py \
  skills/ragflow-kb-build/scripts/build.py

# 2. Targeted tests
python3 -m pytest packages/ragflow-skill-runtime/tests/test_kb_build_cli.py -q -k \
  "refresh_report_classifies_empty_document_list_with_manifest_parse_evidence or \
   parse_report_surfaces_refresh_zero_document_compatibility_warning"

# 3. Schema identity
python3 tools/schema_identity_check.py --report-json "$PRIVATE_RUN_ROOT/schema_identity.json" \
  > "$PRIVATE_RUN_ROOT/schema_identity.stdout"

# 4. Release hygiene
python3 tools/release_hygiene_check.py > "$PRIVATE_RUN_ROOT/release_hygiene.json"
```

Pass criteria: `py_compile` exit 0, 2 tests passed, schema identity `ok=true` / 0 failures,
release hygiene `ok=true` / 0 findings.

### Embedding Model Check

Two-step: dry-run with a model-specific profile template, then health-report against KB
manifest to detect model-neutral profile gaps.

```bash
# Step 1: Dry-run with model-specific profile
python3 skills/ragflow-kb-build/scripts/build.py \
  --doc-manifest <private doc_manifest.json> \
  --retrieval-hints <private retrieval_hints.json> \
  --kb-name reviewed-placeholder-kb \
  --profile skills/ragflow-kb-build/templates/bge-m3-zh-512.json \
  --expected-embedding-model bge-m3 \
  --dry-run --json > "$PRIVATE_RUN_ROOT/embedding_dry_run.json"

# Check: embedding_model_check.status == "match", matches_expected == true

# Step 2: Health-report against existing KB manifest
python3 skills/ragflow-kb-build/scripts/build.py health-report \
  --kb-manifest <private kb_manifest.json> \
  --parse-report <private parse_report.json> \
  --observed-state <private kb_refresh_report.json> \
  --expected-embedding-model bge-m3 \
  --report-json "$PRIVATE_RUN_ROOT/kb_health_report.json" \
  --report-md "$PRIVATE_RUN_ROOT/kb_health_report.md" \
  --json
```

Key fields to verify in dry-run output:
- `embedding_model_check.status`: must be `match`
- `embedding_model_check.matches_expected`: must be `true`
- `embedding_model_check.rebuild_or_reparse_required`: must be `false`

Health-report may show `embedding_model_unknown` (info severity) if the KB was built with a
model-neutral profile (`profile_embedding_model_missing`). This is a reviewed finding, not
a rebuild blocker — document it and note that future builds with the model-specific template
will carry embedding-model evidence into the manifest.

### Routing / Route Tests / ragflow-query Validation

Optional scope (`ROUTING_SCOPE=yes` required). When `ROUTING_SCOPE=no`, do NOT check the
routing checklist; document it as gated follow-up.

When in scope, run:
```bash
python3 skills/ragflow-kb-build/scripts/build.py activation-plan \
  --kb-manifest <kb_manifest> --doc-manifest <doc_manifest> \
  --route-config "$ROUTING_CONFIG" --retrieval-hints <retrieval_hints> \
  --route-tests "$ROUTE_TESTS" \
  --output "$PRIVATE_RUN_ROOT/kb_activation_plan.json" \
  --report-md "$PRIVATE_RUN_ROOT/kb_activation_plan.md" --json

python3 skills/ragflow-query/scripts/query.py route-test \
  --routing-config "$ROUTING_CONFIG" --queries "$ROUTE_TESTS" \
  --report-json "$PRIVATE_RUN_ROOT/route_test_report.json" \
  --report-md "$PRIVATE_RUN_ROOT/route_test_report.md" --json

python3 skills/ragflow-query/scripts/query.py route-activation-check \
  --activation-plan "$PRIVATE_RUN_ROOT/kb_activation_plan.json" \
  --routing-config "$ROUTING_CONFIG" \
  --route-test-report "$PRIVATE_RUN_ROOT/route_test_report.json" \
  --report-json "$PRIVATE_RUN_ROOT/route_activation_check.json" \
  --report-md "$PRIVATE_RUN_ROOT/route_activation_check.md" --json
```

## Post-Edit Verification

After updating docs with checklist closures:

```bash
# Whitespace/errors
git diff --check

# Secret leak scan (must return only pre-existing prohibition mentions)
rg -n "/home/|192\.168|127\.0\.0\.1|/tmp/|api[_-]?key|bearer|token|dataset_id|document_id|kb:" \
  docs/31-hermes-e2e-improvement-follow-up-plan.md || true

# Final release hygiene
python3 tools/release_hygiene_check.py > "$PRIVATE_RUN_ROOT/final_release_hygiene.json"
```

## Checklist Closure Gating Logic

| Category | Close when | Keep gated when |
|---|---|---|
| Refresh API compat | 2 pytest pass + schema identity ok + hygiene ok | Tests fail or code not compiled |
| Embedding model | Dry-run `match` + health-report reviewed (info risks OK) | `EXPECTED_EMBEDDING_MODEL=UNKNOWN` or missing artifacts |
| Routing | activation-plan + route-test + route-activation-check all reviewed | `ROUTING_SCOPE=no` or missing routing config |

## release_hygiene_check Output Structure

The JSON output uses `findings` (a list), not `findings_count`. Check with:
```python
d = json.load(open(path))
ok = d.get("ok")           # bool
findings = d.get("findings")  # list
```
