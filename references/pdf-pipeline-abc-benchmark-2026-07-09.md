# PDF 三管线 A/B/C 基准对比 (2026-07-09)

同一 PDF 文档（Palantir 实战指南，8.4MB，316 页中文电子书）通过三条管线入库，对比检索质量与文本干净度。

## 三管线定义

| 管线 | 路径 | 工具链 |
|:--|:--|:--|
| **A** | RAGFlow native parser 直接入库 | `ragflow-kb-ops` → `chunk-build` |
| **B** | 手动 MinerU → 手动 passthrough → kb-build | MinerU CLI → `convert.py --mode passthrough` → `build.py` |
| **C** | skill 原生全链路 | `convert.py pipeline --backend mineru-fastapi --table-quality high` → `build.py` |

## KB 元数据

| 维度 | A | B | C |
|:--|:--|:--|:--|
| KB ID | c66294dc... | 9fbfdd18... | 94a0d624... |
| Chunks (文本) | 310 | 326 | 256 |
| Chunks (图片) | 0 | 0 | 88 |
| language | Chinese ✅ | English ❌→已修 | English ❌→已修 |
| chunk_token_num | 768 | 512 | 768 |
| Quality Gate | N/A | BLOCKED | PASS_WITH_REVIEW |
| 图片提取 | 0 | 0 | 88 张 |
| 表格提取 | 0 | 0 | 30 (14 MD + 16 HTML) |

## 检索质量（10 条查询，Top-1/Top-3/Top-5 avg similarity）

| 指标 | A | B | C |
|:--|:--:|:--:|:--:|
| Top-1 avg | **0.473** | 0.460 | 0.460 |
| Top-3 avg | **0.449** | 0.444 | 0.444 |
| Top-5 avg | **0.440** | 0.429 | 0.429 |
| Top-1 胜场 (A vs C) | **9/10** | — | 1/10 |

### 逐条对比 (A vs C)

| Query | A | C | Δ | 胜者 |
|:--|:--:|:--:|:--:|:--:|
| 核心产品 | 0.519 | 0.521 | +0.002 | C |
| Gotham军事 | 0.450 | 0.444 | −0.006 | A |
| Foundry整合 | 0.552 | 0.527 | −0.025 | A |
| 本体论 | 0.533 | 0.515 | −0.018 | A |
| AIP功能 | 0.507 | 0.504 | −0.002 | A |
| 诺华案例 | 0.484 | 0.452 | −0.032 | A |
| 保险AI | 0.317 | 0.312 | −0.005 | A |
| 构建本体论 | 0.513 | 0.505 | −0.008 | A |
| 商业模式 | 0.542 | 0.509 | −0.033 | A |
| 福特制造 | 0.314 | 0.308 | −0.006 | A |

## 文本质量

| 维度 | A | B | C |
|:--|:--|:--|:--|
| 噪声 chunks | 有（页眉"扫码关注"混入） | 零 | 零 |
| chunk markers | 无 | 326/326 | 256/256 |
| 图片标注 `<details>` | 无 | 无 | 有 |

## 图片上传（C 管线补跑）

C 管线 build 后需单独执行图片上传：
1. `asset-upload-plan --doc-manifest` → 生成 plan（注意 DEFECT-001 可能误报 blocked）
2. `image-ingestion-execute --execute --asset-upload-plan --dataset-id --confirm-planned-count 88` → 88/88 成功

## D 管线：Delimiter 模式验证

C 管线的 `default-zh-768` profile 使用 naive chunker 按 token 数切分，完全忽略了 829 个 `<!-- chunk -->` 语义边界标记。D 管线测试 `profile_suggestions.json` 推荐的 `table-atomic-zh-4096`（实际 RAGFlow 限制 `chunk_token_num` ≤ 2048，使用 1024）配合 `delimiter` 字段让 RAGFlow 在 `<!-- chunk -->` 处断开。

### D 配置

```json
{
  "profile_id": "table-atomic-zh-delimiter",
  "chunk_method": "naive",
  "parser_config": {
    "chunk_token_num": 1024,
    "delimiter": "`<!-- chunk -->`",
    "auto_keywords": 0,
    "auto_questions": 0,
    "__language__": "Chinese"
  }
}
```

> **Pitfall**: RAGFlow API `chunk_token_num` 上限为 2048（非文档建议的 4096）。
> `language` 字段不能放在 `parser_config` 内，必须在 dataset 顶层。
> `build.py` 在同名 KB 已存在时会报 `could not extract dataset id`，需先手动 `POST /datasets` 创建 KB 再上传文档。

### 四管线完整对比

| 指标 | A (chunk-build) | B (manual MinerU) | C (skill naive-768) | **D (skill delimiter)** |
|:--|:--:|:--:|:--:|:--:|
| Chunks | 310 | 326 | 256 | **210** |
| Top-1 avg | **0.473** | 0.460 | 0.460 | **0.468** |
| Top-3 avg | **0.449** | 0.444 | 0.444 | **0.445** |
| Top-1 wins (vs A) | — | 0/10 | 1/10 | **3/10** |

