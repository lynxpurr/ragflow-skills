---
name: ragflow-skills-adaptive-pipeline-proposal
description: 设计与完成记录：为 ragflow-skills 增加确定性自适应解析管线，先轻量检测文档内容，再选择 backend / table_quality / postprocess_profile / chunk profile 参数组合，最后复用正式 pipeline。
version: 1.1.0
author: Architecture Partner
_created: 2026-07-05
---

# ragflow-skills 自适应解析管线设计与完成记录

状态：P0/P1 公共离线开发已完成；LLM 决策、live KB 验证和长期特征知识库仍保持 gated / observation。
日期：2026-07-05

## 本轮结论

本轮已把 adaptive pipeline 从提案推进为可运行、可审计、可测试的公共 CLI 能力：

- 新增 `ragflow_document_features_v1`，由 `ragflow-doc-to-md inspect-source` 生成轻量源文档特征。
- 新增 `ragflow_pipeline_decision_v1`，由确定性规则选择 `backend`、`table_quality`、
  `postprocess_profile`、`mineru_asset_mode` 和推荐 KB profile。
- 当首轮 source inspection 在 PDF、Office、图片等需要转换的输入中发现表格信号时，规则会自动选择
  `mineru-fastapi`、`table_quality: high`、`mineru_fastapi_backend: hybrid-auto-engine`、
  `markdown_assets` 和 `chunk-markers-dense`，从源头启用高质量 table 提取；已有 Markdown/HTML
  表格不强制重走 MinerU。
- 新增 `ragflow_adaptive_pipeline_summary_v1`，由 `ragflow-doc-to-md adaptive` 输出执行摘要和
  后续 `inspect-handoff`、`asset-upload-plan`、`dry-run` 离线 review 命令。
- `adaptive --decision-only` 可只生成 features/decision/summary，不执行转换。
- `adaptive` 默认复用现有 `pipeline`，不新增 live RAGFlow mutation、不调用 LLM、不绕过 quality gate。
- 新增 focused runtime/CLI/inventory/schema tests，并把新 schema 和新 CLI surface 纳入
  schema identity、report surface inventory、generated Markdown audit 和 runtime resilience inventory。

本文件中的“现状/问题”描述的是本轮启动前的缺口；后续“完成清单”记录当前实现状态。

## 现状

本轮启动前，`ragflow-skills` 没有「先检测文档内容、再用规则自动选择最佳参数组合、最后执行完整解析」的闭环机制。既有能力分为三层：

| 能力 | 位置 | 自动化程度 | 限制 |
|---|---|---|---|
| `backend=auto` | `doc_convert.py` | 按文件扩展名选 backend | 不分析文档内容 |
| `recommend_profile()` | `profiles.py` | 按用户指定的 `language` + `doc_type` 给固定参数 | `doc_type` 只有 6 个预设类别，不读取文档内容 |
| `make_profile_suggestions_payload()` | `handoff.py` | 在 `pipeline` 跑完后分析 Markdown 产物，推荐 `default` 或 `table-atomic` profile | 事后建议，不能自动执行；无 AI 判断；不做 backend/table_quality 选择 |

也就是说，用户在运行 `doc-to-md` 之前必须已经知道：
- 文档是否表格密集
- 是否是扫描件 / 图文混排
- 最佳 chunk size 和 overlap
- 是否需要 `table-quality high` 或 `chunk-markers-dense`

不了解文档时，只能盲选默认参数，跑完后若发现质量不佳再重跑，成本高。

## 问题

1. **参数选择依赖先验知识**：表格多、扫描件、复杂版式需要不同的 backend 和 quality 设置，但用户未读文档前不知道。
2. **高成本 backend 不能盲用**：`table-quality high` / `accurate` 类路径需要结合 backend capability、既有 FastAPI 服务状态、失败类别和 fallback policy 判断，不能仅按 GPU 型号一刀切。
3. **推荐不闭环**：现有 `profile_suggestions.json` 只是建议，不会自动把推荐参数传回 pipeline 再执行。
4. **没有可复用的内容特征库**：每次文档都重新试错，没有记录文档特征与最佳参数的映射。

