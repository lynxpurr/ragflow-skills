# Standard Benchmark Dataset Integration Plan

Status: active standard-dataset integration plan; Open RAG Benchmark seed validated
through Stage 5, with Stage 6/7 public tooling and synthetic rehearsal complete
Date: 2026-07-09
Last calibrated: 2026-07-11

Execution follow-up: `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`
owns the Open RAG strict-evidence, FinanceBench offline slice, initial regression
portfolio, transition-validation, and later Hermes replay work. This document remains the
dataset, licensing, normalization, and benchmark-maturity design source.

## Objective

The current RAGFlow skill suite has strong offline checks, dry-run previews, formal
handoff sidecars, benchmark import/preflight commands, disposable optimization gates,
and public-safe retention reports. The remaining quality gap is not primarily a missing
runtime feature. It is the lack of a reusable benchmark corpus that can repeatedly test
whether document conversion, KB construction, profile choices, and retrieval settings
actually improve answer evidence.

This plan defines a standard-dataset program for `ragflow-doc-to-md`,
`ragflow-kb-build`, and `ragflow-query`. It describes which public datasets to
introduce, how to normalize them into this repository's benchmark artifact model, how
to connect them to the current skills, and which metrics should be tracked over time.

The plan does not add live RAGFlow mutation by default, does not vendor large external
datasets into this repository, does not add script-owned LLM/RAGAS evaluation, and does
not change the public CLI/archive release baseline. External PDFs and raw dataset
artifacts should remain user-owned or private-run-root artifacts unless a separate
license and release decision is made.

## Problem Statement

Recent consumption-gap work showed that the public skills can now explain what gets
materialized into RAGFlow and what remains advisory. It also showed that enrichment
features such as `auto_keywords` and `auto_questions` cannot be judged from prose
summaries alone. They need stable queries, relevance judgments, and retained
per-query results.

Without a standard benchmark suite:

- profile decisions depend on one-off field-trial reports;
- document-level qrels can make weak benchmarks look decisive;
- table and image retrieval regressions are easy to miss;
- improvements to chunk markers, delimiter profiles, image ingestion, or enrichment
  settings cannot be compared across releases;
- live disposable tests are hard to approve because the expected evidence and cleanup
  record are not predetermined.

The next quality improvement is therefore to make benchmark data acquisition,
normalization, validation, and trend tracking first-class maintenance work.

## Current Execution Progress

As of 2026-07-09, the first Open RAG Benchmark seed has been exercised through
Stage 5 disposable live comparison.

Completed evidence:

- Stage 0 planning baseline was accepted for standard benchmark integration.
- Stage 1 created a one-PDF Open RAG Benchmark seed with 10 judged queries and
  document-level qrels.
- Stage 2 benchmark import and preflight passed with expected weak-benchmark
  warnings. The seed remains `exploratory` because it has one target document,
  document-level qrels, and no chunk-level ground truth.
- Stage 3 validated the PDF-to-formal-handoff-to-dry-run path using the approved
  MinerU formal handoff route. `builtin` PDF handling was confirmed as a
  capability boundary, not a conversion defect. `pandoc` and new local PDF
  extraction fallbacks remain excluded.
- For this seed, the MinerU hybrid high-quality path is the preferred formal
  handoff path. The table-sizing issue observed in the standard pipeline path
  was resolved in the hybrid path: the table preflight became ready, all table
  entries fit the 768-token profile, and no table-parent chunk oversize warning
  remained.
- Stage 4 readiness completed offline with a delimiter-aware profile base,
  bounded `auto_keywords` / `auto_questions` candidates, profile lint,
  optimization planning, cleanup planning, and readiness reporting.
- Stage 5 completed after explicit live approval. Four unique effective
  disposable KBs were created, parsed, queried, and cleaned up; public-safe
  retention artifacts were generated; cleanup verification reported zero
  residual disposable KBs.
- On this exploratory seed, `auto_questions=1` improved average top similarity
  by about 6%, while `auto_keywords=1` showed no measured gain. All candidates
  hit all judged queries, so the benchmark remains too weak to evaluate
  precision or support promotion.

Current limitations and gates:

- The benchmark supports workflow validation and exploratory comparison only.
  It must not be used for profile promotion or global default strategy changes.
- The Stage 5 evidence closes the `docs/34` disposable enrichment checklist
  item, but only at an exploratory decision tier.
- Duplicate effective profiles were collapsed before live execution. The
  delimiter-aware base profile represented the `auto_keywords=0,
  auto_questions=0` baseline, so only four unique effective disposable
  candidates were created.
- RAGFlow DeepDoc native PDF handling remains a separate live-approved
  PDF-native/fallback baseline path, not part of the first enrichment comparison.
- The normalized artifact contract now includes validated source attribution and
  selection reports, and deterministic sampling preserves their provenance.
- An explicit-input offline portfolio tool and neutral two-subset synthetic rehearsal
  now cover table, numeric, mixed-modality, expected-term, declared expected-chunk, and
  negative cases without calling RAGFlow or an LLM.
