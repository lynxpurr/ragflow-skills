---
name: ragflow-skills
description: "RAGFlow 三 skill 套件：ragflow-doc-to-md + ragflow-kb-build + ragflow-query。知识库准备阶段以 doc-to-md → kb-build 为主线；覆盖 handoff 契约、regression test、chunk marker/table 原子性、以及 ragflux/ragflow-kb-ops 退役过渡对照。"
version: 1.0.1
author: Architect (Luca)
_updated: '2026-07-05'
license: MIT
metadata:
  hermes:
    tags: [ragflow, rag, document-pipeline, knowledge-base, mineru, markdown, chunking, regression-test]
    related_skills: [ragflow-doc-to-md, ragflow-kb-build, ragflow-query, ragflux, ragflow-kb-ops, ragflow-smart-query, rag-systems]
---

# RAGFlow Skills — 文档入库技能套件

本 skill 是当前项目三 skill 套件的总入口：`ragflow-doc-to-md` 负责文档到 Markdown handoff，`ragflow-kb-build` 负责 handoff 到 RAGFlow KB 与验证，`ragflow-query` 负责检索、路由和证据验证。知识库准备阶段默认走 `doc-to-md` → `kb-build`；`ragflux` / `ragflow-kb-ops` 是退役完成前的对照和过渡工具，不作为新流程主路径。

## 触发条件

- 用户提到 "ragflow-skills"、"doc-to-md"、"kb-build"、"ragflow-query"
- 需要规划知识库准备路径：source document → Markdown handoff → KB build
- 需要跑一轮 `ragflow-skills` 回归测试
- 需要对比当前三 skill 套件 vs `ragflux` / `ragflow-kb-ops` 退役过渡路径
- 需要确认 chunk marker 是否会在表格中间插入
- 需要理解 handoff 产物（`doc_manifest.json`、`ragflow_ingest_plan.yaml`）如何传给下游

## 仓库结构

```
~/.hermes/skills/research/ragflow-skills/
├── packages/ragflow-skill-runtime/    # 核心运行时库（被 skills/ 和 dist/ 共用）
│   ├── src/ragflow_skill_runtime/     # doc_convert, doc_postprocess, kb_build, handoff ...
│   └── tests/                         # 515 项回归测试
├── skills/ragflow-doc-to-md/          # 开发版 CLI
├── skills/ragflow-kb-build/          # 开发版 CLI
├── skills/ragflow-query/             # 开发版 CLI
├── dist/ragflow-doc-to-md/            # 发布版，带 _vendor/ 内嵌 runtime
├── dist/ragflow-kb-build/             # 发布版，带 _vendor/ 内嵌 runtime
└── dist/ragflow-query/                # 发布版，带 _vendor/ 内嵌 runtime
```

`skills/` 与 `dist/` 的脚本主体同步。差异：
- `skills/` 多 `agents/`、`doc/`、`__pycache__`
- `dist/` 多 `_vendor/` 内嵌 runtime

CLI 脚本通过 `bootstrap_runtime()` 优先从 `RAGFLOW_SKILL_RUNTIME_PATH` → 自身 `_vendor` → 相邻 `_shared` 加载 runtime。

## 标准回归测试

```bash
cd ~/.hermes/skills/research/ragflow-skills
python3 -m venv .venv
.venv/bin/pip install -e packages/ragflow-skill-runtime
.venv/bin/pip install pytest pyyaml requests
.venv/bin/python -m pytest packages/ragflow-skill-runtime/tests -v --tb=short
```

**基准结果**：515 passed, 6 subtests passed, 0 failed，耗时约 120 秒。

若新增 commit 或修改 runtime，跑完这轮测试后再评估是否可用。

## 核心能力与 profile

默认使用顺序：

1. `ragflow-doc-to-md` 先生成 Markdown handoff 与质量报告。
2. `ragflow-kb-build` 消费 handoff，先 dry-run，再按需执行 live build 和验证。
3. KB 建成后再用 `ragflow-query` 做检索、路由、证据和引用验证。

### doc-to-md

标准入口：

```bash
python scripts/convert.py pipeline \
  --input ./raw \
  --output ./handoff \
  --backend mineru-fastapi \
  --mineru-base-url https://mineru.example.internal \
  --mineru-asset-mode markdown_assets \
  --postprocess-profile chunk-markers-dense
```

自适应入口（inspect → decide → pipeline 一键）：

```bash
python scripts/convert.py adaptive \
  --input ./raw \
  --output ./handoff \
  --backend mineru-fastapi \
  --mineru-base-url https://mineru.example.internal \
  --adaptive-policy table-atomic \
  --postprocess-profile chunk-markers-dense \
  --json
```

只生成决策、不执行转换：