## 建议目标

增加一个 **adaptive pipeline** 阶段，实现：

1. **轻量预检测**：对原始文档做一次低成本扫描，提取内容特征。
2. **智能参数决策**：默认基于确定性规则分析特征，输出推荐参数组合；LLM 只作为后续 gated request/review 方向。
3. **自动执行闭环**：用推荐参数执行完整 `pipeline`。
4. **可验证、可回退**：保留预检测报告和决策理由，用户可以覆盖。

## 建议方案

### 总体流程

```
原始文档
    │
    ▼
[ 阶段 1：轻量预检测 ]
    │ 输出：document_features.json
    │ 包含：language, has_tables, table_density, is_scanned,
    │       image_density, page_count, estimated_complexity
    ▼
[ 阶段 2：参数决策 ]
    │ 输出：pipeline_decision.json
    │ 包含：backend, table_quality, postprocess_profile,
    │       chunk_profile, asset_mode, 决策理由
    ▼
[ 阶段 3：执行完整 pipeline ]
    │ 输出：handoff/ + doc_manifest.json + quality_report.json
    ▼
[ 阶段 4：验证 & review 建议 ]
    │ 输出：adaptive_summary.json + 离线 review command manifest
```

### 阶段 1：轻量预检测（`doc_inspect` 模块）

新增命令或子模块：

```bash
python scripts/convert.py inspect-source \
  --input ./raw/doc.pdf \
  --report-json ./run/document_features.json \
  --report-md ./run/document_features.md \
  --redaction-report ./run/document_features.redaction.json
```

检测内容（最小可运行集）：

| 特征 | 获取方式 | 用途 |
|---|---|---|
| `language` | 采样前 N 字符 + 字符集检测 | 决定 chunk size、parser_config.__language__ |
| `page_count` | PDF 轻量二进制探测；未来可接入 PyMuPDF/pdfinfo | 决定是否需要 segment/split |
| `has_tables` | 检测 `<table>`、`| --- |` 等采样信号 | 决定是否 table-atomic profile |
| `table_density` | 表格行数 / 总字符数 | 决定是否 `--table-quality high` |
| `image_density` | 图片数 / 页数 | 判断是否图文混排、需要 image fallback |
| `is_scanned` | 字符覆盖率 / 是否有 OCR 置信度 | 判断是否启用 OCR 路径 |
| `estimated_complexity` | 综合打分 | 决定 backend、timeout、重试策略 |

实现依赖：
- 当前实现不引入重量级依赖；PDF 只做有限二进制探测和低文本风险标记。
- 未来如果需要更高置信度，可在不破坏默认离线路径的前提下接入 PyMuPDF/pdfinfo 或可选 preview backend。

### 阶段 2：参数决策（`adaptive_decision` 模块）

两种方式，可以并存：

#### 2a 规则决策（默认、确定性、低成本）

根据 `doc_features.json` 查表决策：

```python
ADAPTIVE_RULES = [
    # 表格密集 + 扫描件 → 高成本 backend + dense markers
    {
        "when": {"table_density": ">0.05", "is_scanned": True},
        "backend": "mineru-fastapi",
        "table_quality": "auto",
        "postprocess_profile": "chunk-markers-dense",
        "chunk_profile": "table-atomic-zh-4096",
        "reason": "scanned + table-heavy: use OCR pipeline with table-atomic chunks",
    },
    # 表格密集 + 数字文档 → 高精度 backend
    {
        "when": {"table_density": ">0.05", "is_scanned": False},
        "backend": "mineru-fastapi",
        "table_quality": "high",
        "postprocess_profile": "chunk-markers-dense",
        "chunk_profile": "table-atomic-zh-4096",
        "reason": "digital + table-heavy: high-accuracy table parsing",
    },
    # 图片密集 → markdown_assets + image context
    {
        "when": {"image_density": ">0.5"},
        "backend": "mineru-fastapi",
        "table_quality": "standard",
        "postprocess_profile": "chunk-markers-dense",
        "asset_mode": "markdown_assets",
        "reason": "image-rich: preserve image context",
    },
    # 默认
    {
        "when": {},
        "backend": "auto",
        "table_quality": "standard",
        "postprocess_profile": "safe",
        "chunk_profile": "default",
        "reason": "default conservative settings",
    },
]
```

