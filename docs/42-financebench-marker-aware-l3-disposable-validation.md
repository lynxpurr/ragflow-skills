# FinanceBench Marker-Aware L3 Disposable Validation Contract

Status: L3-PREP reviewed; live execution is not authorized
Date: 2026-07-12
Owning plans:

- `docs/40-marker-aware-evidence-validation-and-promotion-plan.md`
- `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`
- `docs/35-standard-benchmark-dataset-integration-plan.md`

## Purpose And Authority Boundary

This document defines the proposed FinanceBench L3 disposable build, observed-evidence,
query, retention, and cleanup contract. It is an authorization design, not an execution
record and not live approval.

The current authority is L3-PREP only. Under L3-PREP, maintainers may verify public code,
the specifically authorized retained evidence, hashes, and offline reports. They may not
make any RAGFlow HTTP request, create or inspect a live dataset, upload a document,
trigger parsing, run retrieval, delete a dataset, or perform a cleanup probe.

The final action in this document is always `approval_required`. A later live run needs a
new, explicit authorization that pins the execution commit, private run contract,
disposable name, live config source, operation counts, and cleanup obligations. Authority
from L0, L1, L2, or this L3-PREP review is not reusable.

Explicit exclusions for both preparation and the proposed L3 run:

- no MinerU rerun, source reacquisition, DeepDoc, native-PDF comparison, or visual-asset
  ingestion;
- no script-owned LLM, RAGAS, answer generation, or answer-level citation audit;
- no Stage 8C, L4, high-level or low-level default change, or profile promotion;
- no append, reparse, update, second dataset, second document, unreviewed query, or
  unrelated resource access;
- no modification or deletion of an existing dataset;
- no public retention of private paths, endpoints, credentials, dataset/document
  identifiers, disposable names, raw query text, raw chunks, or raw evidence spans;
- no commit or push unless separately requested.

## Repository And Evidence Baseline

The L3-PREP review verified a clean synchronized `develop` worktree at:

```text
40615d5d92ce395609a9ab54c61e2c1f3bac2147
```

`HEAD`, `develop`, and `origin/develop` were identical. This commit is a docs-only
descendant of the handoff baseline:

```text
03ea178f2274ca3ec90e7a6c61cf74c11f11988d
```

The only intervening change adds the repository `AGENTS.md`; it does not change the
marker-aware runtime, benchmark tools, profile templates, or owning plans. The latest
code-changing verification baseline remains:

```text
b42b96ba2e8e6d8138f01031101c95aef1a741a8
```

Because this document is intentionally not committed in L3-PREP, a later live run cannot
start merely from the preparation commit above. Before any live call, the user must
separately approve an exact clean execution commit containing this reviewed document.
That execution commit must be a docs-only descendant of `40615d5...` unless a new
L3-PREP review revalidates every changed source/profile file. The live preflight must
prove:

```text
HEAD == develop == origin/develop == <APPROVED_EXECUTION_COMMIT>
git status --porcelain is empty
```

Any other commit, detached state, untracked public file, or dirty worktree stops before
network access.

The authorized retained evidence was present, and all 11 handoff-pinned SHA-256 values
matched. The FinanceBench source identities used by this contract are:

| Artifact | SHA-256 |
| --- | --- |
| Selected source PDF | `09285ff7ee737d3302977104aa05cc53c9dfb0161f3461a89b583dc38b9f2ab6` |
| Reviewed formal Markdown | `8dfe30efaf18e038b271116bd210ef6f834f6b72004709aebe20f28fbfbf3cbe` |
| Reviewed normalized seven-query set | `ce4b56468f79258143bee3d15d23f0d056df61249b8b044e7b57fff2f0dfcd6d` |

The normalized private benchmark contains exactly one target document and exactly seven
reviewed queries: one fact query, three information-extraction queries, and three numeric
reasoning queries. All seven expect text evidence; three also expect table evidence. No
reviewed query depends on image evidence. The candidate-only L1 review mapped all 9 of 9
reviewed evidence spans and kept all 110 HTML tables balanced and atomic.

These facts do not authorize live work. A later run must reproduce the pinned hashes and
counts before any HTTP call.

## Resolved Build Input Contract

The selected input is the directly pinned formal Markdown:

```text
build.py --input <PINNED_FORMAL_MARKDOWN>
```

No private `doc_manifest.json` will be reconstructed for this L3 baseline. The retained
evidence does not contain the original document manifest, formal handoff manifest,
retrieval hints, ingest plan, or original KB dry-run report. Reconstructing a manifest
would invent provenance, sidecar membership, and readiness semantics that cannot be
verified from the retained files. Direct Markdown is an existing public CLI contract and
uses the exact content whose hash and candidate mapping were reviewed.