```bash
python scripts/convert.py adaptive \
  --input ./raw \
  --output ./run \
  --decision-only \
  --backend mineru-fastapi \
  --adaptive-policy table-atomic \
  --json
```

先 inspect 再单独决策：

```bash
python scripts/convert.py inspect-source \
  --input ./raw \
  --report-json ./run/document_features.json \
  --report-md ./run/document_features.md

python scripts/convert.py adaptive \
  --input ./raw \
  --output ./run \
  --decision-only \
  --adaptive-policy table-atomic \
  --json
```

主要产物：
- `documents/*.md`
- `doc_manifest.json` — 文档级契约，下游 `ragflow-kb-build` 消费
- `formal_handoff_manifest.json` — 包级审计清单
- `ragflow_ingest_plan.yaml` — 非机密入库计划
- `retrieval_hints.json` — 检索提示
- `quality_report.json` — 质量报告
- `chunk_profile_report.json` — chunk marker 统计

## 真实 PDF 扫描本的额外注意事项

- `inspect-source` 可能报告 `likely_scanned: true` 和 `pdf_text_sample_quality: binary_garbage`。只要 `file` 命令确认是 PDF，这通常是低文本密度/嵌入字体导致的，不影响 MinerU 转换。
- 扫描/中文 PDF 经 `mineru-fastapi` 后，图像资产可能使用 MinerU 生成的 `image-NNN_image.jpg` 名称或内容 hash 名称；`asset-upload-plan` 的语义别名启发式可能误报为 missing。先以 `inspect-handoff` 的 `missing_image_count` 为准，不要仅因 `asset-upload-plan` 的 `blocked` 状态就停止 live build。详情见 `references/asset-upload-plan-phantom-missing-image-pitfall.md`。

### chunk marker profile

| Profile | 边界类型 | 说明 |
|---|---|---|
| `chunk-markers` / `chunk-markers-conservative` | `heading` | 仅在 heading 前插入 |
| `chunk-markers-dense` | `heading`, `page`, `table`, `image` | 推荐常规使用 |
| `chunk-markers-ragflux-like` | `heading`, `page`, `table`, `image`, `list` | 最密集，用于迁移对比 |

### kb-build

标准入口：

```bash
python scripts/build.py \
  --doc-manifest ./handoff/doc_manifest.json \
  --kb-name "<kb-name>" \
  --profile ./templates/default-zh-512.json \
  --dry-run --json
```

一定要先 `--dry-run`，再决定 live build。

### Embedding model 验证

当已知部署目标 embedding model（如 `bge-m3`）时，dry-run 和 health-report 可做
model-match 检查：

```bash
# dry-run with model-specific profile template
python3 scripts/build.py \
  --doc-manifest ./handoff/doc_manifest.json \
  --kb-name "<kb-name>" \
  --profile ./templates/bge-m3-zh-512.json \
  --expected-embedding-model bge-m3 \
  --dry-run --json
```

检查 `embedding_model_check.status` 是否为 `match`。如果已有 kb_manifest /
parse_report / refresh_report，可跑 health-report 做更深检查。

**注意**：如果 KB 建于 model-neutral profile（如 `default-zh-512.json`），health-report
会报 info 级 `embedding_model_unknown`（`profile_embedding_model_missing`）。这是已知
gap，不是 rebuild blocker — 未来用 model-specific profile template 即可。

## 当前套件与 ragflux / ragflow-kb-ops 的取舍

| 维度 | 当前三 skill 套件 | ragflux | ragflow-kb-ops |
|---|---|---|---|
| 定位 | 新一代可移植管线：`doc-to-md` 准备文档、`kb-build` 构建/验证 KB、`query` 做检索验证 | 上一代本地 MinerU 预处理，退役候选 | 旧生产运维与 ES backfill / task 诊断，退役候选中的 ops 侧 |
| 入口 | `convert.py pipeline` / `build.py` / `query.py` | `python -m ragflux.cli.main run` | `chunking_runner.py` / `cli.py chunk-build` |
| MinerU backend | 多种，含 `mineru-fastapi` | `fast` (pipeline) / `accurate` (hybrid-auto) | 不解析 |
| Blackwell 兼容 | 优先用 `mineru-fastapi` capability probe；`pipeline` 稳定，high-accuracy 需看服务能力和 fallback | ⚠️ 旧本地 `accurate` 在 sm_120 高风险 | 无关 |
| 产物 | handoff bundle + 契约文件 + KB dry-run/build/report + query evidence reports | `doc.md` + `images/` + `quality_report.json` | 直接写 RAGFlow |
| 质量门禁 | 有 `PASS`/`PASS_WITH_REVIEW`/`BLOCKED` | 有 | 无原生 |
| benchmark/optimize | 内建完整 | 无 | 有独立脚本 |
| ES backfill / MySQL 直写 | 无 | 无 | 核心能力 |
| 推荐 | 默认主线；知识库准备先用 `doc-to-md` → `kb-build`，查询阶段再用 `ragflow-query` | 仅做退役前 fast-path 对照或保留包比较 | 仅做退役前 cross-test、生产诊断、ES/MySQL 补救；不作为新 KB 准备主线 |

