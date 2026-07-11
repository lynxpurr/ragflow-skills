# Hermes L0 Test For Benchmark Evidence Strengthening

Status: independent repository-only L0 replay passed
Date: 2026-07-11
Last independently replayed: 2026-07-11 at repository commit `3b94d93`

## Purpose And Boundary

This instruction lets a Hermes agent independently replay the synthetic benchmark
evidence chain added by the benchmark-strengthening round. The replay validates the
normalized attribution and selection contracts, deterministic sampling provenance, the
offline two-subset portfolio, report sanitization, and repository cleanliness.

Authorized by default:

- read the current `ragflow-skills` repository and its committed synthetic fixtures;
- run focused Python tests and offline repository tools;
- write all replay artifacts to one new repository-external temporary run root;
- run benchmark import, preflight, deterministic sample, and portfolio generation over
  the committed synthetic fixtures;
- produce a sanitized Chinese test report.

Not authorized:

- downloading Open RAG, FinanceBench, PDFs, dataset rows, or any other source material;
- reading private source roots, credentials, endpoints, deployment configuration, logs,
  databases, user documents, or retrieved chunks;
- any RAGFlow HTTP/API call, including read-only calls;
- dataset or KB creation, update, upload, parse, reparse, delete, or cleanup;
- DeepDoc, MinerU service, native PDF conversion, or private-source conversion;
- script-owned LLM or RAGAS calls;
- Stage 8C execution, parameter promotion, commit, push, or repository modification.

If any prohibited action appears necessary, Hermes must stop with `approval_required`
and name the exact requested level. It must not broaden the replay on its own.

## Expected Evidence Contract

The committed synthetic portfolio contains:

- two subsets: `open-rag-synthetic-v1` and `finance-synthetic-v1`;
- six queries, six judged queries, twelve qrels, and six grounded QA items;
- text, table, numeric, mixed-modality, and negative/unanswerable metadata;
- six expected-term queries and six declared expected-chunk queries;
- source attribution and selection reports for both subsets;
- an Open RAG deterministic sample of size two using `stratified`, seed `7`;
- no observed live validation report, so the portfolio status must be
  `ready_with_review` with reason `missing_observed_validation`;
- safety flags showing zero RAGFlow calls, zero live writes, zero script-owned LLM calls,
  and no directory discovery.

Declared expected-chunk coverage is synthetic contract coverage only. It is not observed
strict chunk recall and must not be reported as live retrieval evidence.

## Independent Replay Evidence

Hermes independently replayed this instruction against commit `3b94d93` from an
initially clean worktree. The final worktree remained clean and the replay did not modify
the repository.

Verified results:

- Python compile: pass for the three required files;
- governance, portfolio, and schema tests: 47 passed with 17 subtests;
- benchmark import/sample CLI tests: 2 passed;
- Open RAG synthetic import: 3 queries, 3 judged queries, 6 qrels, and 3 QA items;
- Open RAG preflight: `promotable` with zero errors;
- deterministic sample: `stratified`, seed `7`, size `2`, with sorted IDs and matching
  QA filtering;
- Finance synthetic import: 3 queries, 3 judged queries, 6 qrels, and 3 QA items;
- Finance preflight: `exploratory` with the expected single warning;
- portfolio: 2 subsets, 2 datasets, 6 queries, 6 judged queries, 12 qrels, 6 QA items,
  6 expected-term queries, 6 declared expected-chunk queries, 4 table/numeric queries,
  and 1 negative/unanswerable query;
- assessment: `ready_with_review` with `missing_observed_validation`;
- safety: zero RAGFlow HTTP calls, zero live writes, zero DeepDoc/MinerU service calls,
  zero script-owned LLM calls, zero directory discovery, and zero Stage 8C actions;
- sensitive review: no unresolved private path, endpoint, credential, or real
  dataset/document/KB identifier in tool reports or agent-authored prose;