The live run must upload that one Markdown file only. It must not upload the source PDF,
local image files, a directory, a regenerated handoff, or any second document. Discovery
of more than one Markdown document, a hash mismatch, or an attempt to substitute a
manifest stops before creation.

The direct-input choice has reviewed limitations:

- manifest quality-gate and ingest-readiness states are unavailable, not implicitly
  `PASS`;
- two Markdown image references are classified as unsupported/gated by the standard
  Markdown build and are not uploaded;
- retrieval hints, ingest-plan fields, and table-parent preflight are unavailable;
- dense markers remain source-side candidate evidence and are not silently materialized
  into the RAGFlow parser profile.

These limitations are acceptable only for this proposed text/table FinanceBench slice
because the seven reviewed queries use text/table evidence, the 9 evidence spans mapped
exactly, and all 110 HTML tables passed structural review. They do not establish visual
ingestion quality or formal-handoff parity. Any later request to test images, sidecar
consumption, or marker-delimiter materialization requires a new input/profile contract.

## Resolved Profile Contract

The selected public profile is:

```text
skills/ragflow-kb-build/templates/default-en-768.json
```

Its pinned SHA-256 is:

```text
b43222e6120c0471f1b59265cdf42916c64ab0dbaa3c064f0af79fd2e440f6d8
```

This is a new reviewed L3 baseline choice. It is not claimed to reproduce the profile
used by the historical conversion/dry-run narrative. It was selected because it is the
current public English, model-neutral, no-enrichment template and therefore avoids
guessing a deployment-specific embedding model or adding an unreviewed parser field.

Offline lint and explanation both passed with zero errors and zero warnings. The
requested profile and create-payload contract is:

| Field | Reviewed request | Dataset-create treatment | Required live interpretation |
| --- | --- | --- | --- |
| `chunk_method` | `naive` | sent as `dataset.chunk_method` | current `parameter-audit` marks this target `not_observable`; perform a separate raw dataset-detail field review |
| language | `English` | sent as `dataset.language` | compare with the mapped dataset `language`/`lang` read-back path |
| `chunk_token_num` | `768` | sent as `dataset.parser_config.chunk_token_num` | compare with the mapped effective `parser_config` path |
| `auto_keywords` | `0` | sent as `dataset.parser_config.auto_keywords` | compare with the mapped effective `parser_config` path |
| `auto_questions` | `0` | sent as `dataset.parser_config.auto_questions` | compare with the mapped effective `parser_config` path |
| profile overlap | `96` | local audit only; not sent | never claim an effective overlap from this value |
| marker delimiter | not requested | not sent | no server marker-parity claim |
| embedding model | not configured | deployment-selected | record the observed model if exposed |
| image/table context defaults | not requested | not sent | record only as read-only server defaults if exposed |
| automatic metadata, overlap API mapping | not requested | blocked/unknown | no update attempt |
| PageIndex/table-to-HTML | not requested | native-parser-only | excluded from Markdown L3 |

The later run must retain one private dataset-detail read-back and run the offline
`parameter-audit` comparison against the approved dry-run report. Every observed value
must retain its exact JSON pointer and the digest of the response that supplied it.
Requested values and server-observed values must remain separate under these rules:

- `dataset.language` and the three requested `dataset.parser_config` fields use the
  audit's supported mapped paths. `observed_changed` or `observed_missing` blocks parser-
  profile acceptance and enters cleanup.
- `dataset.chunk_method` is not mapped by the current audit. Review the unmodified raw
  dataset-detail response separately and record `manual_match`, `manual_changed`, or
  `not_observable`. A changed value blocks acceptance; an absent field yields
  `partial_l3_chunk_method_unpinned` rather than an inferred match.
- the effective embedding model follows the same raw-field rule. If it is absent, the
  lifecycle may finish and clean up, but the result is `partial_l3_model_unpinned`.
- read-only image/table context values are recorded only when present. Overlap, marker
  delimiter, automatic metadata, PageIndex, and table-to-HTML remain local-only,
  unknown, or native-parser-only as classified above; absence is never converted into an
  effective server value.

Neither partial status can close the two-subset regression baseline or support guidance
or default changes.

Changing the profile path, profile bytes, embedding model declaration, delimiter,
enrichment values, chunk size, or language invalidates this contract and returns to
L3-PREP.

## Zero-Network Offline Dry-Run Evidence

The reviewed direct-input/profile pair was executed in an owner-only private planning
root with an empty environment except for the public source-runtime path. A Python audit
hook rejected any `socket.*` or `http.client.*` event. The command completed with:

```text
zero_network_guard=active network_events=0
```

The retained raw report basename is `kb-build-dry-run.json`; its SHA-256 is:

```text
6795574617e6a096762151a376d3146b0e68bcdbad8dc1ef9e5e4a02e0f9139b
```

Reviewed result:

| Item | Result |
| --- | --- |
| Dry-run status | `ok=true`, `dry_run=true` |
| Document count | exactly `1` |
| Markdown characters | `564900` |
| Estimated chunks | `841` |
| Estimation basis | `markdown_character_windows` |
| Selected profile | `default-en-768` |
| Parser errors / warnings / infos | `0 / 0 / 2` |
| Quality-gate state | `UNKNOWN` because direct input has no manifest |
| Ingest-readiness state | `not_available` |
| Table-parent preflight | `not_available` |
| RAGFlow calls | `0` |
| Live writes | `false` |
| Script-owned LLM calls | `0` |
| Collision probe | deliberately `not_probed` under L3-PREP |

The `841` estimate is not expected to equal the L1 marker-derived 492 emitted segments or
487 unique candidate hashes. Candidate chunks and server-observed chunks remain separate
identities. The difference is evidence to measure, not a reason to relabel either side.

The two lint information items are expected: the public profile is model-neutral, and
the internal language metadata is filtered from `parser_config` while materializing the
top-level dataset language. Neither item is a parser warning. The unavailable manifest
quality/readiness fields and excluded image references are the explicit direct-input
limitations above; they must be accepted in the separate L3 authorization and must not be
silently rewritten as passing evidence.

## Private Run Contract Required Before Live Approval

The future operator must create an owner-only private run root outside the repository and
write one immutable private `l3-run-contract.json`. Before approval it must contain every
exact pre-run value below plus a typed schema for the two identifiers that will later be
populated only in the separate supervisor state file:

| Public placeholder | Private run-contract value |
| --- | --- |
| `<PRIVATE_RUN_ROOT>` | owner-only repository-external artifact root |
| `<PRIVATE_LIVE_CONFIG>` | temporary mode-0600 config file with exact private path and SHA-256 |
| `<PRIVATE_RAGFLOW_ENDPOINT>` | approved endpoint retained only in the private config/contract |
| `<PRIVATE_RAGFLOW_CREDENTIAL>` | authorized credential-source binding; the secret value exists only in the temporary config and is not duplicated in the contract |
| `<DISPOSABLE_KB_NAME>` | exact materialized name from the naming policy below |
| `<CREATED_DATASET_ID>` | declared state-file slot, initially null; may be populated only from create and the immediate matching checkpoint, never from name-only recovery |
| `<UPLOADED_DOCUMENT_ID>` | declared state-file slot, initially null; may be populated only from the one successful upload response/checkpoint |
| `<PINNED_FORMAL_MARKDOWN>` | exact retained Markdown whose public hash is pinned above |

All pre-run placeholders must be resolved before the first HTTP call. The two generated
identifier slots cannot exist before mutation: any later command that depends on one may
run only after the supervisor has atomically bound that slot from its permitted response
and checkpoint source. The private contract pins command-array templates and typed slot
sources but remains byte-for-byte unchanged; the mutable values belong only in the state
file. The supervisor records the fully resolved argv digest before dispatch and must
never send a literal placeholder. No private replacement value may be copied back into
this public document.

The immutable contract must also record:

- approved execution commit and proof that the worktree is clean and synchronized;
- PDF, formal-Markdown, normalized seven-query set, normalized benchmark, candidate-map
  QA, and profile SHA-256 values;
- direct-Markdown input mode and exact one-document discovery result;
- exact disposable KB name and run identifier;
- exact private live-config source and an owner-only temporary config path;
- `document_count=1`, `query_count=7`, `top_k=3`, `metric_cutoff=3`;
- `http_timeout_seconds=60`, `parse_poll_deadline_seconds=900`,
  `poll_interval_seconds=5`, `forward_phase_deadline_seconds=3600`,
  `cleanup_reserve_seconds=900`, `outer_supervisor_deadline_seconds=4500`, and
  `signal_child_grace_seconds=15`;
- `supervisor_state_schema=financebench_l3_supervisor_state_v1`;
- one parse trigger, no reparse, and no automatic HTTP retry;
- two retrieval passes over the same seven reviewed queries and no additional query;
- the operation ceilings and cleanup policy from this document;
- the SHA-256 and review result for the private HTTP call-accounting hook used by every
  live Python process;
- the lifecycle supervisor's exact bytes and SHA-256, interpreter, complete pre-run argv
  arrays, typed runtime-slot command templates, owner-only state-file path and schema,
  cleanup preview/execute templates, pagination-checker argv arrays, and
  signal/child-process policy;
- an explicit statement that MinerU, DeepDoc, LLM/RAGAS, Stage 8C, L4, default changes,
  visual ingestion, updates, append, and unrelated resources are excluded;