#### 2b LLM 决策（后续 gated、非 P0 默认）

当规则冲突或特征模糊时，未来可以把 `document_features.json` + 少量采样文本打包成外部 request/review
artifact，由 host-approved 模型给出 advisory 参数建议。当前公共实现不启用 script-owned LLM 调用。

```json
{
  "recommendation": {
    "backend": "mineru-fastapi",
    "table_quality": "high",
    "postprocess_profile": "chunk-markers-dense",
    "chunk_profile": "table-atomic-zh-4096",
    "asset_mode": "markdown_assets"
  },
  "reason": "表格占比 12%，非扫描件，建议使用高精确度表格解析..."
}
```

未来 LLM 决策必须有：
- 固定 system prompt + 输出 schema 约束
- 可覆盖（当前已支持 `--decision-override`）
- 记录到 `pipeline_decision.json`

### 阶段 3：执行完整 pipeline

由新的 `adaptive` 子命令统一编排：

```bash
python scripts/convert.py adaptive \
  --input ./raw \
  --output ./handoff \
  --features-report-name document_features.json \
  --decision-report-name pipeline_decision.json \
  --adaptive-summary-name adaptive_summary.json \
  --backend mineru-fastapi \
  --mineru-base-url https://mineru.example.internal
```

执行逻辑：
1. 运行 `inspect-source` 生成 `doc_features.json`
2. 调用 `adaptive_decision` 生成 `pipeline_decision.json`
3. 用决策参数调用 `pipeline`（`postprocess_profile`、`table_quality` 等）
4. 输出完整 handoff

### 阶段 4：验证与 review 建议

`adaptive` 结束后，结合 `quality_report.json`、`profile_suggestions.json`、`retrieval_hints.json`
和 `ingest_readiness_report.json`：
- 如果 `quality_gate.status == BLOCKED` → 建议升级参数或换 backend
- 如果表格原子性检测失败 → 建议增大 chunk size 或改用 table-atomic
- 如果长文档（>200 页） → 建议 `segment-plan` + `split`

## 与现有架构的衔接

| 现有模块 | 新模块 | 关系 |
|---|---|---|
| `doc_convert.py` | `doc_inspect.py` | 新增轻量预检测，复用 backend 选择逻辑 |
| `doc_postprocess.py` | `adaptive_decision.py` | 决策时引用 postprocess profile 配置 |
| `handoff.py` 的 `make_profile_suggestions_payload` | `adaptive_decision.py` | 把事后建议扩展为事前决策输入 |
| `profiles.py` 的 `recommend_profile` | `adaptive_decision.py` | 规则决策可调用 `recommend_profile` 作为 fallback |
| `convert.py` CLI | `adaptive` subcommand | 新增入口，不破坏现有命令 |

## 最小可行实现（MVP）完成状态