### D 管线亮点

delimiter 模式在 3 条 query 上击败 A：

| 查询 | A | D | Δ |
|:--|:--:|:--:|:--:|
| 商业模式和竞争力 | 0.542 | **0.554** | +0.013 |
| 诺华药物研发 | 0.484 | **0.490** | +0.005 |
| 保险行业AI | 0.317 | **0.323** | +0.006 |

这三条都是**多段落、跨章节**查询——delimiter 在语义边界处切断，把相关内容聚合在同一 chunk 内。

### D 管线短板

D 在两个 query 上大幅落后 A：Foundry整合（−0.025）和构建本体论（−0.027）——`<!-- chunk -->` 标记把最优 chunk 切成两半，而 A 的 768-token 窗口刚好完整覆盖。`chunk_token_num=768` + delimiter 可能在保持语义边界的同时避免过度碎片化。

## 结论

- **A 检索精度最优**：chunk 数最多（310），语义匹配精确度最高
- **D 是 skill 管线的最佳配置**：210 chunks 追到 A 的 98.9%（Δ=−0.005），比 C 少用 46 chunks 但 sim 更高
- **delimiter 模式明确有效**：D vs C 提升 +0.008，证明了 chunk markers 的语义边界价值
- **C 文本质量最优**：零噪声 + 88 图片 + 30 表格 + 完整审计 sidecar
- **C 检索精度略低**：约 −2.8% Top-1 sim，源于 chunk 更少更宽（256 vs 310）
- **B 全面不如 A 和 C**：检测质量低 + 配置错误（language=English, chunk_size=512）
- **language=English 是 kb-build 已知行为**：创建 KB 后需 `PUT /datasets/{id}` 手动修正
- **chunk_token_num 上限 2048**：RAGFlow API 强制限制，profile_suggestions 的 4096 建议不可直接使用

## 测试 KB（保留）

- `kb:test-pdf-A-naive-palantir` — A 管线
- `kb:test-pdf-B-mineru-palantir` — B 管线
- `kb:test-pdf-C-skill-palantir` — C 管线（含 88 张图片）
- `kb:test-pdf-D-delimiter-palantir` — D 管线（delimiter 模式）

## 复现方法

```bash
# A: chunk-build (ragflow-kb-ops)
python3 cli.py chunk-build --kb-name "kb:test-pdf-A-naive-palantir" --file <PDF>

# B: manual MinerU → passthrough → kb-build
# (MinerU CLI conversion then convert.py passthrough then build.py)

# C: full skill pipeline
python3 scripts/convert.py pipeline \
  --input <PDF> \
  --output /tmp/handoff \
  --backend mineru-fastapi \
  --mineru-base-url http://localhost:8888 \
  --mineru-language ch \
  --table-quality high \
  --mineru-asset-mode markdown_assets \
  --postprocess-profile chunk-markers-dense

python3 scripts/build.py \
  --doc-manifest /tmp/handoff/doc_manifest.json \
  --kb-name "kb:test-pdf-C-skill-palantir" \
  --profile /tmp/profile-zh-768.json \
  --base-url http://localhost:9380 \
  --api-key <KEY> \
  --output /tmp/kb_manifest.json

# Image upload (separate step)
python3 scripts/build.py asset-upload-plan \
  --doc-manifest /tmp/handoff/doc_manifest.json \
  --report-json /tmp/asset_plan.json

python3 scripts/build.py image-ingestion-execute \
  --execute \
  --asset-upload-plan /tmp/asset_plan.json \
  --dataset-id <KB_ID> \
  --confirm-dataset-id <KB_ID> \
  --confirm-planned-count 88
```

### D: delimiter mode (manual KB creation required)

```bash
# RAGFlow chunk_token_num max=2048, language must be top-level (not in parser_config)
# build.py fails on duplicate KB names — create manually first
curl -s -X POST "http://localhost:9380/api/v1/datasets" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"kb:test-pdf-D","embedding_model":"text-embedding-v4@Tongyi-Qianwen","parser_config":{"chunk_token_num":1024,"delimiter":"`<!-- chunk -->`","auto_keywords":0}}'

curl -s -X PUT "http://localhost:9380/api/v1/datasets/$KB_D" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" -H "Content-Type: application/json" \
  -d '{"language":"Chinese"}'

curl -s -X POST "http://localhost:9380/api/v1/datasets/$KB_D/documents" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" \
  -F "file=@$MD;type=text/markdown"

curl -s -X POST "http://localhost:9380/api/v1/datasets/$KB_D/chunks" \
  -H "Authorization: Bearer $RAGFLOW_API_KEY" -H "Content-Type: application/json" \
  -d "{\"document_ids\":[\"$DOC_ID\"]}"
```