- This synthetic rehearsal proves the Stage 6/7 tooling path only. It does not replace
  an operator-reviewed Open RAG source fill, a real FinanceBench slice, observed strict
  chunk recall, or a retrieval-quality regression baseline.

### Session Status Matrix

| Work item | Status | Evidence / decision |
| --- | --- | --- |
| Stage 0 planning baseline | Complete | Standard benchmark integration plan accepted and committed. |
| Stage 1 Open RAG Benchmark seed | Complete | One-PDF seed with 10 judged queries and document-level qrels established. |
| Stage 2 import/preflight | Complete | Benchmark preflight passed with expected exploratory-strength warnings. |
| Stage 3 PDF handoff/dry-run | Complete | MinerU hybrid formal handoff passed inspect-handoff and dry-run; table sizing resolved for this seed. |
| Stage 4 readiness | Complete | Delimiter-aware profile base, bounded enrichment candidates, lint, optimization plan, cleanup plan, and readiness completed. |
| Stage 5 disposable enrichment comparison | Complete | Four unique effective disposable KBs were created, queried, and cleaned up after explicit approval. Public-safe retention artifacts were generated. |
| `docs/34` disposable enrichment checklist | Complete | Stage 5 evidence closed the remaining live-gated checklist item. |
| DeepDoc native PDF baseline | Pending / separately gated | Optional PDF-native/fallback comparison requiring separate live approval. |
| KB parameter materialization | Contract-audited / conditionally blocked | `docs/36-ragflow-kb-parameter-materialization-plan.md` Stage 8B is complete for RAGFlow `v0.25.5`; zero candidates are Stage 8C eligible. Benchmark datasets remain prerequisite evaluation evidence if a future pinned contract exposes a writable candidate. |
| Stronger Open RAG Benchmark subset | Pending | Needs more documents, more queries, expected terms, or expected chunks before promotion decisions. |
| FinanceBench table/numeric slice | Pending | Recommended next dataset expansion for table-heavy and numeric evidence retrieval. |
| QASPER scientific QA slice | Deferred | Useful after Open RAG Benchmark and FinanceBench adapters are stable. |
| TREC-COVID IR reference slice | Deferred | Later retrieval-metric and qrels-format calibration work. |
| Regression portfolio | Pending | Current seed can become a smoke/exploratory baseline; broader portfolio still needs pinned subsets and trend reporting. |
| Attribution/selection artifact contract | Complete | Import and deterministic sampling now preserve normalized source and selection provenance with schema/release governance. |
| Synthetic Stage 6/7 rehearsal | Complete | Neutral two-subset portfolio produced 6 queries, 12 qrels, 6 QA items, table/numeric and negative coverage, and `ready_with_review` without live calls. |
| Private Stage 6/7 evidence fill | Blocked on operator input | `private_source_fill_required`; no reviewed FinanceBench/Open RAG source root was supplied in this round. |

### Follow-Up Work Plan

Recommended next sequence:

1. Execute the artifact-contract and explicit-input portfolio work in
   `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`.
2. Strengthen the current Open RAG Benchmark seed with reviewed expected terms and,
   only when a reviewed snapshot exists, expected chunk hashes for the existing
   stable queries.
3. Add one bounded FinanceBench slice for table-heavy, numeric, and evidence-page
   retrieval failure modes, then form the initial two-subset regression portfolio.
4. Keep `docs/36-ragflow-kb-parameter-materialization-plan.md` as a conditional gate.
   Its pinned RAGFlow `v0.25.5` Stage 8B audit is complete with zero Stage 8C-eligible
   candidates; reopen contract discovery only for a new deployed version or an explicit
   upstream contract change.
5. Decide separately whether a DeepDoc native PDF baseline is needed for a PDF-native
   parser comparison. This remains live-approved and must not be bundled into ordinary
   offline benchmark expansion.

## Candidate Dataset Portfolio

### Primary Seed: Open RAG Benchmark

Use this as the first standard seed because it is PDF-first and already contains PDF
URLs, queries, qrels, and answers.

Public source:

- Hugging Face dataset: https://huggingface.co/datasets/vectara/open_ragbench
- GitHub project: https://github.com/vectara/open-rag-bench

Observed public structure:

- `pdf_urls.json`
- `corpus/`
- `queries.json`
- `qrels.json`
- `answers.json`

Fit for this project:

- It starts from arXiv PDFs, which matches the `ragflow-doc-to-md` to
  `ragflow-kb-build` path.
- It includes text, table, image, and mixed source categories.
- Its qrels link query IDs to document and section evidence, which can be converted to
  document-level qrels immediately and expected-section or expected-chunk qrels after
  chunk snapshot mapping.
- It is the best candidate for the first disposable enrichment comparison because a
  small sample can be selected without manually authoring all queries.

Limitations:

- Query and answer generation used an LLM during dataset creation; this is acceptable
  for an external benchmark source but should be recorded in benchmark metadata.
- The Hugging Face license is `cc-by-nc-4.0`, so use should remain research/testing
  unless a later legal review allows broader use.
- Section IDs are not the same as RAGFlow chunk IDs. Strong qrels require a mapping
  step from source sections to generated chunk hashes.

Recommended first slice:

- Select one positive PDF and 6 to 10 associated queries.
- Include at least one text-only query, one table query if available, one image or
  mixed-modality query if available, and one abstractive query.
- Generate a normalized benchmark directory with `manifest.json`, `queries.json`,
  `qrels.json`, and `qa.json`.
- Run `benchmark preflight`; allow a weak-benchmark warning only if the first slice is
  document-level.

### Secondary Domain Stress Test: FinanceBench

Use this after Open RAG Benchmark to stress table-heavy, numeric, and evidence-page
retrieval.

Public source:

- GitHub project: https://github.com/patronus-ai/financebench
- Hugging Face dataset: https://huggingface.co/datasets/PatronusAI/financebench

Observed public structure:

- open-source sample of 150 annotated examples;
- financial PDFs under `/pdfs/` in the GitHub project;
- question, answer, document metadata, evidence text, document name, source document
  link, and evidence page fields in the public sample.

Fit for this project:

- It exercises annual reports, quarterly reports, tables, page references, numeric
  calculations, and evidence grounding.
- It is useful for validating table extraction, table-parent chunk behavior, page-level
  evidence retention, and wrong-document/pollution checks.
- Its evidence text can be used to build expected-term qrels first, then expected-chunk
  qrels after chunk snapshots exist.

Limitations:

- The PDFs can be large and table-heavy, so this should not be the first live disposable
  sample.
- It is QA/evidence oriented rather than a ready BEIR-style qrels package.
- The Hugging Face license is `cc-by-nc-4.0`; do not vendor the dataset into public
  release artifacts.

Recommended first slice:

- Select one small or medium filing with several public questions.
- Build qrels from `doc_name`, `evidence_page_num`, and `evidence_text`.
- Track table/evidence metrics separately from general text retrieval metrics.

### Scientific QA Expansion: QASPER

Use this to expand scientific-paper coverage after the Open RAG Benchmark path works.

Public source:

- Hugging Face dataset: https://huggingface.co/datasets/allenai/qasper

Observed public structure:

- questions over NLP research papers;
- answers and supporting evidence;
- dataset license recorded as `CC BY 4.0` in the dataset loader;
- papers can be mapped back to arXiv PDFs through paper identifiers in downstream
  workflows, but the dataset is not as PDF-first as Open RAG Benchmark.

Fit for this project:

- It tests long scholarly documents, section evidence, abstractive answers, extractive
  answers, yes/no answers, and unanswerable cases.
- It can support negative and unanswerable retrieval tests that are missing from many
  synthetic benchmark seeds.

Limitations:

- It requires additional PDF acquisition and mapping work.
- It is less directly aligned with image/table ingestion than Open RAG Benchmark.
- The first integration should use only a small curated subset until PDF mapping is
  deterministic.

Recommended first slice:

- Select 3 to 5 papers with easy PDF retrieval and clear evidence spans.
- Convert supporting evidence into expected terms and expected chunks.
- Include at least one unanswerable query to measure over-retrieval and hallucination
  pressure in downstream query workflows.

### IR Reference Set: TREC-COVID

Use this as a later retrieval-method reference, not as the first PDF ingestion test.

Public source:

- NIST data page: https://ir.nist.gov/trec-covid/data.html

Observed public structure:

- TREC-COVID Complete has a Round 5 CORD-19 document set, 50 topics, and cumulative
  relevance judgments.
- Qrels use topic ID, iteration, document ID, and relevance judgment, where the
  judgment scale distinguishes not relevant, partially relevant, and fully relevant.

Fit for this project:

- It provides classic IR qrels and mature relevance judgment semantics.
- It is useful for validating qrels import, benchmark trend, nDCG, MRR, precision,
  recall, and wrong-document behavior on a large corpus.

Limitations:

- It is not a convenient single-PDF ingestion workflow.
- It is better suited to corpus-level retrieval experiments than to the immediate
  `ragflow-doc-to-md` -> `ragflow-kb-build` disposable KB loop.

Recommended first slice:

- Defer until the Open RAG Benchmark and FinanceBench adapters exist.
- Use a tiny topic/document subset only for qrels-format regression and metric
  validation before considering corpus-level experiments.

## Standard Artifact Contract

Every imported benchmark subset should produce a normalized benchmark directory:

```text
benchmark/
  manifest.json
  queries.json
  qrels.json
  qa.json
  source_attribution.json
  selection_report.json
  preflight.json
  preflight.md
```

Required public-safe semantics:

- `manifest.json` uses `ragflow_benchmark_manifest_v1` and references local artifact
  names, not private absolute paths.
