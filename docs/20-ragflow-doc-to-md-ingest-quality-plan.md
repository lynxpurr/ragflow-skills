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
- 图片语义文件名 -> 对哈希/opaque 图片名生成稳定可读文件名，并在 metadata 中保留 hash 审计。
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

### 3.3 图片语义 metadata 和可读文件名

正式 handoff 不应把哈希值暴露为主要图片文件名。参考 RAGFlux 的 `--rename-images`
实践，当前实现应在不牺牲审计性的前提下，把哈希/opaque 图片名改写为稳定、可读、
可回归的本地文件名：

- 在转换写出 manifest 前，对 Markdown 中本地图片引用做 deterministic semantic rename；
  已经可读的 `chart.png`、`diagram.jpg` 等名称保持不变。
- 对哈希/opaque 文件名，优先使用图片 alt、同一行文本、附近标题和类型推断生成
  `image-001_<kind>_<slug>.<ext>` 风格名称，并处理重名碰撞。
- 在 `artifact_index.json` 或新的 asset semantics report 中记录页码、类型、alt/caption、附近标题、上下文片段。
- 区分 image、chart、table_image、logo、decorative、unknown 等可解释类型。
- 文件内容 hash 继续保存在 `doc_manifest.json`、`artifact_index.json` 和
  `formal_handoff_manifest.json` 中，作为审计和完整性校验依据，而不是作为人读文件名。
- 把图片语义信号传递给 `retrieval_hints.json` 和 assistant test plan。

验收标准：

- 没有页码或类型信息时保持兼容，不伪造精确信号。
- 有 `content_list` / `middle_json` 时优先使用结构化信号；没有结构化信号时使用 Markdown
  alt、同一行文本和附近标题作为 fallback。
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

实现状态：2026-07-03 已完成；`package --rich` 和 `pipeline` 默认写出
`ragflow_formal_handoff_manifest_v1` 为 `formal_handoff_manifest.json`，记录相对
sidecar inventory、schema/version identity、Markdown/image/report hash、包级 hash 和
inspect/dry-run command suggestions。`doc_manifest.json` 继续作为文档级 ingestion
contract，formal manifest 只作为包级审计和 handoff 完整性证据；未执行 live RAGFlow
mutation。

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

实现状态：2026-07-03 已完成；新增 `compare-retained-package` 只读 CLI 和
`ragflow_handoff_comparison_v1` JSON-first 报告，覆盖 retained package 静态比较、
normalized text similarity、image/table/chunk/hints/sidecar completeness、redaction
sidecar、consumer acceptance 和 strict-vendor platform smoke。该命令仅读取显式传入的
retained package 和 replacement handoff；默认 `paired_live_ab.status: not_run`，未执行
live RAGFlow mutation。

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

实现状态：2026-07-03 已完成；`ragflow_doc_runtime_report_v1` 兼容扩展
`performance` 区块，记录 conversion、asset、postprocess、package、hints 和 ingest plan
阶段 timing，区分 local MinerU CLI 冷启动进程与常驻 MinerU service 复用口径，标记
model init 未由 backend 汇报，并输出 timeout/resource failure 分类和 Markdown 摘要；未执行
live RAGFlow mutation。

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

### 4.4 P1：图片语义 metadata 和可读命名

实现状态：2026-07-03 已完成；扩展 `artifact_index.json` 内嵌图片语义报告，并传递到
`retrieval_hints.json` 和 `assistant_test_plan.json`，未执行 live RAGFlow mutation。

补充状态：2026-07-04 已完成；新增转换阶段 semantic image rename，对 Markdown 中的
哈希/opaque 本地图片文件名生成稳定可读名称并重写引用。`doc_manifest.json`、
`runtime_report.json.asset_policy`、`artifact_index.json`、`retrieval_hints.json` 和
`formal_handoff_manifest.json` 均指向最终可读文件名；sha256 继续作为审计字段保留。

