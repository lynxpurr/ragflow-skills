---
doc_type: spec
topic: doc-to-md-table-quality
status: historical
created: 2026-07-04
updated: 2026-08-03
canonical: false
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
archived: 2026-08-03
historical_reason: completed
original_sha256: bf9762763577348b27b09f8932ae1ddc36d7f112cfe293085dc298654888be20
---

> **Historical archive:** This document is immutable context and creates no current task,
> implementation, operational, network, credential, mutation, or live authority.

# 21. ragflow-doc-to-md 表格质量优化设计

状态：P0/P1/P2 已实现并通过离线验证；APOLLO high-accuracy 只读回归已完成；
RAGFlow live 入库和 KB 侧 zip 上传仍需单独批准/设计
日期：2026-07-04
适用范围：让 Hermes/OpenClaw 等 host agent 使用 `ragflow-doc-to-md` 处理含复杂表格的
PDF/Office/图片文档时，稳定产出高质量、可入库、表格不被切散的 Markdown handoff。

## 1. 结论摘要

本轮 APOLLO 数据页对照说明，表格质量问题不是单一原因：

- 上游表格结构识别由 MinerU backend 决定。当前 `mineru-fastapi` 路径固定发送
  `backend=pipeline`，即使服务已预加载 VLM，也不会使用 high-accuracy hybrid/VLM 路径。
- 下游 `chunk-markers` 也确实可能改坏表格：它把 OCR 空格清理应用到整篇 Markdown，
  会清理 HTML table 内部空格，使表格文本退化。`chunk-markers-dense` 不触发这组 OCR
  清理，且会在 HTML table 前插入 table boundary marker。
- 表格是否被 RAGFlow 切散，取决于 handoff marker 与 RAGFlow parser profile 是否配套。
  需要使用 `chunk-markers-dense`，并把 RAGFlow `delimiter` 设置为反引号包裹的
  `` `<!-- chunk -->` ``，同时不要设置 `children_delimiter`。

因此需要代码层更新，但应分层推进：先保证后处理不破坏 HTML table，再给
`mineru-fastapi` 增加 high-accuracy backend 透传，最后用质量门和 profile 建议让 Hermes
自动选择正确路径。MinerU v4 platform 是独立 backend：同一个 `--table-quality high`
在 v4 中映射到 `model_version=vlm`，不是 FastAPI 的 high-accuracy backend。

## 2. 目标和非目标

目标：

- 表格丰富文档默认能走到“高质量可选路径”，而不是被固定在 `pipeline`。
- HTML table 在 postprocess、chunk marker 插入、rich package 生成过程中保持原子性。
- Hermes 能从报告中判断是否应使用 high-accuracy backend、是否存在表格退化、以及下一步
  RAGFlow parser profile 应如何配置。
- RAGFlow 入库后，复杂表格尽量落在同一父段落/父 chunk 中，不被 `children_delimiter`
  切散。

非目标：

- 不在 `ragflow-doc-to-md` 中直接创建或修改 RAGFlow KB。
- 不默认把所有文档全局切到 hybrid/VLM backend；高精度路径有 GPU、耗时和服务兼容性成本。
- 不用 LLM 重写表格、补齐表格或生成主观 QA。
- 不把私有本地路径、真实 endpoint、API key 或临时运行目录写入 public handoff。

## 2.1 当前实现进展

2026-07-04 首轮开发已完成以下离线可测改动，并通过 runtime 与 release-facing 验证：

- `ocr` 和 `chunk-markers` 的 OCR cleanup 已跳过 HTML table 和 Markdown pipe table block。
- `postprocess_report.json` 已增加每篇文档的 `table_integrity` 摘要和汇总计数。
- `pipeline` 的正式 handoff 默认 profile 已切到 `chunk-markers-dense`；旧 `chunk-markers`
  仍保留为显式兼容 alias。
