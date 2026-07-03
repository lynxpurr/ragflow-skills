# 20. ragflow-doc-to-md 高质量入库能力提升计划

状态：拟定开发计划
日期：2026-07-03
适用范围：让 `ragflow-doc-to-md` 具备不弱于 RAGFlux 的高质量文档入库准备能力，并与
`ragflow-kb-build`、`ragflow-query` 形成稳定的三段式知识库构建流水线。

## 第一部分：使用问题客观描述

### 1.1 核心目标

本轮优化的目标不是简单复制 RAGFlux 的包结构，而是让 `ragflow-doc-to-md` 在正式入库场景下
稳定产出高质量 RAGFlow handoff，使后续两个 skill 能继续完成高质量知识库构建：

```text
ragflow-doc-to-md  ->  ragflow-kb-build  ->  ragflow-query
高质量 handoff         高质量 KB 构建         高质量检索验证
```

`ragflow-doc-to-md` 应负责把原始 PDF/Office/图片/Markdown 变成可审计、可验证、可入库的
Markdown handoff；`ragflow-kb-build` 应负责 RAGFlow 创建、上传、解析、验证和健康诊断；
`ragflow-query` 应负责检索、assistant review、route/activation 验证和用户查询体验检查。

### 1.2 当前用户和 host-agent 容易遇到的问题

近期 Hermes/OpenClaw 对比测试显示，用户和 host agent 很容易把普通 `convert` 输出当成正式入库
产物来对比 RAGFlux thick package。这样会产生几个表象问题：

- `ragflow-doc-to-md` 看起来没有 `<!-- chunk -->` 标记。
- `ragflow-doc-to-md` 看起来只有 `doc_manifest.json`、`quality_report.json`、`runtime_report.json`
  和 Markdown/图片。
- `ragflow-doc-to-md` 看起来没有 `retrieval_hints.json`、入库建议、README、artifact index 等
  rich sidecars。
- RAGFlux 看起来更适合后续 chunk build，因为它默认输出较厚的结构化包。

这些结论对“快速预览/薄转换输出”是客观成立的，但不能代表当前正式 replacement path 的完整能力。
`ragflow-doc-to-md pipeline` 已经能串联 convert、postprocess、rich package 和非密钥 ingest plan。
真正的问题是：正式 pipeline 入口、产物含义和与后续两个 skill 的协作方式还不够显眼，host agent
仍可能跑错命令或误读输出。

### 1.3 与 RAGFlux 相比仍需补强的真实差距

即使使用正式 pipeline，`ragflow-doc-to-md` 仍有几个值得继续补强的方向：

| 差距 | 当前表现 | 对 KB 质量的影响 |
| --- | --- | --- |
| 正式模式可发现性 | 普通 `convert` 与正式 `pipeline` 容易被混用 | host agent 可能漏掉 chunk markers、hints 和 ingest plan |
| Chunk marker 密度 | 当前 `chunk-markers` 策略较保守 | 某些目录型/产品型文档可能缺少更细粒度边界 |
| 图片语义 | 图片文件名稳定但语义弱，位置信息主要依赖 sidecar | 用户和后续诊断不易理解图片来源、页码、类型和上下文 |
| 表格识别 | MinerU HTML `<table>` 可保留，但统计和 hints 对 HTML 表格覆盖不足 | 表格类事实、规格参数和问答候选可能不够强 |
| 质量门深度 | 现有 quality gate 能阻断明显问题，但入库准备度表达还可更直接 | 用户难判断是否应进入 live build |
| 包级审计 | rich sidecars 已存在，但缺少更强的 package manifest / hash / completeness 总结 | 与 RAGFlux thick package 相比，可复核性仍可提升 |
| 对比评估 | RAGFlux 对比仍依赖临时脚本或人工观察 | 后续退役判断不够自动化、可重复 |
| 性能口径 | cold/warm、模型初始化、OCR/table 阶段耗时口径不统一 | 用户难公平比较常驻 MinerU 与自启动流程 |

### 1.4 设计边界

`ragflow-doc-to-md` 不应接管 `ragflow-kb-build` 和 `ragflow-query` 的职责：