- [x] 定义 `ragflow_asset_semantics_v1` 或扩展 `artifact_index.json`。
- [x] 从 Markdown image refs、artifact index、content_list、middle_json 合并图片语义。
- [x] 记录 page、kind、caption、source_heading、context、exists、sha256、bytes。
- [x] 对哈希/opaque 图片名执行 deterministic semantic rename，并同步 Markdown 主引用。
- [x] 将图片语义写入 retrieval hints 和 assistant test plan。
- [x] 增加 release hygiene 测试，确认不泄露远程 URL、原始路径或临时路径。
- [x] 增加 runtime 和 CLI 测试，确认 MinerU FastAPI 图片改名后 manifest/runtime 路径同步。

### 4.5 P1：Ingest readiness report

实现状态：2026-07-03 已完成；`package --rich` 和 `pipeline` 生成
`ragflow_doc_ingest_readiness_v1` JSON-first 报告及 Markdown 摘要，`inspect-handoff`
会读取 sidecar 并复算状态；未执行 live RAGFlow mutation。

- [x] 定义 `ragflow_doc_ingest_readiness_v1` schema。
- [x] 生成 JSON-first `ingest_readiness_report.json`。
- [x] Markdown 摘要只从 JSON 渲染，不含额外私有信息。
- [x] 状态支持 `ready`、`ready_with_review`、`blocked`。
- [x] 复用 quality gate、asset completeness、sidecar completeness、chunk readiness、hints richness。
- [x] `ragflow-kb-build inspect-handoff` 读取并复核该报告。
- [x] 增加 fake-client tests：ready、review、blocked 三类 fixture。

### 4.6 P2：Formal handoff manifest

实现状态：2026-07-03 已完成；新增 public schema template/example、runtime 生成器、
CLI 默认输出、`inspect-handoff` 摘要、consumer acceptance 和 strict-vendor platform
smoke 覆盖；未执行 live RAGFlow mutation。

- [x] 定义 `ragflow_formal_handoff_manifest_v1` schema。
- [x] 写出 sidecar list、schema versions、hashes、downstream command suggestions。
- [x] 增加 schema identity 和 manifest schema check。
- [x] 增加 consumer acceptance 和 strict-vendor platform smoke。
- [x] 更新 public docs，说明它与 `doc_manifest.json` 的关系：前者是包级审计，后者是文档级 ingestion contract。

### 4.7 P2：Normalized comparison report

- [x] 定义 `ragflow_handoff_comparison_v1` schema。
- [x] 实现 retained package static comparison，不扫描中间目录。
- [x] 计算 normalized text similarity：去除 chunk marker、空行、图片路径差异后比较正文。
- [x] 输出 image、table、chunk marker、hints、sidecar completeness 对比。
- [x] 明确标记 paired live A/B 是否执行。
- [x] 增加 fixture：RAGFlux retained package vs pipeline handoff。
- [x] 增加 redaction 测试，确认不写入私有路径。

### 4.8 P2：Runtime performance telemetry

- [x] 扩展 `runtime_report.json` 的 stage timing。
- [x] 区分 cold/warm、model init 是否包含、常驻 MinerU 是否复用。
- [x] 记录 conversion、asset、postprocess、package、hints、ingest plan 阶段耗时。
- [x] 增加 timeout/resource failure 分类字段。
- [x] 增加 runtime report Markdown 摘要。
- [x] 增加 fixture 和 CLI tests。

### 4.9 P3：多样本退役观察矩阵

实现状态：2026-07-03 已完成；`tools/field_trial_metrics.py` 在既有显式 run-root
扫描上新增 `ragflow_retirement_observation_matrix_v1` 多样本退役观察矩阵，按
`ragflow_field_trial_record_v1.sample_types` 或同 run-root 记录归类样本，仅汇总已存在的
脱敏 JSON 报告，不触发 live RAGFlow mutation 或隐式目录扫描。

- [x] 定义多样本 field-trial summary schema。
- [x] 覆盖扫描件、长文档、论文、合同、复杂表格、大量图片、低质量 OCR、多文档批量 handoff。
- [x] 汇总 quality、asset、chunk、hints、dry-run、live parse、smoke/query、cleanup 指标。
- [x] 仅使用显式 run roots；不默认扫描用户目录。
- [x] 输出 sanitized JSON 和 Markdown summary。
- [x] 将结果作为是否把 replacement path 提升为默认正式发布路径的证据。

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

## 第六部分：2026-07-03 本轮优化收口总结