- `mineru-fastapi` 已支持 `--mineru-fastapi-backend`、`MINERU_FASTAPI_BACKEND`、
  `mineru.fastapi_backend`，以及 `--mineru-fastapi-server-url`/`server_url` 透传。
- `hybrid-engine` / `vlm-engine` 会映射到当前本地 FastAPI 兼容的
  `hybrid-auto-engine` / `vlm-auto-engine`。
- `delimiter` 已加入 profile parser_config 白名单，`` `<!-- chunk -->` `` 不再触发
  unsupported parser key warning。
- 已验证 focused tests、全量 runtime tests、release hygiene、release archive export、consumer
  acceptance 和 strict vendor platform smoke。
- `--table-quality standard|high|auto` 已实现：`standard` 保持兼容，`high` 强制选择
  high-accuracy FastAPI backend，`auto` 会对 PDF/Office/图片 formal candidates 自动提升。
- 2026-07-06 MinerU v4 platform 后端已实现；`--table-quality high` 在
  `mineru-v4` / `mineru-platform` 上选择 `mineru_v4_model_version=vlm`，显式
  `MinerU-HTML` 会被保留并写入 review warning。
- `--allow-table-quality-fallback` 已实现；backend unsupported 会按策略降级到 `pipeline`，
  资源/timeout 等失败只有显式允许时才降级，并在 runtime/quality report 中标记
  `table_quality_degraded`。
- `profile_suggestions.json` 已在检测到表格时额外生成 `table-atomic-*-4096` 建议，包含
  `chunk-markers-dense`、外层带反引号的 `<!-- chunk -->` delimiter、`chunk_token_num: 4096`、
  `chunk_overlap: 0` 和 `avoid_children_delimiter: true`。
- `ragflow-kb-build inspect-handoff` 已从 `quality_report.json.documents[].quality_signals`
  读取 HTML table 统计，避免 readiness / artifact coverage 侧漏报表格。
- `quality_report.json.documents[].quality_signals` 已补齐 `table_source_counts`、
  `table_fingerprints`、`chunk_marker_table_atomicity` 和 `table_heavy_document`；
  `postprocess_report.json.documents[].table_integrity` 已补齐 `postprocess_table_delta`。
  host agent 可以直接判断表格来源、结构复杂度、marker 是否切进表格，以及是否需要人工复核。
- APOLLO high-accuracy 只读回归已跑通：`--table-quality high` 选择
  `hybrid-auto-engine`，无 fallback；6 个 HTML table、6 个 table artifacts、33 个 chunk
  markers、0 个 table integrity issue、0 个缺失图片资产，`inspect-handoff` 和 dry-run 均通过。

未执行：RAGFlow live KB 创建/解析/查询。KB 侧“Markdown + local images 打包上传”为
`ragflow-kb-build` 的单独 live mutation 设计问题；MinerU 返回 zip/base64/URL 图片资产落地已由
`markdown_assets` 路径和离线 fixture 覆盖，不再作为本表格质量主线的未完成项。

## 3. 外部资料校准

联网核对后的可用结论：

- MinerU 官方 CLI 文档显示 `mineru` 支持 `--api-url` 复用已有 FastAPI 服务，`--backend`
  支持 `pipeline`、VLM、hybrid 以及 http-client 类后端；`--table` 默认开启，
  `--image-analysis` 面向 VLM/hybrid 后端，hybrid 的 medium effort 会自动关闭 image/chart
  analysis，高精度场景可使用 high effort。
- MinerU README 把 `pipeline` 定位为快且稳定，hybrid/VLM 定位为高精度；同时说明 MinerU
  会把表格转换为 HTML，并支持复杂布局、跨页表格等结构化解析能力。
- RAGFlow 官方 dataset 文档强调 chunking method 会影响语义完整性；child chunking 官方文档
  说明 parent-child 模式会把父 chunk 再切成 child chunks 用于召回。