| 状态 | 任务 | 当前实现 |
| --- | --- | --- |
| 完成 | 新增 `doc_inspect.py` | `inspect_source_document()` 输出 `ragflow_document_features_v1`；支持 builtin 文本/HTML/Markdown 采样、PDF 轻量二进制页数/文本探测、图片/Office/PDF/formal candidate 信号。 |
| 完成 | 新增 `adaptive_decision.py` | `make_pipeline_decision()` 输出 `ragflow_pipeline_decision_v1`；默认规则选择 dense marker、table-atomic profile、table quality、asset mode，并显式记录 `script_owned_llm_calls=0`。 |
| 完成 | 新增 `inspect-source` CLI | `ragflow-doc-to-md inspect-source --report-json --report-md --redaction-report` 生成源文档特征报告。 |
| 完成 | 新增 `adaptive` CLI | `ragflow-doc-to-md adaptive` 串起 inspect → decide → pipeline；`--decision-only` 只生成报告；`--decision-override` 支持人工覆盖；PDF/Office/图片输入一旦在首轮试探中检测到表格信号，会自动启用 high-quality table 提取路径。 |
| 完成 | 新增 adaptive summary | `ragflow_adaptive_pipeline_summary_v1` 输出后续 `inspect-handoff`、`asset-upload-plan` 和 KB dry-run review 命令，不执行 live mutation。 |
| 完成 | 测试与 release governance | 新增 focused tests；schema identity、report surface inventory、generated Markdown audit、runtime resilience inventory 已同步。 |
| 后续 gated | LLM 决策适配器 | 当前仅保留 request/review 方向，不启用 script-owned LLM。 |
| 后续 observation | 特征到最佳参数知识库 | 需要多样本 field-trial evidence 后再设计，不作为本轮未完成公共离线任务。 |

## 风险与规避

| 风险 | 规避 |
|---|---|
| 预检测本身耗时 | 用 `fast` / `pipeline` metadata 或 PyPDF 采样，限制采样页数 |
| LLM 决策结果不稳定 | 默认用规则；LLM 仅作可选增强，schema 约束输出 |
| high-accuracy backend 资源或兼容失败 | 基于 backend probe/status、失败类别和 fallback policy 决策；不再仅按 GPU 型号硬禁。 |
| 用户不信任自动决策 | 强制输出 `pipeline_decision.json`，提供 `--decision-override` |
| 参数组合爆炸 | 只维护 4-6 条规则，覆盖常见场景；复杂场景走 LLM 或人工 |

## 建议优先级

| 优先级 | 任务 | 收益 |
|---|---|---|
| P0 | 实现 `doc_inspect.py` 规则特征检测 + `adaptive` 命令串联 | 完成 |
| P1 | 输出 adaptive summary 和离线 review command manifest | 完成 |
| P2 | 增加 LLM 决策 request/review 适配器（可选） | gated；需 Phase 38 LLM/backend gate |
| P3 | 积累文档特征 → 最佳参数 mapping | observation；需多样本 field-trial evidence |

## 参考

- `ragflow-skills` 当前路径：`<ragflow-skills-repo>`
- `doc_postprocess.py` 中的 postprocess profile 配置
- `handoff.py` 中的 `make_profile_suggestions_payload`
- `profiles.py` 中的 `recommend_profile`
- `doc_convert.py` 中的 backend 路由逻辑
- 测试报告：`<run-artifacts>/ragflow-skills-test-report.md`

---

## 当前使用方式

只看决策、不执行转换：

```bash
python scripts/convert.py adaptive \
  --input <source> \
  --output <handoff> \
  --decision-only \
  --report-json <run>/adaptive_summary.json \
  --report-md <run>/adaptive_summary.md \
  --redaction-report <run>/adaptive_summary.redaction.json \
  --json
```

执行正式 adaptive handoff：

```bash
python scripts/convert.py adaptive \
  --input <source> \
  --output <handoff> \
  --backend mineru-fastapi \
  --mineru-base-url <mineru-fastapi-base-url> \
  --json
```

生成后继续保持离线 review：

```bash
ragflow-kb-build inspect-handoff --handoff <handoff>
ragflow-kb-build asset-upload-plan --doc-manifest <handoff>/doc_manifest.json
ragflow-kb-build --doc-manifest <handoff>/doc_manifest.json --profile <reviewed-profile.json> --dry-run --json
```

## 本轮剩余事项分类

- 公共离线实现任务：已清空。
- 私有数据/fixture：无本轮必需项。
- live RAGFlow 验证：仍需明确批准，不能由 adaptive 默认执行。
- script-owned LLM 决策：仍属 Phase 38 gated，不作为本轮未完成代办。
- 多样本参数知识库：进入 field-trial observation，不作为未完成代码任务。