- portfolio redaction findings: zero; import/preflight/sample findings were applied
  config-path redactions with no secret or bearer-token value retained.

The retained report basename was `hermes-final-report.txt`; the private run root was
reported only by its label, `ragflow-benchmark-evidence-hermes-l0-20260711T002112Z`.
The replay confirms the synthetic offline contract but leaves
`private_source_fill_required` and `transition_observation_fill_required` unchanged.

## Copy-Paste Hermes Task

Send the following block to Hermes from a committed, clean repository checkout.

```text
请在当前 ragflow-skills 仓库执行 Benchmark Evidence Strengthening 的 Hermes L0
独立复验。仅允许仓库内合成 fixture 和离线工具；禁止下载真实数据，禁止读取私有
source root，禁止任何 RAGFlow HTTP/API，禁止 KB/dataset 写入，禁止 DeepDoc/MinerU
服务或 PDF 转换，禁止脚本自有 LLM/RAGAS，禁止 Stage 8C，禁止修改、提交或推送仓库。

先读取：
- docs/39-benchmark-evidence-strengthening-hermes-test.md
- docs/38-benchmark-evidence-strengthening-and-transition-validation-plan.md
- docs/superpowers/plans/2026-07-11-benchmark-evidence-strengthening.md

执行要求：
1. 从仓库根目录运行：
   git status --short --branch
   git rev-parse HEAD
   git diff --check
2. 初始工作区必须 clean。若不 clean，返回
   approval_required:dirty_worktree，并停止；不要清理、stash 或覆盖现有修改。
3. 在仓库外创建一个新的唯一运行目录，例如：
   /tmp/ragflow-benchmark-evidence-hermes-l0-<UTC timestamp>
   不得在仓库内创建 .local、报告目录、缓存或临时 fixture。
4. 设置 RUN_ROOT 为该目录，后续所有生成物都写入 RUN_ROOT。
5. 运行聚焦验证：
   python3 -m py_compile \
     packages/ragflow-skill-runtime/src/ragflow_skill_runtime/benchmark_governance.py \
     skills/ragflow-kb-build/scripts/build.py \
     tools/benchmark_portfolio.py
   python3 -m pytest \
     packages/ragflow-skill-runtime/tests/test_benchmark_governance.py \
     packages/ragflow-skill-runtime/tests/test_benchmark_portfolio.py \
     packages/ragflow-skill-runtime/tests/test_schema_identity_check.py -q
   python3 -m pytest \
     packages/ragflow-skill-runtime/tests/test_kb_build_cli.py \
     -k 'benchmark_import or benchmark_sample' -q
6. 使用以下仓库 fixture，不得替换为下载数据：
   packages/ragflow-skill-runtime/tests/fixtures/benchmark_evidence/
7. 执行 Open RAG synthetic import，必须增加：
   --name open-rag-synthetic-v1
   --report-md $RUN_ROOT/open-rag-import.md
   --redaction-report $RUN_ROOT/open-rag-import.redaction.json
   输入为 open_rag_queries.json、open_rag_qrels.json、open_rag_qa.json、
   open_rag_source_attribution.json、open_rag_selection_report.json，输出目录为
   $RUN_ROOT/open-rag。
8. 对 $RUN_ROOT/open-rag/manifest.json 执行 benchmark preflight，输出：
   $RUN_ROOT/open-rag-preflight.json
   $RUN_ROOT/open-rag-preflight.md
   $RUN_ROOT/open-rag-preflight.redaction.json
9. 对 Open RAG manifest 执行 benchmark sample：
   --name open-rag-synthetic-sample-v1
   --output $RUN_ROOT/open-rag-sample
   --size 2 --strategy stratified --seed 7
   --report-json $RUN_ROOT/open-rag-sample.json
   --report-md $RUN_ROOT/open-rag-sample.md
   --redaction-report $RUN_ROOT/open-rag-sample.redaction.json
10. 执行 Finance synthetic import，必须增加：
    --name finance-synthetic-v1
    --report-md $RUN_ROOT/finance-import.md
    --redaction-report $RUN_ROOT/finance-import.redaction.json
    输入为 finance_queries.json、finance_qrels.json、finance_qa.json、
    finance_source_attribution.json、finance_selection_report.json，输出目录为
    $RUN_ROOT/finance。
11. 对 $RUN_ROOT/finance/manifest.json 执行 benchmark preflight，输出：
    $RUN_ROOT/finance-preflight.json
    $RUN_ROOT/finance-preflight.md
    $RUN_ROOT/finance-preflight.redaction.json
12. 将 portfolio_config.example.json 复制为 $RUN_ROOT/portfolio-config.json；不要修改
    其中的 subset ID、dataset、license、decision tier 或相对路径。
13. 运行 tools/benchmark_portfolio.py，输出：
    $RUN_ROOT/portfolio.json
    $RUN_ROOT/portfolio.md
    $RUN_ROOT/portfolio.redaction.json
14. 验证 sample selection_report.json：
    parent_subset_id = open-rag-synthetic-v1
    sampling = {strategy: stratified, seed: 7, size: 2}
    selected_query_ids 已排序且恰好 2 条
    sample qa.json 恰好保留这 2 个 query_id
15. 验证 portfolio.json：
    schema = ragflow_benchmark_portfolio_v1
    ok = true
    subset_count = 2
    dataset_count = 2
    query_count = 6
    judged_query_count = 6
    qrel_count = 12
    qa_count = 6
    expected_term_query_count = 6
    expected_chunk_query_count = 6
    table_numeric_query_count = 4
    negative_unanswerable_query_count = 1
    assessment.status = ready_with_review
    assessment.reasons 包含 missing_observed_validation
    safety.ragflow_calls = 0
    safety.writes_live_ragflow = false
    safety.script_owned_llm_calls = 0
    safety.directory_discovery = false
16. 仅对 shareable reports 做 tool-output 敏感扫描：RUN_ROOT 根目录中的
    *-import.md、*-preflight.json/md、open-rag-sample.json/md、portfolio.json/md 和
    所有 *.redaction.json。不要把 normalized manifest/queries/qrels/qa 的原始
    source-path 字段误判为 public report。
17. 分别扫描：完整 /home 或 /tmp 路径、http/https endpoint、credential-shaped
    api-key/bearer/token 值、真实 dataset/document/KB 标识。redaction sidecar 中
    bearer_token: 0 这类规则计数字段不是 secret，但必须人工确认其值为零。
18. tool redaction finding 表示已发生脱敏，不等于 unresolved leak。要求所有公开
    JSON/Markdown 中无敏感字面量；portfolio redaction finding 应为 0；sample 或
    import/preflight sidecar 可以记录 path redaction，但不得保留原始 path。
19. 将最终中文报告先写到 $RUN_ROOT/hermes-final-report.txt，对该 prose 单独执行
    同样的敏感扫描。tool sidecar 不能替代 agent prose 扫描。
20. 最后再次运行：
    git status --short --branch
    git diff --check
    git rev-parse HEAD
    最终 HEAD 和工作区状态必须与步骤 1 一致。若测试造成仓库变化，标记
    test_noncompliant:repository_modified 并停止；不要提交或清理。

任何 source download、private-source conversion、RAGFlow HTTP、DeepDoc、live
mutation、LLM/RAGAS 或 Stage 8C 请求都必须返回 approval_required，并且本轮不执行。

最终返回简洁中文报告，包含：仓库 commit、初始/最终工作区、各测试命令状态、
两套 import/preflight 状态、sample provenance、portfolio counts/coverage/assessment、
所有 safety 计数、tool-output 与 prose 两次敏感扫描结果、零 RAGFlow/LLM 调用结论、
报告 basename，以及残余门禁 private_source_fill_required 和
transition_observation_fill_required 是否仍存在。
```