- the exact artifact retention and public-redaction rules.

The supervisor contract must be materialized and hash-reviewed before approval; a prose
description alone is insufficient. The immutable run-contract hash must not change after
approval. Its separate state file must be written atomically before the create request
and after every identity/lifecycle transition. `INT` or `TERM` must stop
new forward-phase calls, forward the signal to the live child, wait only for the pinned
grace period, terminate a still-running child, and enter the same cleanup handler. The
outer deadline must enter cleanup at the 3600-second forward-phase boundary and reserve
the remaining 900 seconds for exact cleanup and absence checks; it must not orphan the
child or skip cleanup merely because the forward phase timed out.

The user approval must name or unambiguously accept this exact contract. Any changed
commit, hash, name, input, profile, query identity/order, top-k, deadline, HTTP timeout,
operation ceiling, supervisor/helper bytes, command array, signal behavior, state schema,
or cleanup rule invalidates approval.

The temporary live config must be mode `0600`, must never be printed, and must be deleted
on every exit path. Final evidence must prove that the config no longer exists. Reading an
unlisted private config or credential source requires separate authorization.

## Disposable Naming And Ownership Policy

The private run contract must materialize exactly one name from this public template:

```text
financebench-l3-marker-<UTC_TIMESTAMP>-<EIGHT_HEX>
```

The timestamp is UTC to the second, and the lowercase hexadecimal suffix is generated
once for the run. The exact materialized name remains private. It must be recorded with
the run ID before the collision check and must never be changed by server-side suffixing
or an automatic retry.

Before creation, one approved exact-name/suffix read-only scan must return:

```text
status=clear
matching_dataset_count=0
suffix_match_count=0
```

Any exact match, suffixed candidate, probe failure, ambiguous response, or inability to
prove the name is unused stops before mutation. A replacement name requires a refreshed
private run contract and renewed exact confirmation; the operator must not append a
number and continue.

The scan is a complete, bounded pagination procedure, not a single list response. It
uses `page_size=200`, reads pages in ascending order, and stops successfully only when
one of these completeness proofs is retained:

- trusted response metadata gives the total/page count, every declared page was read,
  and the declared total is at most 2000; or
- no usable total is exposed and a page with fewer than 200 dataset records terminates
  the scan.

At most ten pages may be read. A full tenth page without trusted end-of-list metadata,
metadata declaring more than ten pages or more than 2000 datasets, a repeated/missing
page, duplicate dataset identifier across pages, inconsistent totals, a collected unique-
identifier count that disagrees with the declared total, or a response shape that cannot
be counted is `pagination_incomplete` and stops. The scan must examine exact and suffix
matches over the complete collected set; a server-side exact-name filter alone cannot
prove suffix absence. Other returned names/identifiers remain private and may not be used
for any dataset-detail request.

Ownership is proven only by the conjunction of the complete pre-create clear result, an
exact identifier successfully parsed from the create response, its immediate persistence
in the matching build checkpoint, and matching exact name/identifier values in every
later available manifest. Name similarity or recovery-list output alone never authorizes
cleanup.

## Maximum Live Operation Surface

After separate approval, the run may perform only the following RAGFlow operations:

| Operation class | Maximum | Purpose |
| --- | ---: | --- |
| Compatibility GET | `1` | prove the reviewed list-datasets surface is usable |
| Pre-create name-scan GET | at most `10` | complete exact/suffix collision gate, 200 records per page |
| Ambiguous-create recovery GET | at most `10` | bounded complete scan for manual-cleanup facts only |
| Dataset read-back GET | `1` | requested/effective parameter evidence |
| Parse-status GET | at most `180` | 900-second poll-loop deadline at a 5-second interval |
| Post-parse refresh GET | `1` | exact document count, state, and chunk total |
| Post-cleanup dataset-ID GET | `1` | prove the created identifier is absent |
| Post-cleanup name-scan GET | at most `10` | complete exact/suffix absence scan, 200 records per page |
| Retrieval POST | at most `14` | seven-call discovery pass plus a conditional seven-call final pass |
| Dataset create POST | at most `1` | create the one disposable dataset |
| Markdown upload | at most `1` | upload the one pinned formal Markdown file |
| Parse POST | at most `1` | trigger parsing once for the one uploaded document |
| Update / PUT | `0` | forbidden |
| Reparse | `0` | forbidden |
| Delete / cleanup DELETE | at most `1` | delete only the exact created dataset |

The maximum GET count is therefore `214`, including all pagination and parse polling.
The ten recovery GETs are allowed only after an ambiguous create attempt and are
forbidden on the normal success path. A recovery match cannot authorize automatic
deletion. The actual ledger may be smaller when parsing finishes early or a stop
condition prevents a later step. Every attempted call, including failed calls, must be
counted by method and logical category. A
retry not listed above, a second upload, a second parse trigger, an eighth distinct query,
a third retrieval pass, an update, or any detail/document/retrieval/mutation access to
another dataset is an unexpected operation and triggers the stop/cleanup path. The
minimum list metadata returned by the approved complete name scans is the only exception.