- 不直接创建或修改 RAGFlow KB。
- 不保存真实 RAGFlow endpoint、API key、私有路径或用户 KB 名称。
- 不自动调用 LLM 生成 QA 或摘要。
- 不把 live validation 当成默认转换行为。

它应输出足够丰富、足够安全、足够可审计的 handoff，让后续两个 skill 能在 dry-run、live build、
validation 和 query 阶段继续提升知识库质量。

## 第二部分：改善方向

### 2.1 把“正式入库 handoff”变成一等模式

将 `ragflow-doc-to-md` 的使用场景明确分成两类：

| 模式 | 目标 | 推荐命令 | 产物形态 |
| --- | --- | --- | --- |
| 快速预览 | 快速得到 Markdown 文本 | `convert` | thin handoff |
| 正式入库准备 | 为 RAGFlow KB 构建准备高质量 handoff | `pipeline` | rich formal handoff |

正式模式应在 summary、runtime report、README 和 host-agent prompt 中明确显示：

- 当前 handoff 是 `thin_preview` 还是 `formal_ingest`。
- 是否生成 chunk markers。
- 是否生成 rich sidecars。
- 是否生成非密钥 ingest plan。
- 下一步应如何运行 `ragflow-kb-build inspect-handoff` 和 dry-run。

### 2.2 以 KB 质量为中心，而不是以文件数量为中心

RAGFlux 的优势不只是文件多，而是它更接近“为入库服务”的结构化预处理。新的优化应围绕 KB 质量指标展开：

- 解析质量：文本、图片、表格、标题、页码、OCR 清理。
- 切分质量：chunk marker 密度、heading/table/page boundary、preferred boundaries。
- 检索质量：keywords、question candidates、numeric candidates、image/table artifacts。
- 入库准备度：quality gate、sidecar completeness、dry-run readiness、profile compatibility。
- 审计可复核：manifest、hash、artifact index、normalized diff、redaction report。

### 2.3 不复制 RAGFlux，但达到或超过 RAGFlux 的有效能力

应迁移 RAGFlux 对用户真正有价值的能力，而不是复制旧实现：

- `ragflow_config.yaml` -> 非密钥 `ragflow_ingest_plan.yaml`。
- 图片语义文件名 -> 稳定文件名 + 语义 metadata / optional alias。
- 密集 chunk markers -> 可配置 chunk boundary profile。
- retrieval hints -> schema 化、可被 kb-build/query 消费的增强 hints。
- package manifest -> public formal handoff manifest 和 completeness report。

### 2.4 保持 spec coding 的实现纪律

每个新增能力都应按以下顺序推进：

1. 先定义 runtime schema 和中性 fixture。
2. 再实现 deterministic runtime 逻辑。
3. 再增加 CLI surface，默认 dry-run 或 advisory，不做 live mutation。
4. 再输出 JSON-first report；Markdown 只作为 JSON 摘要。
5. 再补充 public skill 文案、host-agent 指引、consumer acceptance 和 platform smoke。
6. 最后根据真实 field-trial 证据决定是否调整默认推荐。

## 第三部分：更新方案

### 3.1 Formal handoff mode 和误用防护

新增或增强 `formal_ingest` 信号，不改变现有兼容性：

- 在 pipeline summary 中写入 `handoff_mode: formal_ingest`。
- 在普通 convert summary 中写入 `handoff_mode: thin_preview`。
- 当 PDF/Office/image 输入使用普通 convert 且未生成 rich sidecars 时，输出 advisory note，提示正式入库应使用 pipeline。
- 在 `package_readme.md` 中明确下一步 `ragflow-kb-build inspect-handoff`、dry-run 和 optional live build。

验收标准：

- host agent 读取 JSON summary 后能判断是否拿到了正式入库 handoff。
- 正式 handoff 不再被误报为“无 chunk 标记、无 hints、薄产物”。

### 3.2 Chunk boundary profile 升级

在现有 `chunk-markers` 基础上增加可选 profile，而不是直接改变默认行为：

```text
chunk-markers-conservative   当前策略，标题边界优先
chunk-markers-dense          更接近 RAGFlux 的章节/表格/图片边界密度
chunk-markers-ragflux-like   面向 RAGFlux 迁移对比的兼容密度
```