- `queries.json` contains stable query IDs, query text, optional `min_chunks`, optional
  `top_k`, and metadata such as dataset source, modality, query type, and source
  document key.
- `qrels.json` uses `ragflow_benchmark_qrels_v1` and starts with document-level or
  source-section qrels; strong subsets should add `expected_chunks`, `chunk_hash`,
  expected terms, or content targets after a chunk snapshot exists.
- `qa.json` stores answers, evidence snippets, evidence pages, source section IDs, or
  unanswerable labels when available.
- `source_attribution.json` records dataset name, upstream URLs, license, selected
  source IDs, and whether queries or answers were human-authored, LLM-generated, or
  mixed.
- `selection_report.json` records why the subset was chosen and whether it is intended
  for smoke, exploratory comparison, promotion gating, or regression tracking.
- `preflight.json` records benchmark-strength warnings before any live mutation.

Raw downloaded PDFs, source dataset dumps, RAGFlow endpoints, dataset IDs, document IDs,
KB names, and raw retrieved chunks must stay outside public docs and release artifacts.

## Dataset Normalization Mapping

### Open RAG Benchmark Mapping

Input:

- `pdf_urls.json`
- `queries.json`
- `qrels.json`
- `answers.json`
- optional `corpus/{paper_id}.json`

Normalized mapping:

- `queries[query_id].query` -> validation query `question`.
- `queries[query_id].type` -> query metadata `type`.
- `queries[query_id].source` -> query metadata `source_modality`.
- `qrels[query_id].doc_id` -> qrel `document` or `document_name` after local PDF naming.
- `qrels[query_id].section_id` -> qrel metadata `source_section_id`.
- `answers[query_id]` -> `qa.items[].answer`.
- `pdf_urls[doc_id]` -> private acquisition metadata; public docs may reference only the
  upstream dataset and selected source key.

Strength progression:

1. Document-level qrels prove expected-document retrieval.
2. Section-level metadata helps diagnose whether chunking preserved the relevant source
   region.
3. Chunk snapshot mapping upgrades source sections to `expected_chunks`.
4. Public-safe retention records per-query ranks and stable content hashes without raw
   chunks.

### FinanceBench Mapping

Input:

- open-source JSONL sample;
- PDF files or source document links;
- evidence text, evidence page, document name, answer, and question fields.

Normalized mapping:

- question -> validation query `question`.
- sample ID -> query ID.
- document name -> qrel `document`.
- evidence page -> qrel metadata `evidence_page_num`.
- evidence text -> `qa.items[].evidence_text` and optional expected terms after review.
- answer -> `qa.items[].answer`.
- finance task type or sector -> query metadata.

Strength progression:

1. Document-level qrels establish expected filing retrieval.
2. Evidence-page metadata detects page or table-region misses.
3. Evidence text becomes expected terms.
4. Chunk snapshots map evidence text to expected chunk hashes.
5. Table-specific diagnostics track table row, column, and numeric reasoning misses.

### QASPER Mapping

Input:

- question records;
- answer records;
- supporting evidence;
- paper identifiers and available paper text or PDF identifiers.

Normalized mapping:

- question ID -> validation query ID.
- question text -> validation query `question`.
- paper ID -> qrel `document`.
- supporting evidence -> `qa.items[].evidence` and expected terms.
- answer type -> query metadata.
- unanswerable labels -> metadata and downstream query-evaluation expectations.

Strength progression:

1. Paper-level qrels prove source-paper retrieval.
2. Evidence paragraph text becomes expected terms.
3. PDF-derived chunk snapshots map evidence paragraphs to expected chunks.
4. Unanswerable cases track over-retrieval and unsupported answer generation risk.

### TREC-COVID Mapping

Input:

- topics;
- CORD-19 document IDs;
- qrels with relevance values.

Normalized mapping:

- topic ID -> query ID.
- topic question or query field -> validation query `question`.
- qrels document ID -> qrel `document_id` or corpus document key.
- qrels relevance -> normalized relevance score.
- narrative -> query metadata or QA context.

Strength progression:

1. Use as qrels parser and metric regression coverage.
2. Use a small topic/document subset for retrieval metric calibration.
3. Defer full corpus use until large-corpus RAGFlow resource limits and cleanup rules
   are explicit.

## Integration With Current Skills

### `ragflow-doc-to-md`

Use dataset PDFs as source documents for formal ingestion:

1. Download the selected PDF into a private run root.
2. Run `ragflow-doc-to-md pipeline` with a deterministic profile.
3. Require `handoff_mode: formal_ingest`.
4. Retain `doc_manifest.json`, `quality_report.json`, `retrieval_hints.json`,
   `profile_suggestions.json`, `ingest_readiness_report.json`, and
   `formal_handoff_manifest.json`.
5. Compare conversion quality by dataset and modality:
   - text integrity;
   - table preservation;
   - local image asset count;
   - chunk marker density;
   - blocked quality gates;
   - missing asset warnings.