- Unstructured 的 PDF 表格抽取示例也采用 layout-aware/hi-res 策略，并读取
  `metadata.text_as_html`。这与本项目的原则一致：复杂表格应优先保留 HTML 结构，而不是在
  后处理阶段把它压成普通文本。

参考链接：

- MinerU CLI usage: https://opendatalab.github.io/MinerU/usage/cli_tools/
- MinerU README: https://github.com/opendatalab/MinerU
- RAGFlow configure knowledge base: https://ragflow.io/docs/dev/configure_knowledge_base
- RAGFlow child chunking: https://ragflow.io/docs/dev/configure_child_chunking_strategy
- Unstructured PDF table extraction: https://docs.unstructured.io/examplecode/codesamples/apioss/table-extraction-from-pdf

注意：MinerU 新版公开文档使用 `hybrid-engine` / `vlm-engine` 命名；当前本地 8888 FastAPI
OpenAPI 使用 `hybrid-auto-engine` / `vlm-auto-engine`。实现时需要做兼容映射，而不是只接受
某一代命名。

## 4. 本地证据

本地 APOLLO 样本使用同一份 PDF，结论如下：

- retained RAGFlux、本地 GitHub 原始代码和 `ragflux run --mode fast` 的 raw Markdown
  表格输出一致；`lynxpurr/ragflux` 源码漂移不是根因。
- `ragflow-doc-to-md pipeline --backend mineru-fastapi --postprocess-profile chunk-markers`
  表格行数和 table-line hash 与 raw 输出不同，原因是 `chunk-markers` 触发 OCR 空格清理。
- `safe` 和 `chunk-markers-dense` 保持 raw table-line hash 不变；`chunk-markers-dense`
  还在 APOLLO 中插入 6 个 table boundary marker，且 6 个表格均保持在单一 marker 段内。
- 当前 `mineru_fastapi_convert()` 固定发送：

```text
backend = pipeline
parse_method = ocr 或 auto
table_enable = enable_table
image_analysis = true
```

- 复用已有 MinerU FastAPI 服务执行 `hybrid-auto-engine` 后，APOLLO 的 6 个 HTML table
  数量不变，但结构明显改善：表头分层更合理，温度符号从 `18℃ -22°℃` 改为
  `18°C-22°C`，大尺寸/重量表的列标题被展开而不是压扁成一行。
- 该 hybrid 实测无 OOM，约 14 秒完成，GPU 显存增加约 500 MiB。此前直接本地启动
  accurate/VLM 类路径曾因空闲显存不足失败，所以推荐优先复用已预加载的 FastAPI 服务。
- 通过 `ragflow-doc-to-md pipeline --table-quality high --postprocess-profile
  chunk-markers-dense` 的完整只读回归后，runtime 记录 high-accuracy backend 成功、无降级；
  postprocess 前后 6 个 HTML table fingerprint 不变，marker 未进入 table block；rich handoff
  生成 6 个 table artifacts、24 个 image artifacts 和 table-aware profile suggestion。

## 5. 根因模型

### 5.1 表格结构质量

复杂表格的 `rowspan`、`colspan`、多级表头、单位、温度符号和跨列关系，主要由 MinerU
上游解析决定。后处理只能保护和统计表格，不能凭空恢复被 `pipeline` 压扁的表头。

### 5.2 表格文本退化

`doc_postprocess.py` 中 `ocr` 与 `chunk-markers` 会应用：

- `_remove_cjk_inner_spaces`
- `_fix_ocr_punctuation_spacing`
- `_normalize_ocr_ligatures`

这些规则对普通 OCR 段落有价值，但不能直接作用在 HTML table 原文上。HTML table 内部空格、
公式空格、单位空格和表头视觉分隔可能是结构表达的一部分。

### 5.3 表格被切散

RAGFlow 本地实现从 `delimiter` 中提取反引号包裹的自定义 delimiter。也就是说 profile 里的
值应为：

```json
{
  "delimiter": "`<!-- chunk -->`"
}
```

