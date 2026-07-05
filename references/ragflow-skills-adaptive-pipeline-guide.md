# ragflow-skills：adaptive pipeline 端到端使用指南

**日期**：2026-07-05
**版本**：基于 `ragflow-skills` commit `b4f00e2 Add adaptive document pipeline reports`

## 背景

`adaptive` 是 `ragflow-doc-to-md` 新增的一条命令，目的是：先对文档做轻量特征检测，再基于确定性规则自动推荐 pipeline 参数组合，最后执行完整转换。它解决了用户在未读文档前无法选择最佳参数的问题；LLM 决策当前不启用，仍属于后续 gated 能力。

## 命令总览

```bash
python scripts/convert.py adaptive \
  --input ./raw \
  --output ./handoff \
  --backend mineru-fastapi \
  --adaptive-policy {formal, fast-preview, table-atomic} \
  [--decision-only] \
  [--postprocess-profile chunk-markers-dense] \
  [--json]
```

## 三个主要阶段

### 1. inspect-source（预检测）

独立命令：

```bash
python scripts/convert.py inspect-source \
  --input ./raw \
  --report-json ./run/document_features.json \
  --report-md ./run/document_features.md
```

**注意**：`inspect-source` 不接收 `--output` 或 `--backend` 参数。它通过 `--report-json` 和 `--report-md` 指定输出路径。

输出 `document_features.json` 包含：
- `summary.document_count`
- `summary.primary_language`
- `summary.sample_table_count` / `sample_html_table_count` / `sample_markdown_table_count`
- `summary.sample_image_ref_count`
- `summary.max_table_density`
- `summary.table_heavy`
- `summary.image_rich`
- `summary.long_document`
- `summary.estimated_complexity`

### 2. adaptive --decision-only（参数决策）

```bash
python scripts/convert.py adaptive \
  --input ./raw \
  --output ./run \
  --decision-only \
  --adaptive-policy table-atomic
```

**注意**：`--decision-only` 是 flag，不是 `--mode decision-only`。

输出 `pipeline_decision.json` 结构：

```json
{
  "schema": "ragflow_pipeline_decision_v1",
  "policy": "table-atomic",
  "confidence": "high",
  "signals": {
    "table_heavy": true,
    "has_tables": true,
    "image_rich": false,
    "long_document": false
  },
  "recommendation": {
    "backend": "builtin",
    "table_quality": "auto",
    "postprocess_profile": "chunk-markers-dense",
    "mineru_asset_mode": "markdown_assets",
    "mineru_fastapi_backend": "pipeline",
    "allow_table_quality_fallback": false,
    "kb_profile": {
      "id": "table-atomic-en-4096",
      "chunk_size": 4096,
      "chunk_overlap": 0,
      "parser_config": {
        "chunk_token_num": 4096,
        "delimiter": "`<!-- chunk -->`",
        "auto_keywords": 0,
        "auto_questions": 0,
        "__language__": "English"
      },
      "avoid_children_delimiter": true
    }
  },
  "reasons": [
    "Table signals select dense markers and a table-atomic KB profile.",
    "Formal source or table signals select table-quality auto."
  ]
}
```

关键字段含义：
- `policy`：决策策略（`formal` / `fast-preview` / `table-atomic`）
- `confidence`：规则决策通常是 `high`，LLM 决策可能为 `medium`
- `signals`：从 `document_features` 提取的关键信号
- `recommendation`：完整推荐参数组合
- `recommendation.kb_profile`：建议的 RAGFlow chunk profile
- `reasons`：每条决策的可读理由

### 3. adaptive 完整 pipeline（执行转换）

```bash
python scripts/convert.py adaptive \
  --input ./raw \
  --output ./handoff \
  --backend mineru-fastapi \
  --adaptive-policy table-atomic \
  --postprocess-profile chunk-markers-dense \
  --json
```

完整 pipeline 会：
1. 内部调用 `inspect-source` 生成 `document_features.json`
2. 内部调用 `make_pipeline_decision` 生成 `pipeline_decision.json`
3. 使用推荐参数执行 `convert` → `postprocess` → `package`
4. 输出完整 handoff

## policy 选择

| policy | 适用场景 | 推荐参数倾向 |
|---|---|---|
| `formal` | 默认正式流程 | 平衡配置，按语言/文档大小选择 chunk size |
| `fast-preview` | 快速预览 | 轻量配置，快速产出，不追求高精度 |
| `table-atomic` | 表格密集文档 | 大 chunk size (4096)、dense markers、table-atomic profile |