每个 profile 都应输出 `chunk_profile_report.json`，记录：

- marker 总数；
- marker 类型分布：heading/page/table/image/list/manual；
- marker 与 retrieval hints preferred boundaries 的关系；
- 是否存在过密或过稀 warning；
- 对 RAGFlow 解析 profile 的建议。

验收标准：

- 离线 fixture 能证明不同 profile 的 marker 数和边界类型稳定。
- live field-trial 只作为后续验证，不作为默认开启条件。

### 3.3 图片语义 metadata 和 optional alias

保持现有 hash 文件名作为稳定主路径，同时增强图片语义：

- 在 `artifact_index.json` 或新的 asset semantics report 中记录页码、类型、alt/caption、附近标题、上下文片段。
- 区分 image、chart、table_image、logo、decorative、unknown 等可解释类型。
- 可选生成 semantic alias map，但不默认改写 Markdown 主引用，避免破坏现有稳定路径。
- 把图片语义信号传递给 `retrieval_hints.json` 和 assistant test plan。

验收标准：

- 没有页码或类型信息时保持兼容，不伪造精确信号。
- 有 `content_list` / `middle_json` 时优先使用结构化信号。
- 报告不包含原始私有路径或远程下载 URL。

### 3.4 HTML table artifact 和表格质量信号

补强 HTML `<table>` 的识别、统计和 hints：

- quality/runtime report 统计 HTML table count。
- `retrieval_hints.json` 生成 `table_artifacts`，记录标题、上下文、行列估算、header preview、页码。
- 对规格参数类表格生成 deterministic question candidates。
- 标记大表、空表、疑似 OCR 错位表、表头缺失表，作为 review warning 而非默认 blocking error。

验收标准：

- APOLLO 类产品目录 fixture 能识别 HTML table，而不是 `table_count=0`。
- `kb-build topology advise` 和 `query assistant-test-plan` 能消费表格 hints。

### 3.5 Ingest readiness / completeness report

新增正式入库准备度报告，作为 `quality_report.json` 的补充，而不是替代：

```text
ingest_readiness_report.json
```

建议 schema：`ragflow_doc_ingest_readiness_v1`。

报告维度：

- quality gate；
- local asset completeness；
- rich sidecar completeness；
- chunk marker readiness；
- retrieval hints richness；
- table/image artifact coverage；
- ragflow ingest plan completeness；
- redaction safety；
- recommended next command。

输出 advisory score，例如：

```text
ready
ready_with_review
blocked
```

验收标准：

- `ragflow-kb-build inspect-handoff` 可以读取并复核该报告。
- `blocked` 不应依赖主观 LLM 判断，只依赖确定性规则。

### 3.6 Formal handoff manifest 和包级 hash

新增或增强包级清单，补齐 RAGFlux thick package 的可复核体验：

```text
formal_handoff_manifest.json
```

建议 schema：`ragflow_formal_handoff_manifest_v1`。

记录：

- handoff mode；
- source document count；
- generated sidecars；
- Markdown 文件 hash；
- image asset hash；
- report hash；
- schema versions；
- downstream command suggestions。

验收标准：

- 不包含真实 endpoint、API key、私有源路径或临时路径。
- release hygiene 和 schema identity 覆盖该 schema。

### 3.7 Normalized RAGFlux comparison report

将本轮临时对比口径产品化为只读报告：

```text
ragflow-doc-to-md compare-retained-package
```

或作为 release/field-trial 工具中的独立报告。

报告应区分：

- retained package static comparison；
- replacement path live evidence；
- strict paired live A/B 是否实际执行。

比较指标：

- quality gate；
- Markdown chars/bytes/lines；
- normalized text similarity；
- image refs 和 local image files；
- chunk marker count；
- retrieval hints richness；
- sidecar completeness；
- table artifact count；
- live parse/query/cleanup evidence。

验收标准：

- 不把 RAGFlux 中间目录、layout PDF、span PDF、原始 PDF 重复算入 retained package。
- 默认不创建第二个 live KB；paired live A/B 必须另行显式批准。

### 3.8 Runtime performance telemetry

增强 runtime report 的性能口径：