The ceilings are not a substitute for an actual ledger. The current build manifest does
not expose the number of internal parse-poll GETs, so the future run must install one
reviewed private Python audit hook in every live CLI process. The hook records each
`urllib.Request` event before dispatch and writes only the HTTP method plus an approved
logical category to an owner-only append ledger. It must not retain the host, URL query,
headers, body, credential, query text, dataset/document identifier, or raw response. The
hook/helper bytes and SHA-256 belong in `l3-run-contract.json`; commands must fail before
creation if the hook is absent or cannot append safely. Validation's built-in seven-call
safety counters and command artifacts are cross-checks, not replacements. Any uncounted
or unclassifiable request is `unexpected_operation`.

Before either retrieval pass, the supervisor must verify the normalized query artifact
bytes against the pinned SHA-256 above and assert all of the following without printing
query text or identifiers publicly:

- the artifact contains exactly seven query objects in the pinned order, with seven
  unique nonempty query identifiers;
- all seven `expected_documents` arrays are present and empty, as reviewed in L3-PREP;
- the same immutable artifact supplies both passes; no query is copied, reordered,
  rewritten, filtered, or generated at runtime.

The empty `expected_documents` values are deliberate: the retained source qrels identify
the source PDF, while the live object will be the reviewed Markdown upload. A future
nonempty value is provenance drift and stops before retrieval. The manually reviewed
observed qrels, not an edit to the normalized query artifact, supply the live Markdown
identity for the final pass.

The two retrieval passes are intentionally bounded:

1. **Observed-discovery pass:** run the exact seven normalized queries at `top_k=3` and
   `--level regression`, privately retain at most three raw chunks per query, create the
   first server-observed retrieval snapshot, and map the nine reviewed evidence spans.
   This pass is for discovery/mapping; it does not treat candidate document/chunk qrels
   as observed metrics.
2. **Final-validation pass:** after manual approval of private observed qrels, run the
   same seven queries once more with `--level benchmark`, `top_k=3`, and
   `metric_cutoff=3`. No query text, ordering, filter, threshold, route, dataset list, or
   top-k may change. Compare ordered results and stable hash sets for repeatability.

If the first pass cannot map every reviewed span exactly, the second pass is forbidden;
the run proceeds directly to cleanup. Both validation commands must use the exact
post-build KB manifest and its dataset identifier; dataset-name resolution, and its
implicit extra listing GET, is forbidden.

## Exact Create, Upload, And Parse Gate

Immediately before mutation, the operator must compare the reviewed private command
array with `l3-run-contract.json` and record a final typed confirmation covering the
execution commit, disposable name, one-document hash, profile hash, query-set hash,
HTTP/poll/supervisor deadlines, query count, and mandatory cleanup. The public top-level
build command has no live-confirmation flag, so this external reviewed confirmation is
mandatory and must be retained privately.

The live build must use:

- direct `--input <PINNED_FORMAL_MARKDOWN>`;
- `--profile skills/ragflow-kb-build/templates/default-en-768.json`;
- the exact private disposable name;
- `--parse-timeout 900 --poll-interval 5 --batch-size 1`, where 900 seconds is the
  parse-status poll-loop deadline rather than an HTTP or whole-process timeout;
- an output manifest and a checkpoint under the private run root;
- no `--doc-manifest`, `--allow-blocked`, `--no-parse`, `--no-wait`,
  `--force-reupload-confirmed`, visual-ingestion, append, or update option.

The private config must set the per-request HTTP timeout to 60 seconds, and the
supervisor must enforce the 3600-second forward-phase boundary plus the 4500-second outer
deadline defined above. A timeout at one layer does not extend another layer and never
authorizes a retry.

The checkpoint is required so the dataset identifier is persisted immediately after
creation, before upload/parse can fail. Immediately before the create call, the run state
becomes `create_attempted=true` and `cleanup_required=true`, with
`automatic_delete_authorized=false`. As soon as creation returns an exact identifier and
the same identifier/name are atomically persisted in the checkpoint,
`automatic_delete_authorized=true`. It never returns to false until deletion and both
absence proofs succeed. If the create response or checkpoint identity is missing or
ambiguous, the handler may run the bounded recovery scan described below, but the scan
cannot set `automatic_delete_authorized=true` and must not assume that no dataset was
created.

The build is structurally acceptable only when:

- the effective dataset name equals the confirmed name exactly;
- exactly one dataset identifier and one document identifier are returned;
- exactly one document is observed;
- parse reaches one terminal successful state within the 900-second poll-loop deadline;
- observed chunk count is greater than zero;
- no second document, server-side suffix, failed document, or unexpected mutation is
  present;
- every observable requested parser field matches, while `chunk_method` and embedding-
  model visibility follow the explicit partial-status rules above.

No parse retry or reparse is allowed. Timeout, failure, zero chunks, unexpected document
count, or requested/effective mismatch records the failure and enters cleanup.

## Observed Evidence And Validation Contract

After successful parse, retain two distinct evidence layers:

1. a read-only refresh report recording the dataset-wide observed document state and
   total chunk count;
2. retrieval-observed chunk snapshots derived from the private raw results of each
   seven-query pass, with full content retained only in the private run root.

Do not claim that retrieval-observed snapshots enumerate every dataset chunk. Report the
dataset-wide chunk total and the retrieval-observed unique stable-hash set separately.
Candidate L1 hashes and L3 server-observed hashes must also remain separate.

Use the reviewed formal-Markdown candidate-map QA as the exact-span source. The observed
mapping gate requires:

- exactly seven QA items and exactly nine evidence spans;
- 9 of 9 spans mapped;
- every span mapped to exactly one server-observed chunk;
- every target is a stable `sha256:` hash present in the observed snapshot;
- all mapped chunks belong to the one created document;
- manual review accepts the complete evidence text and chunk boundary privately;
- no raw evidence or chunk content enters public artifacts.

Only after this gate may a private observed-qrels file be created. Candidate qrels remain
unchanged. The retained source document qrels identify the original PDF, while the live
object is the reviewed Markdown upload; current matching does not infer equivalence from
those different filename suffixes. The private observed qrels must therefore bind each
query to the exact server-observed Markdown document name or identifier after manual
identity review, while preserving the source-PDF identity separately as provenance. They
must also contain only the exact stable hashes approved by the nine-span observed map.
No public/source qrel is overwritten.

The final validation pass must use the private observed qrels plus the reviewed observed
chunk snapshot and report:

- hit rate, MRR, precision at 3, recall at 3, nDCG at 3, MAP at 3, and empty-result rate;
- strict observed chunk recall, expected-chunk hit rate, and expected evidence rank;
- expected-term and table-term recall;
- wrong-document review;
- retrieval-evidence citation-support proxy, explicitly not an answer-level audit;
- per-query ordered result hashes and two-pass repeatability;
- exact RAGFlow call and mutation counts.

Metric values are evidence, not an automatic pass threshold. A structurally valid run
with weak retrieval is retained as `completed_with_quality_findings` and classified as a
quality regression; it does not authorize guidance or default changes. Tag-pollution is
not meaningful without reviewed tag qrels. Cross-document pollution safety is not
meaningful for a one-document dataset, even if wrong-document rate is zero. These fields
must be reported as unavailable or one-document-limited rather than inferred as broadly
safe.

The L3 evidence is acceptable for later maintainer review only when the operational
lifecycle, exact evidence mapping, call ledger, private/public boundary, cleanup, and
absence proof all pass. If `chunk_method` or the effective embedding model is
unavailable, acceptance is limited by the corresponding partial status described above.

## Stop Conditions And Failure Taxonomy

Before creation, stop with `approval_required` or a precise blocking class when any of
these occurs:

- repository/commit/worktree mismatch;
- missing artifact or hash mismatch;
- input/profile substitution or ambiguous provenance;
- document count other than one, query count other than seven, query-set hash/order
  drift, or any nonempty normalized-query `expected_documents` value;
- blocked dry-run, new parser warning, or an unreviewed direct-input limitation;
- unavailable/incompatible service or failed compatibility check;
- name collision, suffix candidate, incomplete pagination, or ownership ambiguity;
- missing/hash-mismatched supervisor, helper, state schema, command array, or explicit
  live approval, or any changed private run contract;
- temporary config permissions, source authorization, or redaction boundary failure.

After creation, every failure enters the unconditional cleanup handler. Failure classes
include:

- `build_failure` for upload or manifest/checkpoint failure;
- `parse_failure`, `parse_timeout`, or `zero_chunks`;
- `observed_state_mismatch` for count, name, document, or parser read-back drift;
- `evidence_mapping_failure` for anything other than exact 9-of-9 mapping;
- `repeatability_failure` for unreviewed two-pass result/hash drift;
- `quality_regression` for retained but weak retrieval metrics;
- `unexpected_operation` for an extra call, retry, resource, or mutation;
- `redaction_failure` for sensitive leakage;
- `cleanup_risk` for deletion failure, uncertain identity, or missing absence proof.

No failure permits a second dataset, re-upload, reparse, profile change, query change, or
operation-ceiling increase. A new attempt requires a new private run contract and
separate approval.

