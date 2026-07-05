---
name: ragflow-skills-adaptive-pipeline-proposal
description: 提案：为 ragflow-skills 增加文档自适应解析管线，先轻量检测文档内容，再智能选择 backend / table_quality / postprocess_profile / chunk profile 参数组合，最后执行完整解析。
version: 1.0.0
author: Architecture Partner
_created: 2026-07-05
---

# ragflow-skills 自适应解析管线提案

## 现状

当前 `ragflow-skills` 没有「先检测文档内容、再让 AI/规则自动选择最佳参数组合、最后执行完整解析」的闭环机制。现有能力分为三层：

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
2. **高成本 backend 不能盲用**：`table-quality high` / `accurate` 模式在 Blackwell (RTX 5070 Ti) 上会崩溃，必须先知道 GPU 和文档类型才能避免。
3. **推荐不闭环**：现有 `profile_suggestions.json` 只是建议，不会自动把推荐参数传回 pipeline 再执行。
4. **没有可复用的内容特征库**：每次文档都重新试错，没有记录文档特征与最佳参数的映射。

## 建议目标

增加一个 **adaptive pipeline** 阶段，实现：

1. **轻量预检测**：对原始文档做一次低成本扫描，提取内容特征。
2. **智能参数决策**：基于规则和/或 LLM 分析特征，输出推荐参数组合。
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
[ 阶段 4：验证 & 建议 ]
    │ 输出：profile_suggestions.json + 是否需要重跑建议
```

### 阶段 1：轻量预检测（`doc_inspect` 模块）

新增命令或子模块：

```bash
python scripts/convert.py inspect-source \
  --input ./raw/doc.pdf \
  --output ./run/doc_features.json \
  --backend mineru-fastapi \
  --mineru-base-url https://mineru.example.internal
```

检测内容（最小可运行集）：

| 特征 | 获取方式 | 用途 |
|---|---|---|
| `language` | 采样前 N 字符 + 字符集检测 | 决定 chunk size、parser_config.__language__ |
| `page_count` | MinerU metadata / PyMuPDF / pdfinfo | 决定是否需要 segment/split |
| `has_tables` | 检测 `<table>`、`| --- |`、content_list 中 table 类型 | 决定是否 table-atomic profile |
| `table_density` | 表格行数 / 总字符数 | 决定是否 `--table-quality high` |
| `image_density` | 图片数 / 页数 | 判断是否图文混排、需要 image fallback |
| `is_scanned` | 字符覆盖率 / 是否有 OCR 置信度 | 判断是否启用 OCR 路径 |
| `estimated_complexity` | 综合打分 | 决定 backend、timeout、重试策略 |

实现依赖：
- 对 PDF 可用 `pypdf`、`pdfplumber`、`PyMuPDF` 做轻量解析
- 如果已配置 MinerU，可用 `fast` / `pipeline` 跑一次「仅 layout / 仅 metadata」的快速解析
- 不引入重量级依赖；缺失时降级到基础检测

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
        "table_quality": "standard",  # high 在 Blackwell 上不可用
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

#### 2b LLM 决策（可选、非确定性、用于复杂边界）

当规则冲突或特征模糊时，把 `doc_features.json` + 少量采样文本传给 LLM，要求 JSON 输出推荐参数。LLM 只决策参数，不执行解析，成本可控。

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

LLM 决策必须有：
- 固定 system prompt + 输出 schema 约束
- 可覆盖（`--decision-override`）
- 记录到 `pipeline_decision.json`

### 阶段 3：执行完整 pipeline

由新的 `adaptive` 子命令统一编排：

```bash
python scripts/convert.py adaptive \
  --input ./raw \
  --output ./handoff \
  --features-output ./run/doc_features.json \
  --decision-output ./run/pipeline_decision.json \
  --backend mineru-fastapi \
  --mineru-base-url https://mineru.example.internal
```

执行逻辑：
1. 运行 `inspect-source` 生成 `doc_features.json`
2. 调用 `adaptive_decision` 生成 `pipeline_decision.json`
3. 用决策参数调用 `pipeline`（`postprocess_profile`、`table_quality` 等）
4. 输出完整 handoff

### 阶段 4：验证与重跑建议

`pipeline` 结束后，结合 `quality_report.json` 和 `profile_suggestions.json`：
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

## 最小可行实现（MVP）

1. 新增 `doc_inspect.py`：
   - 函数 `inspect_source_document(path, backend, ...)` → `DocumentFeatures`
   - 支持 `builtin` 文本/HTML、`pypdf` 采样、`mineru-fastapi` lightweight metadata
2. 新增 `adaptive_decision.py`：
   - 规则引擎 + 可选 LLM 适配器接口
   - 输出 `PipelineDecision`（含 reason）
3. 新增 `convert.py adaptive` 子命令：
   - 串起 inspect → decide → pipeline
   - 保留 `--decision-override` 和 `--dry-run` 选项
4. 新增测试：
   - 表格密集 PDF → 推荐 table-atomic
   - 纯文本 → 推荐 default safe
   - 扫描件 → 推荐 OCR 路径且不选 high table quality
5. 更新 SKILL.md：
   - 增加 `adaptive` 命令示例
   - 说明决策规则与覆盖方式

## 风险与规避

| 风险 | 规避 |
|---|---|
| 预检测本身耗时 | 用 `fast` / `pipeline` metadata 或 PyPDF 采样，限制采样页数 |
| LLM 决策结果不稳定 | 默认用规则；LLM 仅作可选增强，schema 约束输出 |
| Blackwell 上 `table-quality high` 崩溃 | 规则中结合 GPU arch 检测，sm_120 禁用 hybrid-auto-engine |
| 用户不信任自动决策 | 强制输出 `pipeline_decision.json`，提供 `--decision-override` |
| 参数组合爆炸 | 只维护 4-6 条规则，覆盖常见场景；复杂场景走 LLM 或人工 |

## 建议优先级

| 优先级 | 任务 | 收益 |
|---|---|---|
| P0 | 实现 `doc_inspect.py` 规则特征检测 + `adaptive` 命令串联 | 立刻解决「不了解文档盲选参数」问题 |
| P1 | 将 `profile_suggestions` 从事后建议改为可传入 `adaptive` 的决策输入 | 提升决策准确度 |
| P2 | 增加 LLM 决策适配器（可选） | 处理复杂边界，保持规则默认 |
| P3 | 积累文档特征 → 最佳参数 mapping | 长期形成可复用知识库 |

## 参考

- `ragflow-skills` 当前路径：`<ragflow-skills-repo>`
- `doc_postprocess.py` 中的 postprocess profile 配置
- `handoff.py` 中的 `make_profile_suggestions_payload`
- `profiles.py` 中的 `recommend_profile`
- `doc_convert.py` 中的 backend 路由逻辑
- 测试报告：`<run-artifacts>/ragflow-skills-test-report.md`

---

**下一步建议**：先实现 P0 的 `doc_inspect.py` + `adaptive` 命令 MVP，用一个表格密集 PDF 和一份纯文本文档做对照测试，验证规则决策是否正确。