而不是 `"<!-- chunk -->"`。如果配置了 `children_delimiter`，RAGFlow parent-child chunking
会继续对子 chunk 做二次切分。对复杂表格优先保证表格原子性时，应不设置
`children_delimiter`。

## 6. 更新方案

### P0：表格安全后处理

实现方向：

- 给 OCR cleanup 增加 HTML table protected spans。`ocr` 和 `chunk-markers` 可以继续清理普通
  段落，但必须跳过 `<table>...</table>` 块。
- 对 Markdown pipe table 也应谨慎处理：至少跳过连续 pipe table 行；复杂时以 block scanner
  标记保护区，而不是对整篇文本做正则替换。
- 在 `postprocess_report.json` 增加 `table_integrity` 摘要：
  - raw/postprocess HTML table count；
  - table fingerprint 是否变化；
  - marker 是否出现在 `<table>` 与 `</table>` 内部；
  - 是否存在 unbalanced table fragment。
- 把 `chunk-markers` 继续保留为兼容 alias，但正式含表格文档推荐 `chunk-markers-dense`。

验收：

- 旧的 `chunk-markers` 在含 HTML table fixture 上不再改变 table fingerprint。
- `chunk-markers-dense` 仍在表格前插入 boundary，不在表格内部插入 marker。
- APOLLO fixture 的 6 个 HTML table 在 postprocess 前后数量和 fingerprint 保持一致。

### P0：Hermes 引导与 profile 建议修正

需要修正所有 host-agent 指引中的正式入库推荐：

```bash
python scripts/convert.py pipeline \
  --input ./raw \
  --output ./handoff \
  --backend mineru-fastapi \
  --mineru-base-url https://mineru.example.internal \
  --mineru-asset-mode markdown_assets \
  --postprocess-profile chunk-markers-dense
```

RAGFlow profile 建议必须使用：

```json
{
  "chunk_method": "naive",
  "parser_config": {
    "chunk_token_num": 4096,
    "delimiter": "`<!-- chunk -->`",
    "auto_keywords": 0,
    "auto_questions": 0,
    "__language__": "Chinese"
  }
}
```

不要在表格原子性优先的 profile 中设置 `children_delimiter`。`chunk_token_num` 在 RAGFlow
版本支持时建议不低于 4096；如果当前部署把上限限制为 2048，则先使用 2048，并在
`retrieval_hints.table_artifacts` 提示存在超大表时标记人工复核或服务端升级需求。对特别大的
表格，2048 仍可能触发二次切分，无法仅靠 delimiter 完全保证原子性。

### P1：MinerU FastAPI high-accuracy backend 透传

新增参数和配置：

- CLI：`--mineru-fastapi-backend`
- env：`MINERU_FASTAPI_BACKEND`
- config：`mineru.fastapi_backend`
- CLI：`--mineru-fastapi-server-url`
- env：`MINERU_FASTAPI_SERVER_URL`
- config：`mineru.fastapi_server_url`

默认值保持 `pipeline`，以免破坏现有低资源环境。允许值建议：

```text
pipeline
hybrid-auto-engine
vlm-auto-engine
hybrid-http-client
vlm-http-client
hybrid-engine
vlm-engine
```

兼容映射建议：

| 用户输入 | FastAPI form backend |
| --- | --- |
| `pipeline` | `pipeline` |
| `hybrid-auto-engine` | `hybrid-auto-engine` |
| `vlm-auto-engine` | `vlm-auto-engine` |
| `hybrid-engine` | 优先按服务 OpenAPI 支持情况映射为 `hybrid-auto-engine`，否则原样发送 |
| `vlm-engine` | 优先按服务 OpenAPI 支持情况映射为 `vlm-auto-engine`，否则原样发送 |
| `hybrid-http-client` | `hybrid-http-client`，并透传 `server_url` |
| `vlm-http-client` | `vlm-http-client`，并透传 `server_url` |

`mineru_fastapi_convert()` 表单字段改为：