## Unconditional Cleanup And Absence Proof

Cleanup is a state machine, not a best-effort final note:

```text
before creation -> cleanup_required=false
create call issued -> create_attempted=true, cleanup_required=true, automatic_delete_authorized=false
exact create identifier atomically persisted in matching checkpoint -> automatic_delete_authorized=true
cleanup preview accepted -> exact delete may run once
delete success + complete ID absence + complete paginated name absence -> cleanup_required=false
anything else -> cleanup_risk
```

The cleanup handler must run after success, failure, interruption, or exception whenever
`create_attempted=true`. The checkpoint is the immediate durable record written from a
successfully parsed create response; the raw response need not be retained separately.
If an exact returned identifier was not persisted in that matching checkpoint, the
handler may run the one bounded, complete recovery name scan for the already confirmed
exact name. The pre-create collision result must have been clear. A
recovery match is retained only as a possible-resource fact for manual cleanup; it does
not prove ownership and cannot supply an identifier to an automatic DELETE. Zero matches
does not prove that an ambiguous create was not committed, and one or more matches do not
prove ownership. Every such outcome, a suffix-only match, a missing identifier, or a
failed/incomplete scan becomes `cleanup_risk`, preserves sanitized manual-cleanup facts,
and stops without automatic deletion. The handler must not create a new name or broaden
the search.

The live build must therefore run inside the exact hash-pinned lifecycle supervisor from
the private run contract. An informal shell wrapper or newly typed `try/finally` is not a
substitute. The supervisor must run the pinned build argv as a non-detached child, write
the owner-only state file atomically before create, intercept `INT`/`TERM` and the
forward/outer deadlines as specified above, and invoke only the pinned cleanup preview,
cleanup execute, identifier check, and paginated name-scan argv arrays. The cleanup
execute array must call the reviewed public cleanup CLI with `--execute`, the exact
manifest when available or explicit `--dataset-id`/`--kb-name` values bound from the
checkpoint, and matching `--confirm-dataset-id` and `--confirm-kb-name`; the public CLI
does not accept a checkpoint argument. Ad hoc shell interpolation or a fuzzy/name-only
delete command is forbidden. If the supervisor or host disappears before cleanup can
run, L3 is immediately `cleanup_risk`; the checkpoint and bounded recovery rule must be
resolved under separate operator authorization before any new attempt.

Once an exact returned identifier is durably available in the checkpoint, the handler
first produces a no-network preview from the checkpoint and, when it exists, the private
manifest. Delete is allowed only when all applicable exact values agree:

- the confirmed disposable name;
- the checkpoint dataset identifier;
- the checkpoint dataset name;
- the manifest dataset identifier/name when a manifest exists;
- `--confirm-dataset-id` and `--confirm-kb-name` values supplied to cleanup.

Name-scan recovery evidence is never part of this agreement set. If identity is missing
or contradictory after the bounded recovery rule, the handler must not guess or delete
by fuzzy name. It records `cleanup_risk`, preserves sanitized
manual-cleanup facts, deletes the temporary live config, and stops for explicit operator
action. It must never inspect or delete an unrelated resource to compensate.

After one successful exact DELETE, two approved read-only checks are required:

1. the created dataset identifier is absent/not found;
2. a complete ten-page-bounded scan proves exact-name and suffixed-name counts are both
   zero using the same pagination completeness rules as the pre-create scan.

The delete response alone is not absence proof. A clear name result without an exact
create/checkpoint identity is also insufficient. Failure or ambiguity in either
post-cleanup check blocks L3 acceptance even when retrieval metrics are strong.

The temporary live config is then deleted and its nonexistence is proven separately.
Cleanup reports and absence reports remain private until sanitized.

## Artifact Retention And Sensitive-Information Boundary

The private run root retains content-bearing and identifying evidence until the
FinanceBench L3 result and later cross-subset review are resolved. Expected private
artifact classes include:

- exact run contract, repository proof, hash inventory, profile lint/explanation, and
  offline dry-run;
- temporary live config metadata without printing its contents, followed by deletion
  proof;
- compatibility, collision, create/checkpoint/manifest, dataset read-back,
  parameter-audit, refresh, parse, and health evidence;
- both raw seven-query validation passes, retrieval-observed snapshots, exact evidence
  maps, manually approved observed qrels, and repeatability comparison;
- full call/mutation ledger;
- cleanup preview, delete response, identifier/name absence proof, and config absence
  proof;
- separate sensitive scans for tool-produced reports and agent-authored prose.

Nothing under the private run root is committed. Public-safe retention may contain only:

- public commit/profile/source hashes;
- aggregate document/query/chunk/evidence counts;
- aggregate metrics and sanitized failure classes;
- operation counts and explicit mutation/non-mutation categories;
- cleanup and post-cleanup proof status;
- public-safe artifact basenames.

Public retention must not contain private paths, endpoint/host values, credentials or
fragments, exact disposable names, dataset/document identifiers, query text, raw chunks,
raw evidence spans, config locations, or source filenames that act as private execution
identifiers. The tool-report and agent-prose scans are reviewed independently; one clean
scan does not substitute for the other. Any unresolved hit is `redaction_failure` and
blocks public retention and L3 acceptance.

The temporary live config is never retained. Other private evidence is not automatically
deleted at run close; it remains owner-controlled until the owning review explicitly
accepts or rejects the L3 result.

## L3 Acceptance And Owning-Plan Effects

A future run may be classified as accepted L3 evidence only when all of the following are
true:

- exact clean execution baseline and all pinned hashes pass;
- one reviewed document and seven reviewed queries are preserved;
- the pinned query artifact/order is unchanged and all seven normalized
  `expected_documents` arrays remain empty;
- the approved profile/input contract is unchanged;
- dry-run and compatibility/complete paginated collision gates pass;
- exactly one dataset and one document are created/uploaded/parsed;
- observed state is terminal with a positive chunk count;
- requested/effective fields are reviewed without overstating unavailable values;
- 9 of 9 evidence spans map exactly to observed chunks;
- both bounded seven-query passes and metric reports are retained;
- actual call counts stay within the contract;
- no excluded operation occurs;
- exact cleanup, identifier absence, complete paginated name absence, and config absence
  all pass;
- separate sensitive scans pass.

Even then, the run does not itself close the two open `docs/38` rows. A later maintainer
review must compare the accepted FinanceBench evidence with the pinned Open RAG L2
checkpoint, assess one-document limitations, and decide whether the true two-subset
baseline and metric-review criteria are satisfied. No L4 or default-promotion work may
begin in the same step.

## Instruction Self-Review

| Review dimension | Result |
| --- | --- |
| Preparation authority | L3-PREP only; every live/read-only HTTP action remains separately gated |
| Input provenance | direct pinned formal Markdown; no reconstructed manifest |
| Profile provenance | exact public path/hash; explicitly a new reviewed baseline |
| Query identity | exact file hash/order; seven unique entries; seven empty `expected_documents` arrays |
| Naming collision | complete bounded pagination; exact/suffix collision or incomplete listing stops |
| Creation scope | one dataset, one Markdown upload, one parse trigger |
| Query scope | same exact seven reviewed queries, two bounded passes, no additions |
| Timeout layers | 60-second HTTP, 900-second poll loop, 3600-second forward phase, 4500-second outer deadline |
| Stop behavior | no HTTP retry, reparse, substitute profile, or second dataset |
| Cleanup | handler becomes mandatory when the create call is issued, including ambiguous responses |
| Delete safety | only a returned ID persisted in the checkpoint authorizes exact deletion; recovery scans are manual facts only |
| Absence proof | identifier absence plus complete paginated exact/suffixed name absence required |
| Retention | raw/content-bearing evidence private; sanitized aggregates only public |
| Sensitive boundary | tool and prose scans separated; unresolved hit blocks acceptance |
| Excluded tracks | MinerU, DeepDoc, LLM/RAGAS, Stage 8C, L4, defaults, unrelated resources |

## Independent Instruction Review

An independent instruction review returned `with fixes`. The technically applicable
findings were resolved as follows:

| Finding | Resolution |
| --- | --- |
| Name-only recovery could authorize the wrong DELETE | recovery is now manual-cleanup evidence only; automatic deletion requires the returned ID in the immediate checkpoint |
| Collision/absence checks could inspect only one page | all name checks now require a complete, ten-page-bounded, 200-record pagination proof |
| Supervisor behavior was described but not pinned | the private contract must pin supervisor/helper bytes, hashes, state schema, argv arrays, signal behavior, and cleanup commands before approval |
| One `900s` value conflated timeout layers | HTTP, parse-poll, forward-phase, cleanup-reserve, and outer deadlines are now separate |
| Requested/effective fields lacked field-level observability rules | mapped audit fields, raw manual review, and `not_observable` partial statuses are now distinct |
| Query-document identity could drift | the exact seven-query artifact/order is pinned and all seven empty `expected_documents` arrays are asserted before live retrieval |

No finding was used to expand L3-PREP authority or add a live operation.

## Mandatory Stop

Current status:

```text
approval_required
```

Do not run a compatibility probe, collision check, create, upload, parse, retrieval,
read-back, delete, or post-cleanup check from this L3-PREP session. Request separate,
explicit L3 live-mutation authorization that pins the private run contract and exact
operation ceilings above.