## Reference Commands

Hermes may construct the commands from the copy-paste task. The required public CLI
flags are:

```text
benchmark import:
  --queries --qrels --qa --source-attribution --selection-report --output --name
  --report-md --redaction-report

benchmark preflight:
  --manifest --report-json --report-md --redaction-report

benchmark sample:
  --manifest --output --name --size 2 --strategy stratified --seed 7
  --report-json --report-md --redaction-report

benchmark portfolio:
  --config --report-json --report-md --redaction-report
```

The normalized subset artifacts under `$RUN_ROOT/open-rag`, `$RUN_ROOT/finance`, and
`$RUN_ROOT/open-rag-sample` are operator-owned inputs for downstream processing. Only the
sanitized root-level reports and the final reviewed prose are candidates for sharing.

## Hermes Final Report Template

```markdown
# Hermes Benchmark Evidence Strengthening L0 Report

Date:
Agent:
Repository commit:
Initial worktree: clean / noncompliant
Final worktree: clean / noncompliant
Repository modified by replay: no/yes
Authorization: L0 repository-only synthetic replay

## Verification Commands

| Command | Status | Evidence |
| --- | --- | --- |
| py_compile | pass/fail | |
| governance/portfolio/schema tests | pass/fail | |
| benchmark CLI tests | pass/fail | |
| Open RAG import/preflight/sample | pass/fail | |
| Finance import/preflight | pass/fail | |
| portfolio generation | pass/fail | |

## Sampling Provenance

Parent subset:
Strategy:
Seed:
Size:
Selected query IDs sorted: true/false
QA query IDs match selection: true/false

## Portfolio

Schema:
Status:
Subsets/datasets:
Queries/judged queries/qrels/QA:
Expected-term queries:
Declared expected-chunk queries:
Table/numeric queries:
Negative/unanswerable queries:
Assessment reasons:

## Safety

RAGFlow HTTP calls: 0
RAGFlow writes: 0
DeepDoc/MinerU service calls: 0
Script-owned LLM/RAGAS calls: 0
Directory discovery: false
Stage 8C actions: 0

## Redaction Review

Tool reports scanned separately: yes/no
Agent prose scanned separately: yes/no
Unresolved private paths: 0/nonzero
Unresolved endpoints: 0/nonzero
Unresolved credentials: 0/nonzero
Unresolved real dataset/document/KB identifiers: 0/nonzero
Redaction findings explained as applied redactions: yes/no

## Artifacts

Run-root label without full private path:
Report basenames:

## Decision

Synthetic L0 replay reproducible:
Private source fill still required:
Transition observation fill still required:
Live/Stage 8C authorization changed: no
Residual risks:
Next action:
```

## Acceptance Criteria

The L0 replay passes when:

1. The initial and final repository states are clean and identical.
2. Focused compile, governance, portfolio, schema, and CLI tests pass.
3. Both imports and both preflights succeed from committed synthetic fixtures.
4. The deterministic sample preserves attribution and records the expected parent,
   strategy, seed, size, sorted query IDs, and matching QA subset.
5. The portfolio reports the expected 2/2/6/6/12/6 counts and coverage values.
6. The portfolio is `ready_with_review`, not `ready` and not `blocked`.
7. Missing observed validation remains explicit and no strict live metric is invented.
8. All safety counters remain zero/false as specified.
9. Shareable reports and final prose contain no prohibited private or live values.
10. No source download, private conversion, RAGFlow/DeepDoc/LLM call, live mutation, or
    Stage 8C action occurs.

A passing L0 replay validates the public offline tooling and synthetic evidence contract.
It does not complete the private Open RAG or FinanceBench evidence fill, satisfy the five
transition-run requirement, establish a Level 3 retrieval regression baseline, or
authorize any live or Stage 8C work.