```text
backend = resolved_mineru_fastapi_backend
server_url = mineru_fastapi_server_url  # only when provided
parse_method = ocr 或 auto
table_enable = enable_table
image_analysis = true
```

runtime report 应记录：

- requested backend；
- resolved backend；
- 是否提供 server_url，并进行 endpoint redaction；
- FastAPI OpenAPI 是否可探测到 backend 字段；
- task 失败时是否疑似 OOM、backend unsupported 或 upstream 5xx；
- high-accuracy fallback 是否发生。

### P1：表格质量门和回归报告

新增确定性质量信号：

- `table_source_counts`：HTML table、Markdown table、content-list table 数量。
- `table_fingerprints`：每个 HTML table 的规范化 hash、行数、cell 数、`rowspan`/`colspan`
  计数、caption preview。
- `postprocess_table_delta`：postprocess 前后 table count/hash/cell count 是否变化。
- `chunk_marker_table_atomicity`：按 `` `<!-- chunk -->` `` split 后是否存在不完整
  `<table>` fragment。
- `table_heavy_document`：表格数量、最大 cell 数、表格字符占比达到阈值时置 true。

这些信号应进入 `quality_report.json` 或 `ingest_readiness_report.json`，并在
`runtime_report.json` 摘要中露出足够信息，让 Hermes 无需人工打开 Markdown 也能判断风险。

实现状态：`quality_report.json` 已输出 HTML/Markdown/content-list table 来源计数、
HTML table fingerprint、行/列/cell/rowspan/colspan/caption 摘要、chunk marker table
atomicity 和 `table_heavy_document`；`postprocess_report.json` 已输出 `postprocess_table_delta`、
table fingerprint delta 和 marker-in-table 检查；`runtime_report.json` 已汇总 quality table counts；
`inspect-handoff` / readiness 已读取这些计数并与 `retrieval_hints.json.table_artifacts`
做 coverage 对齐。

### P1：完整 pipeline 推荐命令

Hermes 面对“有复杂表格、规格参数、产品目录、财报、扫描件表格”的文档时，推荐命令应升级为：

```bash
python scripts/convert.py pipeline \
  --input /path/to/input.pdf \
  --output /path/to/handoff \
  --backend mineru-fastapi \
  --mineru-base-url http://mineru.example.internal \
  --table-quality high \
  --mineru-asset-mode markdown_assets \
  --postprocess-profile chunk-markers-dense \
  --json
```

如果只希望 formal PDF/Office/图片候选自动提升，可使用：

```bash
--table-quality auto
```

若使用远端 OpenAI-compatible VLM/hybrid 服务：

```bash
--mineru-fastapi-backend hybrid-http-client \
--mineru-fastapi-server-url https://vlm.example.internal/v1
```

### P2：自动策略和 fallback

`--table-quality` 可选策略，默认仍为 `standard`：

```text
standard  保持兼容，使用 pipeline
high      强制使用 high-accuracy backend，失败则失败
auto      基于文档/用户意图/服务能力选择 high-accuracy；资源失败时可按策略 fallback
```

`auto` 触发条件：

- 用户明确要求“高质量表格”“复杂表格”“正确对齐”。
- 输入为 PDF/图片，初步检测存在多表格页、规格参数页或大量数字单位。
- 上一次同文档 pipeline 输出出现 table warning。
- `retrieval_hints.table_artifacts` 或 content-list 显示存在 `complex_table`。

fallback 原则：

- high-accuracy backend unsupported：可回退 `pipeline`，但必须在报告中标记
  `table_quality_degraded=true`。
- OOM/资源不足：默认失败并给出复用预加载 FastAPI 或远端 http-client 的建议；只有显式
  `--allow-table-quality-fallback` 才回退。
- fallback 后仍必须使用 table-safe postprocess 和 `chunk-markers-dense`。

实现状态：

