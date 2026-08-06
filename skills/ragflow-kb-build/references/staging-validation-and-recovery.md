# Staging Validation And Recovery

Use this reference for an authorized live staging build, an interrupted parse/build recovery, post-build artifact consistency, or interpretation of live chunk and negative-query findings.

## Phase Boundaries

Keep these phases distinct:

1. Inspect the formal handoff, lint the selected profile, and run `build.py --dry-run`.
2. Obtain explicit live-build approval for the exact KB name, input manifest, profile, and scope.
3. Build or resume the versioned staging KB and write the real `kb_manifest.json`.
4. Refresh observed state, audit parse and effective-parameter visibility, and run artifact consistency.
5. Run smoke, regression, benchmark, negative, and route/answer-layer checks owned by the actual workflow.
6. Generate activation and rollback evidence only after the relevant corpus-level gates pass.

A dry-run validates planned local inputs and payloads. It does not create a dataset and cannot produce a real `kb_manifest.json`. Never synthesize dataset, document, or chunk IDs to run a post-build consistency gate early.

## Selected Profile Truth

- Preserve handoff recommendations and earlier preflight profiles as historical or advisory evidence.
- Record the exact profile used by the live build separately, including any deployment-bound clamp.
- Change only the approved effective variable. Treat `chunk_size`, `chunk_token_num`, and `parser_config.chunk_token_num` as aliases when they map to the same server behavior.
- Keep the KB name, document allowlist, embedding-model expectation, and all unrelated parameters unchanged during a single-variable adjustment.
- Do not rewrite old handoff manifests, dry-run reports, or profile-lint evidence to match a later selected profile.

## Parse Trigger And Application Errors

The bundled runtime triggers parsing with:

```text
POST /datasets/{dataset_id}/chunks
{"document_ids": ["..."]}
```

Do not assume the legacy `/datasets/{dataset_id}/documents/parse` path is accepted by the target deployment. Probe compatibility before a live release when the server version is unknown.

Treat transport and application status as separate gates. A JSON response with nonzero `code`, including a numeric string such as `"100"`, is a failure even when an HTTP client returned a response successfully. Fail before entering parse polling so an application rejection is not misreported as a timeout or an indefinitely `UNSTART` document.

Implement endpoint or response-contract corrections in the shared runtime source with focused HTTP tests. Do not patch vendored runtime files inside a released skill or add project-local fallbacks that hide the shared defect.

## Checkpoint Recovery

Use `--checkpoint` for a live build whenever dataset creation, upload, parse trigger, or parse wait may be interrupted. On failure:

1. Inspect the checkpoint and current read-only dataset state.
2. Confirm the exact KB name, dataset identity, expected document count, target document count, and embedding model.
3. Confirm which documents are checkpointed as uploaded or parse-triggered.
4. Fix the shared cause, then rerun with `--resume` and the same checkpoint.
5. Verify that resume skips confirmed creation/upload work and emits one final real manifest.

Do not create another suffixed KB, repeat confirmed uploads, or use `--force-reupload-confirmed` merely to work around a trigger failure. Those actions introduce duplicates and destroy failure attribution.

## Post-Build Evidence

Use the real manifest as the identity contract for downstream checks. Compare it with a fresh read-only observed-state report before making parse or chunk claims.

- Run artifact `consistency-check` only after the real manifest exists.
- Treat final manifest/read-back document state and chunk count as the completion gate.
- Preserve differences between parse progress messages and final indexed counts as findings; do not silently normalize them.
- When read-back does not expose effective `parser_config`, report requested fields as `not_observable`. Payload acceptance does not prove effective server values.
- Interpret `health-report` findings by ownership. A missing activation plan can produce `REVIEW` without implying parse or retrieval failure.

## Live Chunk Findings

Canonical chunk markers express reviewed semantic boundaries; they are not a promise that every RAGFlow parser will create one live chunk per marker. The server may merge boundaries, create parent/child variants, or add an alternate HTML representation of a Markdown table.

When this happens:

- preserve the source-faithful canonical and the current staging baseline;
- compare authoritative content and alternate chunks by context, completeness, rank, and qrel ownership;
- record context-free or unaccepted duplicate chunks as ranking-pollution findings;
- run smoke, regression, and benchmark coverage before changing the profile or canonical text;
- start a new single-variable experiment only when a reviewed gate shows material recall, ranking, grounding, or correctness degradation.

Do not split a complete table or remove required heading context solely to silence a static consistency heuristic.

## Negative And Answer-Layer Gates

A forced query against one explicitly selected KB may return a similar chunk for an out-of-scope question. Non-empty forced retrieval does not prove that the application should answer and does not evaluate abstention.

- Keep retrieval diagnostics separate from final-answer policy.
- Test abstention through the actual application entry point, with its real routing, prompt, threshold, and answer logic frozen.
- Retain the final answer, citations, and refusal decision in restricted evidence, plus a sanitized public result.
- Do not create route tests when the real entry point does not use that route mechanism.

## Retention And Transfer

Keep real dataset/document/chunk IDs, private endpoints, checkpoints, raw query text, raw chunk text, and unsanitized reports in restricted runtime storage. Retain only reviewed public summaries, stable hashes, aggregate metrics, redaction sidecars, and non-secret command contracts in portable Git.

Before commit or transfer:

1. Review the explicit staged file list; do not use a recursive catch-all add.
2. Scan staged blobs for IDs, credentials, private URLs, local paths, and raw evidence.
3. Confirm ignore rules cover real manifests, checkpoints, private snapshots, and unsanitized reports as required by the project.
4. Run repository transfer or release verification after files are tracked.