- cold vs warm；
- 是否复用常驻 MinerU；
- 是否包含模型初始化；
- conversion、asset download、postprocess、package、hints、ingest plan 阶段耗时；
- image/table/OCR 慢路径 warning；
- task timeout 和 retry 分类。

验收标准：

- 用户能公平理解 `ragflow-doc-to-md` 和 RAGFlux 的耗时差异。
- 不把主机私有路径、endpoint 或 token 写入报告。

## 第四部分：开发任务清单

### 4.1 P0：正式入库模式可发现性和误用防护

实现状态：2026-07-03 已完成首个 P0 切片；仅增加离线 summary/report/advisory、文档和验收，
未执行 live RAGFlow mutation。

- [x] 定义 `handoff_mode` 字段，支持 `thin_preview` 和 `formal_ingest`。
- [x] 在普通 convert summary/runtime report 中写入 thin preview advisory。
- [x] 在 pipeline summary/runtime report 中写入 formal ingest readiness signals。
- [x] 更新 `package_readme.md`，明确下一步 kb-build inspect/dry-run 命令。
- [x] 更新 `ragflow-doc-to-md/SKILL.md` 和 host-agent prompt，要求正式入库默认使用 pipeline。
- [x] 增加 CLI tests：普通 convert 输出 advisory；pipeline 输出 formal mode。
- [x] 增加 consumer acceptance：host agent 能从 summary 判断正式 handoff 是否齐全。

### 4.2 P0：HTML table 识别和质量统计

实现状态：2026-07-03 已完成；仅增加离线 deterministic parser、report/hints 信号和测试，
未执行 live RAGFlow mutation。

- [x] 定义 HTML table deterministic parser helper，统计 `<table>`、行列估算、header preview。
- [x] 扩展 quality/runtime report，纳入 HTML table count。
- [x] 扩展 `retrieval_hints.json` 的 `table_artifacts`，支持 HTML table source。
- [x] 增加 APOLLO 类 HTML table fixture。
- [x] 增加 `kb-build topology advise` 和 assistant test plan 消费测试。

### 4.3 P1：Chunk boundary profile 体系

实现状态：2026-07-03 已完成；新增 profile/report、CLI sidecar、preferred boundary 和离线 fixture
验证，未执行 live RAGFlow mutation。

- [x] 定义 `chunk_profile_report.json` schema：`ragflow_chunk_profile_report_v1`。
- [x] 增加 `chunk-markers-dense` profile。
- [x] 增加 `chunk-markers-ragflux-like` profile。
- [x] 将 table/image/page/list boundary 纳入 preferred boundary 计算。
- [x] 增加 marker density warning：过密、过稀、连续 marker、空 section。
- [x] 增加离线 fixture：产品目录、论文、合同、长文档。
- [x] 增加 smoke comparison：不同 profile 下 marker 数、hints 数和 chunk profile report 稳定。

### 4.4 P1：图片语义 metadata

实现状态：2026-07-03 已完成；扩展 `artifact_index.json` 内嵌图片语义报告，并传递到
`retrieval_hints.json` 和 `assistant_test_plan.json`，未执行 live RAGFlow mutation。

- [x] 定义 `ragflow_asset_semantics_v1` 或扩展 `artifact_index.json`。
- [x] 从 Markdown image refs、artifact index、content_list、middle_json 合并图片语义。
- [x] 记录 page、kind、caption、source_heading、context、exists、sha256、bytes。
- [x] 增加 optional semantic alias map，但默认不改写 Markdown 主引用。
- [x] 将图片语义写入 retrieval hints 和 assistant test plan。
- [x] 增加 release hygiene 测试，确认不泄露远程 URL、原始路径或临时路径。

### 4.5 P1：Ingest readiness report

- [ ] 定义 `ragflow_doc_ingest_readiness_v1` schema。
- [ ] 生成 JSON-first `ingest_readiness_report.json`。
- [ ] Markdown 摘要只从 JSON 渲染，不含额外私有信息。
- [ ] 状态支持 `ready`、`ready_with_review`、`blocked`。
- [ ] 复用 quality gate、asset completeness、sidecar completeness、chunk readiness、hints richness。
- [ ] `ragflow-kb-build inspect-handoff` 读取并复核该报告。
- [ ] 增加 fake-client tests：ready、review、blocked 三类 fixture。