- CLI/config/env 已支持 `--table-quality` / `DOC_TO_MD_TABLE_QUALITY` / `doc_to_md.table_quality`。
- CLI/config/env 已支持 `--allow-table-quality-fallback` /
  `DOC_TO_MD_ALLOW_TABLE_QUALITY_FALLBACK` / `doc_to_md.allow_table_quality_fallback`。
- runtime context 会记录 table-quality mode、auto trigger、fallback count、degraded 标记和
  fallback events；fallback 后的文档 warnings 会带 `table_quality_degraded`。

## 7. RAGFlow 入库配套

推荐 profile：

```json
{
  "profile_id": "zh-table-atomic-4096",
  "chunk_method": "naive",
  "chunk_size": 4096,
  "chunk_overlap": 0,
  "parser_config": {
    "chunk_token_num": 4096,
    "delimiter": "`<!-- chunk -->`",
    "auto_keywords": 0,
    "auto_questions": 0,
    "__language__": "Chinese"
  }
}
```

操作原则：

- 上传 `ragflow-doc-to-md` 生成的 Markdown handoff，而不是让 RAGFlow 重新解析原始 PDF。
- 使用 `delimiter` 命中 `chunk-markers-dense` 生成的 marker。
- 不设置 `children_delimiter`，避免复杂表格被二次切分。
- 优先查看 `profile_suggestions.json` 中的 `table-atomic-*-4096`，它会给出可直接复核的
  parser_config 建议。
- `chunk_token_num` 不要过小；如果部署支持 4096 或更高，表格文档优先使用较大父段。若部署
  只允许 2048，仍可使用 marker 保护普通表格，但超大表格需要服务端上限调整、升级或上游逻辑拆表。
- `auto_keywords` 和 `auto_questions` 默认为 0；表格问答候选应优先来自
  `retrieval_hints.json` 和后续 offline review，而不是入库时额外 LLM 扩写。

## 8. Hermes 决策规则

Hermes 使用此 skill 时建议按以下顺序决策：

1. 如果用户只是要快速预览 Markdown，用默认 thin convert。
2. 如果用户要正式入库或后续 RAGFlow KB 构建，使用 `pipeline`、`markdown_assets`、
   `chunk-markers-dense`。
3. 如果文档含表格，优先选择 `--table-quality high`；需要由 host 判断候选文档时使用
   `--table-quality auto`，并复用已有 FastAPI 服务。
4. 如果 high-accuracy backend 失败，先查看 runtime report 的 failure category：
   backend unsupported、OOM、timeout、upstream 5xx 分别给出不同建议。
5. 生成后检查 `ingest_readiness_report.json`、`postprocess_report.json`、
   `retrieval_hints.json.table_artifacts` 和 `chunk_profile_report.json`。
6. 入库前把 RAGFlow profile 设置为 `` delimiter: "`<!-- chunk -->`" ``，不设置
   `children_delimiter`。

## 9. 验收计划

离线单元测试：

- `test_doc_postprocess.py`：HTML table protected spans、pipe table protected spans、
  marker 不进入 table block。
- `test_doc_convert.py`：`mineru_fastapi_convert()` 默认发送 `pipeline`；显式 high backend
  会透传；`server_url` 只在提供时发送；runtime attempt 会记录 requested/resolved backend。
- `test_doc_convert_cli.py`：CLI 参数、env、config 优先级和 redaction。
- `test_profiles.py`：允许 `delimiter` 作为 parser_config 字段，并校验推荐值带反引号。

离线回归 fixture：

- APOLLO sanitized fixture：6 个 HTML table，`chunk-markers-dense` postprocess 后 table
  fingerprint 不变，table marker 数为 6。
- fake FastAPI fixture：分别模拟 `pipeline`、`hybrid-auto-engine`、unsupported backend、
  OOM 和 timeout。

可选 live 验证：

```bash
python scripts/convert.py pipeline \
  --input /path/to/apollo.pdf \
  --output /path/to/handoff \
  --backend mineru-fastapi \
  --mineru-base-url http://mineru.example.internal \
  --table-quality high \
  --mineru-asset-mode markdown_assets \
  --postprocess-profile chunk-markers-dense \
  --json
```