This turns external PDFs into repeatable handoff quality tests.

### `ragflow-kb-build`

Use normalized benchmark artifacts to drive dry-run, profile selection, and optional
disposable live comparison:

1. Run `inspect-handoff`.
2. Run `build.py --dry-run --json` and retain `build_payload_preview`,
   `handoff_consumption_status`, `delimiter_profile_guidance`, and
   `build_readiness_metrics`.
3. Run `benchmark import` for normalized dataset artifacts.
4. Run `benchmark preflight` and record benchmark strength.
5. Run `profile.py experiment --bounded-defaults` for small enrichment matrices.
6. Run `optimize --plan-only`, `cleanup-plan`, and `readiness`.
7. Only with explicit user approval, run disposable live KB comparison.
8. Generate public-safe query-result retention artifacts.
9. Execute cleanup and verify cleanup before marking any live checklist item complete.

This connects dataset evidence directly to profile materialization, parser settings,
enrichment behavior, and cleanup governance.

### `ragflow-query`

Use normalized benchmark and live validation outputs to test retrieval behavior:

1. Use `validation-suggestions` only as a deterministic seed when upstream qrels are
   missing or weak.
2. Use direct query and host-assisted query only after a KB manifest exists and the
   workflow explicitly needs query-path evidence.
3. Keep assistant-profile and assistant-test-plan outputs advisory unless a later
   gated adapter is approved.
4. Compare query traces against qrels, expected chunks, and public-safe retention
   artifacts.

This keeps query optimization evidence grounded in benchmark artifacts instead of
one-off manual inspection.

## Metrics To Track

### Handoff And Conversion Metrics

- handoff readiness status;
- quality gate status and issue counts;
- document count and approximate source size;
- Markdown character count and empty-document count;
- table count and table warning count;
- local image asset count and missing-image count;
- chunk marker count, marker density, and section-boundary count;
- profile suggestion count and clamping warnings;
- retrieval hint count by modality.

### Build And Parser Metrics

- dry-run `ok`;
- build payload preview sent/local-only/unsupported field counts;
- language materialization status;
- delimiter guidance status;
- handoff consumption status distribution;
- parse status and parse elapsed time;
- document parse count and failed parse count;
- chunk count, average chunk length, and chunk length distribution;
- requested versus effective profile evidence when read-back sidecars exist.

### Retrieval Metrics

- hit rate;
- recall at k;
- precision at k;
- MRR;
- nDCG;
- empty-result rate;
- wrong-document rate;
- strict chunk recall at k;
- expected chunk hit rate;
- matched expected terms;
- table query hit rate;
- image or mixed-modality query hit rate;
- top-k stability across profile candidates;
- query-specific regressions and improvements.

### Cost, Latency, And Risk Metrics

- parse time per candidate;
- validation/query elapsed time;
- RAGFlow enrichment flags enabled;
- cost or latency evidence missing/known;
- candidate duplicate/effective-profile alias count;
- cleanup required, cleanup executed, and cleanup verified;
- live mutation count;
- script-owned LLM call count, expected to remain zero for repository-owned tools.

### Benchmark Strength Metrics

- query count;
- judged query count;
- qrel count;
- qrel field distribution;
- target document count;
- query type and modality distribution;
- expected-term coverage;
- expected-chunk coverage;
- negative or unanswerable case count;
- saturated metric risk;
- decision tier: smoke, exploratory, recommendation, or promotion gate.

## Improvement Loop

Use a four-level benchmark maturity model.

### Level 0: Seed

Purpose:

- prove the import path and artifact shape;
- support smoke checks and dry-run readiness.

Requirements:

- 1 PDF;
- 3 to 5 queries;
- document-level qrels;
- source attribution;
- preflight report.

Allowed conclusion:

- The benchmark path works.
- Retrieval quality conclusions are exploratory only.

### Level 1: Exploratory

Purpose:

- compare parser profiles and bounded enrichment candidates on a small but real sample.

Requirements:

- 1 to 3 PDFs;
- 6 to 15 queries;
- at least two query types;
- document-level qrels plus section, page, or evidence-text metadata;
- public-safe retention report.

Allowed conclusion:

- Candidate A is better, tied, or worse on this sample.
- No default profile promotion yet unless strict evidence is present.

### Level 2: Promotion Candidate

Purpose:

- justify changing recommended profiles or guidance.

Requirements:

- multiple PDFs or one intentionally representative full document;
- 20 or more queries where practical;
- expected terms and expected chunks for core queries;
- table/image coverage if the source contains those modalities;
- benchmark strength report without high-severity warnings;
- cleanup-verified disposable live comparison if live mutation is part of the claim.

Allowed conclusion:

- A reviewed profile or guidance change may be recommended if quality improves without
  unacceptable cost, latency, or cleanup risk.

### Level 3: Regression Baseline

Purpose:

- track release-to-release retrieval and ingestion drift.

Requirements:

- pinned dataset subset;
- stable source hashes;
- normalized benchmark artifacts;
- reproducible handoff profile;
- retained public-safe query-result artifacts for each release candidate;
- trend reports and threshold gates.

Allowed conclusion:

- A release candidate is healthy, regressed, or needs manual review on the standard
  benchmark portfolio.

## 分阶段落实任务清单

以下阶段 0 到阶段 5 记录首轮 Open RAG Benchmark seed 的执行路线。它们最初
用于支撑 `docs/34-pipeline-consumption-gap-quality-improvement-plan.md` 的剩余
live-gated enrichment comparison；截至 2026-07-09，该首轮路线已经完成并关闭
`docs/34` 的对应 checklist 项。阶段 6 之后仍是后续 benchmark portfolio 扩展
计划。除非当前线程获得明确授权，任何新的 live RAGFlow mutation 仍然默认不执行。

### 阶段 0：冻结规划基线（已完成）

目标：

- 将本文件确认为标准数据集引入和后续 benchmark 工作的执行依据。
- 避免继续用一次性报告或临时 query 集判断检索质量。

任务：

- 审阅并接受本计划的数据集优先级：Open RAG Benchmark 第一，
  FinanceBench 第二，QASPER 第三，TREC-COVID 延后。
- 确认治理边界：不把外部 PDF、源数据集 dump、raw chunks、真实 RAGFlow
  endpoint、KB 名称、dataset ID 或 document ID 写入公开仓库。
- 记录当时 gate 条件：只有真实 live comparison、retention artifacts 和
  cleanup verification 都完成后，才可关闭 `docs/34` 对应 checklist 项；该
  gate 已在阶段 5 后关闭。
- 如需要进入版本历史，提交本文件作为 planning baseline；提交前只 stage
  intended docs changes。

完成标准：

- 本计划被接受为后续执行基线。
- 后续执行任务都引用本计划的 artifact contract、指标和 gate 条件。

### 阶段 1：Open RAG Benchmark 离线种子集（已完成）

目标：

- 建立最小可用、可复用、可审计的 PDF-first benchmark seed。
- 不触发 live mutation，只验证 acquisition、normalization 和 artifact shape。

任务：

- 从 Open RAG Benchmark 选择 1 篇 positive PDF。
- 从对应 upstream `queries.json` / `qrels.json` / `answers.json` 抽取 6 到
  10 个 query。
- 覆盖至少两类问题：文本事实、概览或跨段落问题；如果样本支持，再加入
  table、image 或 mixed-modality query。
- 在 private run root 下载 PDF 和 upstream source artifacts，不把 raw PDF 或
  source dump 放入仓库。
- 生成标准 benchmark artifacts：
  - `queries.json`
  - `qrels.json`
  - `qa.json`
  - `source_attribution.json`
  - `selection_report.json`
  - `manifest.json`
- 在 `source_attribution.json` 中记录 upstream dataset、URL、license、selected
  source keys，以及 query/answer 是否来自 LLM-generated upstream dataset。

完成标准：

- 有一个可被当前工具消费的 `ragflow_benchmark_manifest_v1`。
- qrels 至少达到 document-level，并保留 section/source metadata 以便后续
  升级为 expected-chunk qrels。
- 没有 live RAGFlow 调用，也没有 public repo 数据集大文件变更。

### 阶段 2：Benchmark Import 和 Preflight 闭环（已完成）

目标：

- 验证阶段 1 的 benchmark seed 能被 `ragflow-kb-build` benchmark 工具链稳定
  消费。
- 在进入任何 live readiness 前先量化 benchmark strength。

任务：

- 运行 `ragflow-kb-build benchmark import`，将 seed artifacts 标准化为
  `manifest.json`、`queries.json`、`qrels.json` 和 `qa.json`。
- 运行 `ragflow-kb-build benchmark preflight`。
- 检查 query/qrels 一致性：
  - 每个 query 都有 qrels；
  - 每条 qrel 都能匹配 query；
  - qrel count、judged query count 和 query type distribution 合理；
  - document-level weak-benchmark warning 是预期 warning，而不是误判。
- 记录 benchmark strength：
  - query count；
  - judged query count；
  - qrel field distribution；
  - target document count；
  - modality distribution；
  - expected-term coverage；
  - expected-chunk coverage。

完成标准：

- Preflight 通过，或只存在已解释的弱 qrels warning。
- 该 benchmark 可用于 handoff dry-run readiness。
- 仍不声称 profile 或 enrichment 有检索质量提升。

### 阶段 3：PDF 到 Handoff 到 Dry-run 验证（已完成）

目标：

- 用真实公开 PDF 验证 `ragflow-doc-to-md` 到 `ragflow-kb-build` 的离线链路。
- 将外部标准数据集变成 repeatable handoff quality evidence。

任务：