本轮围绕“正式入库准备质量”完成了 `ragflow-doc-to-md` 到 `ragflow-kb-build`、
`ragflow-query` 的离线 handoff 强化。实现重点不是复制旧包结构，而是把正式入库路径变成
可发现、可审计、可 dry-run、可对比、可观察的 replacement path。

### 6.1 已完成修改

- 正式入库模式可发现性：`convert` 默认标记 `handoff_mode: thin_preview` 并给出 advisory；
  `pipeline` 标记 `handoff_mode: formal_ingest`，并在 summary/runtime report 中暴露正式
  handoff readiness signals。
- KB 质量前置：新增 HTML table 统计、table artifact hints、chunk boundary profiles、
  marker density warnings、图片语义 metadata、assistant/query hint 传递。
- 入库准备审计：新增 `ragflow_doc_ingest_readiness_v1`，让 `package --rich`、`pipeline`
  和 `ragflow-kb-build inspect-handoff` 能复用同一 JSON-first readiness 判断。
- 包级可复核性：新增 `ragflow_formal_handoff_manifest_v1`，记录 sidecar、schema versions、
  hashes 和 downstream command suggestions；`doc_manifest.json` 继续作为文档级 ingestion
  contract。
- Retained package 对比：新增 `ragflow_handoff_comparison_v1`，进行静态、脱敏、normalized
  comparison，并明确标记 paired live A/B 是否执行。
- Runtime 性能口径：`ragflow_doc_runtime_report_v1` 增加 `performance` 区块，记录 conversion、
  asset、postprocess、package、hints、ingest plan 等阶段耗时，区分 local CLI 冷启动和常驻
  service 复用，并保留 timeout/resource failure 分类。
- 多样本退役观察：`tools/field_trial_metrics.py` 新增
  `ragflow_retirement_observation_matrix_v1`，仅从显式 run roots 汇总 scanned、long
  document、paper、contract、complex table、image heavy、low-quality OCR、multi-document
  handoff 等样本证据。
- Release gate 补强：field-trial metrics 和 retirement matrix schema identity 已纳入
  release hygiene 路径，防止后续报告 schema 静默漂移。

### 6.2 需要持续观察的项目

- 多样本覆盖是否充分：当前代表样本不能替代广泛语料结论，后续应继续积累扫描件、长文档、
  论文、合同、复杂表格、大量图片、低质量 OCR 和多文档 handoff 证据。
- Chunk marker 密度：代表样本中 retained package 的 marker 更密，新 pipeline 的 live parse
  和 smoke/query 已通过；后续应观察 marker 稀疏是否导致检索召回或 citation 稳定性下降。
- 图片和表格语义：持续检查 local asset 落地、caption/context/page 归属、HTML table artifact
  和 retrieval hints 是否能被 downstream profile、assistant test plan 和 query 侧有效消费。
- Readiness 与实际 parse/query 的一致性：`ready` 或 `ready_with_review` 应持续对照 dry-run、
  live parse chunk 数、smoke/query 和 citation audit 结果，避免 readiness 过度乐观。
- 性能口径稳定性：区分 local MinerU CLI cold process、persistent service reuse、backend 未汇报
  model init 的情况，避免把不同运行形态的耗时直接比较。
- 安全边界：field-trial summary 只能记录脱敏指标、artifact 名称和 failure class，不写 endpoint、
  token、dataset/document id、KB name、私有路径或 raw chunks。
- Release health：每次 public schema、CLI summary、report surface 或 release artifact 变化后，
  保持 schema identity、manifest schema、release hygiene、consumer acceptance 和 strict-vendor
  platform smoke 绿色。

### 6.3 后续开发工作汇总

- 默认后续方向是 field-trial observation 和 release-path maintenance，不是直接开启新产品 surface。
- 若至少三个真实 host-agent run 证明一次性 CLI handoff 成为瓶颈，再从 Phase 37.2 设计门禁进入
  `ragflow-query serve`：localhost 绑定、生命周期、health/direct/host-assisted/shutdown schema、
  auth boundary、redacted logs 和 fake-client smoke 必须先定义。