验收标准：

- 输出 Markdown 中 6 个 HTML table 存在，且 postprocess 前后 fingerprint 不变。
- `retrieval_hints.json.table_artifacts` 至少包含 6 个 HTML table artifact。
- `chunk_profile_report.json` 显示 table boundary marker 与表格数量一致。
- RAGFlow delimiter 模拟 split 后不存在 unbalanced table fragment。
- runtime report 明确记录 `mineru_fastapi_backend=hybrid-auto-engine`。

## 10. 实施顺序

1. P0 修复 postprocess 表格保护，并修正文档/host-agent prompt 默认推荐为
   `chunk-markers-dense`。
2. P1 增加 `--mineru-fastapi-backend` 与 `--mineru-fastapi-server-url` 透传，默认保持
   `pipeline`。
3. P1 增加 table fingerprint、atomicity check 和 high-accuracy runtime report 字段。
4. 用 APOLLO 样本跑完整 pipeline 对比，生成脱敏回归记录。已完成 high-accuracy 只读回归；
   未执行 RAGFlow live mutation。
5. P2 已实现 `--table-quality auto|high|standard` 和 fallback 策略。

这条路线能同时满足三件事：Hermes 有 chunk markers 辅助生成段落，复杂表格能优先走
high-accuracy 解析，表格在 RAGFlow chunking 中保持原子性。

## 11. 本轮优化完成总结

本轮优化已经把表格质量问题从“经验性操作建议”推进为可配置、可观测、可验证的
`ragflow-doc-to-md` 正式能力：

- 后处理链路已 table-safe：OCR 空格清理会跳过 HTML table 和 Markdown pipe table；
  `chunk-markers-dense` 会插入表格边界 marker，但不会把 marker 写进 `<table>` 内部。
- MinerU FastAPI 路径已不再固定 `pipeline`：CLI、env、config 均可设置
  `mineru_fastapi_backend` 和 `mineru_fastapi_server_url`，并兼容新旧 hybrid/VLM backend 命名。
- `--table-quality standard|high|auto` 已成为 host agent 的正式决策入口：
  `standard` 保持兼容，`high` 走 high-accuracy backend，`auto` 对正式 PDF/Office/图片候选自动提升。
- fallback 行为已显式化：unsupported backend 可降级到 `pipeline`，资源/timeout 类失败只有显式允许时
  才降级；所有降级都会写入 runtime/table-quality 报告并标记 `table_quality_degraded`。
- 表格质量信号已补齐到报告层：`quality_report.json` 现在包含 `table_source_counts`、
  `table_fingerprints`、`chunk_marker_table_atomicity`、`table_heavy_document`；
  `postprocess_report.json` 包含 `postprocess_table_delta` 和 table integrity 汇总。
- rich handoff 已能给出 table-aware profile suggestion：检测到表格时会生成
  `table-atomic-*-4096` 建议，包含 `chunk-markers-dense`、带反引号的 `<!-- chunk -->`
  delimiter、较大的父 chunk、零 overlap 和 `avoid_children_delimiter: true`。
- `ragflow-kb-build inspect-handoff` 已能读取 quality report 中的 HTML/Markdown table 计数，
  并与 `retrieval_hints.json.table_artifacts` 做覆盖对齐，避免下游漏判表格文档。
- release 工具链已把 public release surface 和本地开发输入分开：skill-local `doc/` 目录可保留
  下一轮分析输入，但不会进入 release archive、hygiene scan 或 rename governance 的发布面判断。
- 本轮收尾已通过完整 release-facing validation chain：runtime tests、diff check、manifest schema、
  release hygiene、release build、archive export、consumer acceptance 和 strict vendor platform smoke。

实际使用上，Hermes 面对含复杂表格的正式入库任务时，应优先生成 formal ingest handoff：