- 对阶段 1 选定 PDF 运行 `ragflow-doc-to-md pipeline`。
- 确认输出是 `handoff_mode: formal_ingest`。
- 保留并检查以下 handoff sidecars：
  - `doc_manifest.json`
  - `quality_report.json`
  - `retrieval_hints.json`
  - `profile_suggestions.json`
  - `ingest_readiness_report.json`
  - `formal_handoff_manifest.json`
- 运行 `ragflow-kb-build inspect-handoff`。
- 运行 `ragflow-kb-build --dry-run --json`。
- 检查 dry-run 关键字段：
  - `build_payload_preview`
  - `handoff_consumption_status`
  - `delimiter_profile_guidance`
  - `build_readiness_metrics`
  - retrieval hints 是否保持 advisory，而不是静默写入 parser config。
- 记录 public-safe 离线指标：handoff readiness、quality gate、table/image count、
  chunk marker count、profile suggestion warning 和 dry-run `ok`。

完成标准：

- 外部 PDF 可稳定生成 formal handoff。
- `inspect-handoff` 和 dry-run 通过或只有已分类的 advisory warning。
- 不执行 live mutation。

### 阶段 4：为 `docs/34` disposable enrichment 做 readiness（已完成）

目标：

- 使用标准 benchmark seed 准备 `docs/34` 最后一项 live-gated enrichment
  comparison；该阶段当时只停在 plan/readiness，不执行 live mutation。

任务：

- 基于阶段 1 到阶段 3 的 benchmark 和 handoff 生成 bounded candidates：
  - `auto_keywords=0, auto_questions=0`
  - `auto_keywords=0, auto_questions=1`
  - `auto_keywords=1, auto_questions=0`
  - `auto_keywords=1, auto_questions=1`
- 运行 profile lint，检测重复 effective profile，并在进入 live 前去重。
- 运行 optimization plan。
- 运行 cleanup plan。
- 运行 readiness。
- 检查 readiness evidence：
  - candidate count；
  - profile lint pass count；
  - LLM-backed enrichment warning；
  - cleanup plan 是否完整；
  - readiness 是否 `ok=true`；
  - benchmark strength 是否只支持 exploratory conclusion。

完成标准：

- 有 optimization plan、cleanup plan 和 readiness report。
- 如果 delimiter base 与 `auto_keywords=0, auto_questions=0` 产生重复
  effective profile，应在 Stage 5 中只创建一个代表性 disposable KB。
- 如果 readiness 不是 `ok=true`，不进入 live comparison。
- Readiness 通过后，只能进入下一阶段的显式授权流程；首轮已在阶段 5 获得
  授权并完成。

### 阶段 5：一次受控 Disposable Live Comparison（已完成）

目标：

- 在明确授权后，使用标准 seed 关闭 `docs/34` 剩余的 live-gated checklist
  item；首轮已完成并验证 cleanup。

任务：

- 获得当前线程明确授权，授权范围必须限定为 disposable KB、bounded
  `auto_keywords` / `auto_questions` matrix、retention artifact generation 和
  cleanup verification。
- 执行 4 个 unique effective candidate profile 的 disposable KB comparison。
- 对每个候选记录：
  - hit rate；
  - recall at k；
  - precision at k；
  - MRR；
  - nDCG；
  - empty-result rate；
  - wrong-document rate；
  - top-k stability；
  - query-specific regressions；
  - parse/query latency；
  - enrichment risk and cost notes。
- 生成 public-safe retention JSON 和 Markdown。
- 执行 cleanup。
- 验证 disposable KB cleanup 成功。
- 只将 sanitized metrics 和 artifact names 写入 public docs。

完成标准：

- Live comparison 完成。
- Public-safe retention artifacts 完成。
- Cleanup verified。
- Redaction scan 和 release hygiene 通过。
- 以上条件已在首轮 Stage 5 后满足，`docs/34` 对应 checklist 项已关闭。

### 阶段 6：FinanceBench 表格和数值压力集

目标：

- 补齐 table-heavy、financial filing、evidence page 和 numeric evidence
  retrieval 的标准测试能力。

任务：

- 选择 1 到 2 个较小或中等规模的 FinanceBench filing PDF。
- 选择 evidence-rich table/numeric questions。
- 从 upstream fields 构造 benchmark artifacts：
  - question -> validation query；
  - evidence document name -> qrel document；
  - evidence page -> qrel metadata；
  - evidence text -> `qa.json` evidence and optional expected terms；
  - answer -> `qa.json` answer。
- 先运行 handoff conversion、inspect-handoff 和 dry-run。
- 如后续有 live approval，再生成 chunk snapshot，并将 evidence text 映射到
  expected chunk hashes。
- 单独跟踪 table/numeric 指标：table query hit rate、evidence-page miss、
  expected-term miss、wrong-document rate 和 table fragmentation warning。

完成标准：

- 有一个可重复的 table/numeric benchmark slice。
- 该 slice 能检测表格碎片化、错误页、错误文档和数值证据丢失。