**默认组合**：`ragflow-doc-to-md` 做解析与 handoff → `ragflow-kb-build` 做 dry-run / build / validation → KB 建成后用 `ragflow-query` 做检索验证。

**过渡组合**：退役完成前，`ragflux` + `ragflow-kb-ops` 可保留做历史基线。必要时也可以让 `ragflow-doc-to-md` 的 Markdown / handoff 输出与 `ragflow-kb-ops` 做交叉测试或生产诊断，但这属于退役过渡，不是新增知识库准备流程的推荐路径。

## Table 与 Chunk Marker 原子性

### doc-to-md 层面的保证

- `_table_protected_spans()` 会合并 HTML `<table>` 和 Markdown 表格范围
- 后处理规则（OCR 清理、CJK 空格修复）只作用于表格外部
- chunk marker 插入在表格开始行**之前**，不会落入表格内部
- 质量报告输出 `chunk_marker_table_atomicity`：
  - `ok: true` — 没有 marker 把 HTML table 切成不平衡 fragment
  - `ok: false` — 需要检查 `unbalanced_fragments`

### 关键限制

`doc-to-md` 保证**不在表格中间插入 marker**，但**不能保证 RAGFlow 的 chunker 不切表格**。

| 层级 | 谁负责 | 能否保证 |
|---|---|---|
| doc-to-md chunk marker | 插入 Markdown 边界标记 | ✅ 不落在表格中间 |
| RAGFlow chunker | 按 token/字符切分 | ⚠️ 超大表格仍可能被切 |

对表格重的文档，建议：
- 使用 `chunk-markers-dense` 或 `chunk-markers-ragflux-like`
- 在 RAGFlow 端使用较大的 `chunk_token_num`，或把表格作为独立 segment
- 入库后检查 `quality_report.json` 的 `chunk_marker_table_atomicity.ok`

## Pitfalls

### Pitfall #1: 混淆 dist 和 skills 两套路径

`skills/` 和 `dist/` 脚本主体同步，但 `_vendor` 与 `__pycache__` 差异可能导致运行结果不同。回归测试应跑 `packages/ragflow-skill-runtime/tests`，而不是直接比较两个 CLI 的输出。

### Pitfall #2: 把 Blackwell 与 high-accuracy 解析一刀切绑定

RTX 5070 Ti / 5080 / 5090 (sm_120) 上，旧 `ragflux accurate` 本地路径高风险。`ragflow-skills`
应优先用 `mineru-fastapi` 的 backend probe/warmup、`--table-quality auto|high` 和 fallback 报告判断，
不要只按 GPU 型号硬禁 high-accuracy；不确定时先用 `pipeline` 或 `adaptive --decision-only` 生成 review。

Observed compatibility warning: one MinerU FastAPI 3.2.1 field trial on a
Blackwell-class GPU failed when `hybrid-auto-engine` initialized, while the standard
`pipeline` backend completed. When this failure class appears, explicitly pin
`--mineru-fastapi-backend pipeline` and use backend warmup/fallback evidence before
retrying high-accuracy backends. See
`references/blackwell-mineru-fastapi-backend-pitfall.md` and the sanitized scanned-PDF
regression notes in `references/real-scanned-pdf-e2e-test-report.md`.

Observed environment quirk (2026-07-08): a local MinerU FastAPI service running on
`127.0.0.1:8888` exposed `protocol_version: 2` and a `/tasks` endpoint, but rejected
PDF uploads with `HTTP 400 Unsupported file type: html`. The port had previously been
used by a MinerU sync-style service. If the same port returns sync-style errors while
advertising v2, verify the actual service binary behind the port before assuming the
FastAPI backend is broken; check the unit files or health payload for the real backend.
This is a deployment/protocol identification issue, not a universal `mineru-fastapi`
limitation. See `references/mineru-fastapi-port-protocol-quirk.md`.

### Pitfall #3: 认为 chunk marker 能阻止 RAGFlow 切表格

chunk marker 是**提示性边界**，不是**硬约束**。RAGFlow 的 chunker 仍可能按 `chunk_token_num` 切超大表格。表格原子性需要结合 RAGFlow profile 和入库后验证。

### Pitfall #4: 把 ragflow-kb-ops 当成默认 kb-build 替代品