```bash
python scripts/convert.py pipeline \
  --input /path/to/input \
  --output /path/to/handoff \
  --backend mineru-fastapi \
  --mineru-base-url https://mineru.example.internal \
  --table-quality high \
  --mineru-asset-mode markdown_assets \
  --postprocess-profile chunk-markers-dense \
  --json
```

如果 host agent 需要自行判断是否提升，可把 `--table-quality high` 换成 `--table-quality auto`。

## 12. 持续跟踪问题和改善方向

本轮完成的是表格质量主路径的工程闭环，不代表复杂表格问答已经没有剩余风险。后续应持续跟踪：

- **High-accuracy backend 可用性**：不同 MinerU 版本、FastAPI schema 和模型部署可能支持不同 backend
  名称或参数。需要继续记录 backend unsupported、timeout、OOM、upstream 5xx 的真实比例，并据此优化
  `auto` 策略和错误建议。
- **`auto` 策略触发条件**：当前主要基于正式候选文件类型提升。后续可接入上一轮 quality warning、
  content-list `complex_table` 信号、表格密度、数字/单位密度和用户意图提示，让自动提升更精确。
- **超大表格原子性**：`chunk-markers-dense` 和 delimiter 可以保护普通表格边界，但如果 RAGFlow 部署的
  `chunk_token_num` 上限偏小，超大表格仍可能被服务端二次切分。docs/22 后续已补充
  `table_parent_chunk_preflight`、表格 token 估算和小父 chunk profile warning；后续风险主要是
  live 部署实际上限与服务端二次切分行为仍需现场验证。
- **复杂 HTML 结构语义**：rowspan/colspan、多级表头、公式符号和单位关系仍主要取决于上游 MinerU 解析。
  docs/22 后续已补充 per-table 结构风险评分、表头层级摘要输入、`semantic_risks` 和 review hints；
  剩余风险是这些 hints 只能提示人工或 host agent 复核，不能无损修复错误的上游表格结构。
- **表格问答准确率**：APOLLO 类规格表中，表头别名、型号族、单位符号和跨表对比仍可能导致检索或回答误判。
  docs/22 后续已补充 `apollo_table_qa_fixture_v1`、离线 evaluate、no-LLM table strategy report 和外部
  judge request/review 边界；完整 16 问填充仍需在私有侧脱敏后执行。
- **图片与表格联合证据**：复杂产品数据页经常需要图片、表格、caption 和页面上下文共同解释。后续可加强
  `retrieval_hints` 中 table artifact 与 image artifact 的同页/同标题关联，辅助 KB profile 和查询阶段引用。
- **KB 侧 zip/资产上传策略**：`ragflow-doc-to-md` 已能产出 Markdown assets 和 rich handoff，docs/22 后续已补充
  `ragflow_kb_asset_upload_plan_v1` 和本地 zip 物化。真正用 zip 或 API 批量携带图片资产 live 入库仍属于
  `ragflow-kb-build` 的单独 live mutation 设计问题，需要确认 API 语义、fake-client 覆盖并经过批准。
- **Live RAGFlow 端到端验证**：本轮只把代表样本的 high-accuracy 转换、handoff、inspect 和 dry-run 路径跑通。
  真正的 live KB 创建、解析、查询和清理仍需显式批准，并应记录为脱敏 field-trial evidence。
- **跨文档/跨版本回归矩阵**：除代表产品数据页外，还应持续收集扫描件、财报、论文、长合同、图片密集文档和
  Office 表格样本，比较 `standard`、`auto`、`high` 的质量、耗时、失败率和 fallback 频率。

后续改进应坚持两个边界：一是 `ragflow-doc-to-md` 只负责高质量 Markdown handoff 和可审计报告，不直接创建
或修改 RAGFlow KB；二是任何 live mutation、LLM 表格重写、远端 VLM 服务绑定或 KB 侧资产上传，都必须作为
独立设计和显式批准任务推进。