### 4.6 P2：Formal handoff manifest

- [ ] 定义 `ragflow_formal_handoff_manifest_v1` schema。
- [ ] 写出 sidecar list、schema versions、hashes、downstream command suggestions。
- [ ] 增加 schema identity 和 manifest schema check。
- [ ] 增加 consumer acceptance 和 strict-vendor platform smoke。
- [ ] 更新 public docs，说明它与 `doc_manifest.json` 的关系：前者是包级审计，后者是文档级 ingestion contract。

### 4.7 P2：Normalized comparison report

- [ ] 定义 `ragflow_handoff_comparison_v1` schema。
- [ ] 实现 retained package static comparison，不扫描中间目录。
- [ ] 计算 normalized text similarity：去除 chunk marker、空行、图片路径差异后比较正文。
- [ ] 输出 image、table、chunk marker、hints、sidecar completeness 对比。
- [ ] 明确标记 paired live A/B 是否执行。
- [ ] 增加 fixture：RAGFlux retained package vs pipeline handoff。
- [ ] 增加 redaction 测试，确认不写入私有路径。

### 4.8 P2：Runtime performance telemetry

- [ ] 扩展 `runtime_report.json` 的 stage timing。
- [ ] 区分 cold/warm、model init 是否包含、常驻 MinerU 是否复用。
- [ ] 记录 conversion、asset、postprocess、package、hints、ingest plan 阶段耗时。
- [ ] 增加 timeout/resource failure 分类字段。
- [ ] 增加 runtime report Markdown 摘要。
- [ ] 增加 fixture 和 CLI tests。

### 4.9 P3：多样本退役观察矩阵

- [ ] 定义多样本 field-trial summary schema。
- [ ] 覆盖扫描件、长文档、论文、合同、复杂表格、大量图片、低质量 OCR、多文档批量 handoff。
- [ ] 汇总 quality、asset、chunk、hints、dry-run、live parse、smoke/query、cleanup 指标。
- [ ] 仅使用显式 run roots；不默认扫描用户目录。
- [ ] 输出 sanitized JSON 和 Markdown summary。
- [ ] 将结果作为是否把 replacement path 提升为默认正式发布路径的证据。

## 第五部分：验收和发布门禁

### 5.1 离线门禁

每个实现切片至少通过：

```bash
python3 -m py_compile <changed-python-files>
python3 -m pytest <targeted-tests> -q
git diff --check
python3 tools/release_hygiene_check.py
```

涉及 schema、public CLI、release tooling 或 public skill 行为时，执行完整 release-facing chain：

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests -q
git diff --check
python3 tools/manifest_schema_check.py
python3 tools/release_hygiene_check.py
python3 tools/build_release.py --check
python3 tools/export_release_archives.py
python3 tools/consumer_acceptance.py --work-dir <fresh-acceptance-workdir> --overwrite
python3 tools/platform_smoke_matrix.py --profile strict-vendor-env --work-dir <fresh-platform-workdir>
```

### 5.2 Live 门禁

Live RAGFlow mutation 仍由 `ragflow-kb-build` 执行，并必须逐次得到用户明确批准。`ragflow-doc-to-md`
新增能力的默认验收应以离线 fixture、fake client、dry-run 和 sanitized field-trial summary 为主。

若需要 live E2E：

- 先确认正式 pipeline 产物 `ready`。
- 再通过 `ragflow-kb-build --dry-run`。
- 再执行一次性 KB live build / parse / smoke / query。
- 最后执行 cleanup 并记录脱敏结果。

### 5.3 退役判断

RAGFlux 退役不应只看单次样本。至少需要：

- 多样本文档矩阵覆盖常见高风险文档类型。
- 正式 pipeline 在主要样本上达到 quality `PASS` 或明确的 `ready_with_review`。
- 图片、表格、chunk marker、hints、ingest readiness、dry-run、live parse/query 无关键退化。
- paired live A/B 若被要求，必须单独批准并清理一次性 KB。

只有当这些证据稳定后，才能把 `ragflow-doc-to-md pipeline + ragflow-kb-build + ragflow-query`
从“候选 replacement path”提升为“默认正式发布路径”。