2026-07-11 状态：Stage 6 的公共 artifact contract、table/numeric synthetic
fixture、import/preflight 和 portfolio rehearsal 已完成。真实 FinanceBench filing、
evidence page、handoff conversion、inspect-handoff 和 dry-run 尚未执行，因为没有
operator 提供的 reviewed private source root。当前门禁为
`private_source_fill_required`，不得用 synthetic fixture 关闭本阶段。

### 阶段 7：回归基线组合

目标：

- 将标准数据集从一次性实验升级为 release-health regression portfolio。

任务：

- 固定 Open RAG Benchmark seed subset。
- 固定 FinanceBench table/numeric slice。
- 后续补充小规模 QASPER scientific QA slice。
- 记录每个 subset 的 source hashes、license、selection criteria、benchmark
  strength 和 intended decision tier。
- 在 release candidate 或重要质量改动后重复运行：
  - benchmark import/preflight；
  - document conversion；
  - handoff inspection；
  - build dry-run；
  - 必要且获批时的 disposable live comparison；
  - public-safe retention report；
  - trend/delta report。
- 将趋势结果用于 release-health review，区分 CLI/schema 健康和 retrieval
  quality 健康。

完成标准：

- Release validation 可以回答检索质量是否变化，而不只回答 CLI surface 和
  schema 是否兼容。
- 每次质量变化都有 query-level、metric-level 和 public-safe artifact evidence。

2026-07-11 状态：显式输入 portfolio 聚合器、schema identity、release hygiene、
consumer acceptance、strict-vendor smoke 和 Hermes L0 指令已完成。synthetic
portfolio 为 `ready_with_review`，原因是缺少 observed validation；它只证明工具和
artifact contract，不是 Stage 7 的 retrieval-quality regression baseline。真实
Stage 7 仍需要 reviewed Open RAG + FinanceBench subsets、可供 trend/delta 使用的
per-subset validation reports，以及后续 transition observation evidence。

## 立即执行建议

当前已完成阶段 0 到阶段 5 的首轮标准 seed 验证，以及阶段 6/7 所需的公共
artifact contract、portfolio 工具和 synthetic rehearsal。下一步不应从 synthetic
或单一 exploratory seed 推广默认 profile，而应推进真实证据填充：

1. 建立更强 Open RAG Benchmark subset：增加文档数、query 数、expected terms
   或 expected chunks。
2. 引入 FinanceBench 小切片，补 table-heavy、numeric evidence 和 evidence-page
   压力测试。
3. 如需 PDF native/fallback 对照，单独申请 DeepDoc live baseline approval。
4. 将当前 seed 固化为 regression smoke/exploratory baseline，并在后续 release
   health review 中重复运行。

## Governance And Safety

- Do not vendor large external PDFs, upstream dataset dumps, or derived raw chunks into
  this repository.
- Keep downloaded PDFs and raw run artifacts in private run roots.
- Public docs may record dataset names, upstream URLs, selected source key counts,
  sanitized metrics, artifact names, and failure classes.
- Public docs must not include private endpoints, API keys, dataset IDs, document IDs,
  KB names, private host paths, source run-root paths, or raw retrieved chunks.
- External dataset licenses must be recorded in `source_attribution.json` and reviewed
  before any release artifact includes derived samples.
- `cc-by-nc-4.0` datasets should be treated as research/test inputs, not packaged
  commercial release data.
- Live RAGFlow mutation remains approval-gated and cleanup-verified.
- Script-owned LLM/RAGAS calls remain out of scope. If a dataset was created with LLM
  assistance upstream, record that fact as dataset provenance rather than rerunning LLM
  generation inside these skills.

## Acceptance Targets

The standard-dataset program is useful when it can answer these questions repeatedly:

- Can `ragflow-doc-to-md` produce formal handoffs for representative public PDFs without
  quality regressions?
- Can `ragflow-kb-build` explain exactly which handoff evidence becomes RAGFlow state
  and which evidence remains advisory?
- Do delimiter, language, image path, and enrichment changes improve retrieval evidence
  rather than only changing parser payloads?
- Do table and image queries remain healthy across releases?
- Does a proposed profile change improve strict evidence without unacceptable cost,
  latency, cleanup risk, or query-specific regressions?
- Can public summaries preserve useful metrics without leaking raw chunks, private
  identifiers, endpoints, or credentials?

## Immediate Next Step

Treat the first Open RAG Benchmark seed as a completed exploratory baseline. The public
attribution/selection contract, explicit-input portfolio, synthetic replay, and Hermes L0
instruction in `docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md`
are now complete. The next ordinary offline quality step requires operator-reviewed
private inputs: strengthen the real seed, add a FinanceBench table/numeric slice, attach
observed per-subset validation reports, and form a true two-subset regression baseline.
`docs/36-ragflow-kb-parameter-materialization-plan.md` remains
contract-blocked with zero current Stage 8C candidates. A DeepDoc native baseline remains
a separate, explicitly approved live comparison only when PDF-native behavior is the
question being tested.