- 若真实 converter/provider/product 合同出现，再进入 remote conversion client、provider
  abstraction、reranker adapter 或 web/API wrapper；必须先具备 endpoint/auth/error model、fake
  fixtures 和 acceptance criteria，不允许默认私有 endpoint。
- Optional script-owned LLM/RAGAS backend 仍保持 deferred；只有在 explicit LLM config、
  deterministic fixtures、advisory-output marking、citation-audit compatibility、redaction 和 release
  gates 同时满足后才能开发。
- Private bridge 仍留在 public release artifacts 之外；只有当 Markdown passthrough 到
  `doc_manifest.json` 被真实私有 workflow 证明不足时，才在 public `skills/` 外开发。
- Paired live A/B 或新的 live RAGFlow mutation 需要单独明确批准、一次性资源、cleanup 记录和脱敏
  evidence；普通继续开发请求不自动打开 live gate。

### 6.4 2026-07-04 图片可读命名补充

本次补充来自最新实践体验：代表性 MinerU FastAPI pipeline 虽然已经能正确落地本地图片资产，
但 Markdown 和 handoff 目录中的图片文件名仍可能是长哈希值。这样的文件名适合内容寻址，却不适合
用户检查、host-agent 复核、RAGFlux retained package 对比或后续问题定位。因此本轮参考 RAGFlux
`--rename-images` 的用户体验，将“图片语义 metadata / alias”推进为“正式 handoff 中优先使用可读
图片文件名”。

已完成的行为变化：

- 新增转换阶段 semantic image rename，在写出 `doc_manifest.json`、quality report 和 rich sidecars
  之前执行，确保后续所有 manifest/report 都引用最终文件名。
- 仅对哈希/opaque 本地图片文件名改名；已经可读的 `chart.png`、`diagram.jpg` 等名称保持不变，
  以降低兼容性扰动。
- 可读名基于 Markdown alt、同一行上下文、附近标题和 deterministic kind 推断生成，当前风格为
  `image-001_<kind>_<slug>.<ext>`，并对同目录碰撞做稳定后缀处理。
- Markdown 主引用会同步改写；`runtime_report.json.asset_policy.saved.image_paths`、
  `runtime_report.json.asset_policy.saved.image_assets[]` 和 `doc_manifest.json.documents[].assets.images[]`
  也同步指向可读文件名。
- sha256 仍保留在 `doc_manifest.json`、`artifact_index.json` 和
  `formal_handoff_manifest.json` 中，作为完整性校验和审计依据；不再把 hash 本身作为正式 handoff
  的主要人读文件名。
- public skill 文案、host-agent setup、user onboarding prompt 和 RAGFlux parity plan 已同步说明
  该命名策略，避免后续 agent 误判“没有 hash 文件名”等同于“缺少 provenance”。

验证覆盖：

- Runtime 单测覆盖哈希图片名改写、重复引用同步改写、可读文件名保持不变。
- CLI fake MinerU FastAPI 测试覆盖 `markdown_assets` 下 base64 图片落地、Markdown 引用改写、
  `doc_manifest.json` 和 `runtime_report.json.asset_policy` 路径同步。
- 回归验证已覆盖 `test_doc_convert.py`、`test_doc_convert_cli.py`、`test_handoff.py` 和
  `test_kb_build_cli.py`；同时通过 `git diff --check` 和 release hygiene。
- 本轮未执行 live RAGFlow mutation；该能力属于正式 handoff 生成阶段的离线可复核改进。

后续持续观察：

- 真实中文 PDF 中，若同一行上下文过长或标题本身较差，可读名可能仍偏泛化；后续可在
  structured assets 稳定后优先使用 `content_list` / `middle_json` 的 page、block type、caption
  和 image source signal 来进一步接近 RAGFlux 的 `p001_<subtype>_<description>_<short-id>` 风格。
- 当前策略只改哈希/opaque 名，避免对用户已有可读资产名做不必要重写；如果后续 field-trial 证明
  某些非哈希但低语义名称也影响排查，可增加 opt-in rename profile，而不改变默认兼容策略。
- 应继续观察 `artifact_index.json.asset_semantics.semantic_aliases` 与实际文件名的关系，避免 alias
  字段和主路径在后续迭代中表达重复或冲突。