`ragflow-kb-ops` 与 `ragflux` 属于退役过渡线。它可以在退役完成前配合 `ragflow-doc-to-md` 做 cross-test、生产诊断或 ES/MySQL 补救，但新增知识库准备应优先走 `ragflow-kb-build`。其 `chunk-build` 单次处理 ≥5 文件可能超时（约 600 秒），导致 KB 碎片；大批量应分步：RAGFlow API 逐文件上传 → 一次性触发 parse。

### Pitfall #5: 混淆 adaptive 命令的 inspect-source / decision-only 参数

`inspect-source` 不是 `--output`，而是 `--report-json` 和 `--report-md`：

```bash
python scripts/convert.py inspect-source \
  --input ./raw \
  --report-json ./run/document_features.json \
  --report-md ./run/document_features.md
```

`adaptive --decision-only` 没有 `--mode decision-only`，参数就是 `--decision-only`：

```bash
python scripts/convert.py adaptive \
  --input ./raw \
  --output ./run \
  --decision-only \
  --adaptive-policy table-atomic
```

### Pitfall #6: 认为 base64 内嵌图片会被语义化重命名

`semantic_rename_markdown_images` 只处理**本地不透明 hash 文件名**（如 `images/6a1b2c3d...png`）。
**base64 内嵌图片**（`data:image/png;base64,...`）不会触发重命名，因为没有独立文件路径。

### Pitfall #7: 把 adaptive pipeline 的决策报告等同于强制配置

`adaptive --decision-only` 输出 `pipeline_decision.json`，但 pipeline 执行时仍受显式参数覆盖。
要让 `adaptive` 自动执行推荐配置，用完整命令；要人工 review，用 `--decision-only` 读 `recommendation` 字段后再决定。

## 常用验证命令

```bash
# 跑完整回归测试并输出到日志
.venv/bin/python -m pytest packages/ragflow-skill-runtime/tests -v --tb=short \
  > ragflow-skills-test.log 2>&1

# 检查 skills/ 与 dist/ 脚本差异
diff -r skills/ragflow-doc-to-md/scripts dist/ragflow-doc-to-md/scripts
diff -r skills/ragflow-kb-build/scripts dist/ragflow-kb-build/scripts

# 快速测试 chunk marker 行为（Python 单行）
.venv/bin/python -c "
from ragflow_skill_runtime.doc_postprocess import postprocess_markdown_text
text = '| A | B |\n| --- | --- |\n' + '\n'.join([f'| {i} | {i} |' for i in range(20)])
out, _ = postprocess_markdown_text('# T\n\n' + text + '\n\n## Next\n', profile='chunk-markers-dense')
print(out.count('<!-- chunk -->'))
"
```

## Cross-refs

- Skill: `ragflux` — 本地 MinerU 快速预处理管线
- Skill: `ragflow-doc-to-md` — 当前主线：文档到 Markdown handoff
- Skill: `ragflow-kb-build` — 当前主线：handoff 到 RAGFlow KB dry-run / build / validation
- Skill: `ragflow-query` — 当前主线：KB 建成后的检索、路由和证据验证
- Skill: `ragflow-kb-ops` — legacy/ops：与 `ragflux` 配合的生产运维、ES backfill、task 诊断；退役过渡期也可与 `doc-to-md` 做交叉测试
- Skill: `ragflow-smart-query` — legacy：旧检索入口，能力迁移到 `ragflow-query`
- Skill: `rag-systems` — RAG 系统背景与部署总览
- Reference: `references/ragflow-skills-table-atomicity.md` — chunk marker / table 原子性实测记录
- Reference: `references/real-scanned-pdf-e2e-test-report.md` — 真实扫描 PDF 端到端测试记录
- Reference: `references/ragflow-skills-vs-ragflux-vs-kb-ops.md` — 三套管线对比表
- Reference: `references/ragflow-skills-adaptive-pipeline-guide.md` — adaptive pipeline 端到端使用指南
- Reference: `references/blackwell-mineru-fastapi-backend-pitfall.md` — Blackwell GPU 上 MinerU high-accuracy backend 陷阱
- Reference: `references/ragflow-doc-to-md-table-parameter-impact.md` — 参数调整对表格解析质量的影响与决策树
- Reference: `references/mineru-fastapi-port-protocol-quirk.md` — 本地 MinerU FastAPI 端口协议识别陷阱
- Reference: `references/ragflow-skills-e2e-test-checklist.md` — Hermes 端到端测试检查清单 + docs/N checklist 关闭工作流（refresh/embedding/routing 三类验证链与 gating 逻辑）
- Reference: `references/model-provider-404-false-alarm.md` — RAGFlow model-provider API 全 404 不是 embedding 服务故障；TEI + tei-embed-proxy 生产架构验证