## 端到端测试示例

最小可复现实验：

```bash
mkdir -p /tmp/ragflow-e2e/input
mkdir -p /tmp/ragflow-e2e/output

# 写入测试 Markdown
cat > /tmp/ragflow-e2e/input/apollo-test.md << 'MD'
# APOLLO Test Document

## Specifications

| Product | Accuracy | Range | Weight |
| --- | --- | --- | --- |
| APOLLO-A | 4.0 μm | 100 mm | 2.5 kg |
| APOLLO-B | 2.5 μm | 200 mm | 3.2 kg |
| APOLLO-C | 1.8 μm | 300 mm | 4.1 kg |
| APOLLO-D | 1.2 μm | 400 mm | 5.0 kg |
| APOLLO-E | 0.9 μm | 500 mm | 6.3 kg |
| APOLLO-F | 0.6 μm | 600 mm | 7.8 kg |
| APOLLO-G | 0.4 μm | 700 mm | 9.2 kg |
| APOLLO-H | 0.3 μm | 800 mm | 10.5 kg |
| APOLLO-I | 0.2 μm | 900 mm | 12.1 kg |
| APOLLO-J | 0.1 μm | 1000 mm | 14.7 kg |

## Image Reference

![APOLLO diagram](data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=)
MD

# 1. inspect-source
python skills/ragflow-doc-to-md/scripts/convert.py inspect-source \
  --input /tmp/ragflow-e2e/input \
  --report-json /tmp/ragflow-e2e/document_features.json \
  --report-md /tmp/ragflow-e2e/document_features.md

# 2. decision-only
python skills/ragflow-doc-to-md/scripts/convert.py adaptive \
  --input /tmp/ragflow-e2e/input \
  --output /tmp/ragflow-e2e/output/adaptive-only \
  --decision-only \
  --backend builtin \
  --adaptive-policy table-atomic

# 3. full pipeline
python skills/ragflow-doc-to-md/scripts/convert.py adaptive \
  --input /tmp/ragflow-e2e/input \
  --output /tmp/ragflow-e2e/output/adaptive-pipeline \
  --backend builtin \
  --adaptive-policy table-atomic \
  --postprocess-profile chunk-markers-dense
```

验证 chunk marker 不切入表格：

```bash
python -c "
from pathlib import Path
md = Path('/tmp/ragflow-e2e/output/adaptive-pipeline/documents/apollo-test.md').read_text()
lines = md.splitlines()
inside_table = any('|' in line and '<!-- chunk -->' in line for line in lines)
print('marker inside table:', inside_table)
print('marker count:', md.count('<!-- chunk -->'))
print('table rows:', sum(1 for line in lines if line.startswith('| APOLLO')))
"
```

## 实测结果（2026-07-05）

| 检查项 | 结果 |
|---|---|
| inspect-source | 通过，识别 `table_heavy=true`，检测到 1 个 Markdown 表格 |
| adaptive decision-only | 通过，推荐 `table-atomic-en-4096` + `chunk-markers-dense` |
| adaptive full pipeline | 通过，handoff 完整 |
| chunk marker 总数 | 6 |
| marker 在表格行内部 | 否 |
| 长表格被切分 | 否，10 行表格完整保留 |
| quality gate | PASS |

## 当前限制

1. **base64 内嵌图片不会被重命名**：`semantic_rename_markdown_images` 只处理本地 opaque hash 文件，如 `images/6a1b2c3d...png`。base64 内嵌图片保持原样。
2. **LLM 决策未启用**：当前 `table-atomic` policy 是规则决策，`script_owned_llm_calls=0`。复杂边界需后续 gated request/review 或显式 LLM/backend gate。
3. **决策报告需显式消费**：`pipeline_decision.json` 的推荐参数不会自动强制覆盖用户显式传入的参数，需人工确认或写脚本消费。

## 后续扩展

- 用真实 PDF（含本地图片 + 表格）验证 `semantic_rename_markdown_images` 和 `table-quality high` 路径
- 在 Blackwell (RTX 5070 Ti) 上用 backend probe/warmup 和 fallback policy 验证 `mineru-fastapi` 路径
- 探索 `--decision-override` 参数用法，实现用户自定义决策规则

## Cross-refs

- `ragflow-skills/SKILL.md` 主文档
- `references/ragflow-skills-table-atomicity.md` — chunk marker / table 原子性
- `references/ragflow-skills-vs-ragflux-vs-kb-ops.md` — 三套管线对比
