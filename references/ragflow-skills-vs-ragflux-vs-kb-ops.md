# ragflow-skills vs ragflux vs ragflow-kb-ops 对比

**日期**：2026-07-06

## 一句话结论

- `ragflow-skills`：默认首选，新一代可移植 handoff 管线
- `ragflux`：仅在旧本地 MinerU fast 模式临时使用
- `ragflow-kb-ops`：生产运维、ES backfill、task 诊断、MySQL 直写

## 详细对比

| 维度 | ragflow-skills | ragflux | ragflow-kb-ops |
|---|---|---|---|
| 定位 | 新一代可移植 handoff 管线 | 上一代本地 MinerU 预处理管线 | 生产级 RAGFlow 运维工具集 |
| 入口 | `scripts/convert.py pipeline`<br>`scripts/build.py` | `python -m ragflux.cli.main run` | `scripts/chunking_runner.py`<br>`cli.py chunk-build` |
| MinerU 支持 | `mineru-cli`, `mineru`, `mineru-fastapi`, `mineru-v4` / `mineru-platform`, `mineru-sync`, `remote` | `fast` (pipeline)<br>`accurate` (hybrid-auto) | 不直接解析，消费上游 MD |
| Blackwell 兼容性 | `mineru-fastapi` capability probe + fallback；`pipeline` 稳定，high-accuracy 需看服务能力 | ⚠️ 旧本地 `accurate` 在 sm_120 高风险 | 无关 |
| 产物 | `doc_manifest.json`<br>`formal_handoff_manifest.json`<br>`ragflow_ingest_plan.yaml`<br>`retrieval_hints.json` | `doc.md`<br>`images/`<br>`quality_report.json`<br>`manifest.json` | 直接写 RAGFlow dataset/chunk |
| 质量门禁 | `PASS` / `PASS_WITH_REVIEW` / `BLOCKED` | 同左 | 无原生门禁 |
| 回归测试 | 515 项 | 少量 | 少量 |
| benchmark/optimize | 内建完整 | 无 | 有独立脚本 |
| ES backfill / MySQL 直写 | 无 | 无 | 核心能力 |
| 可移植性 | 高（handoff bundle） | 中（依赖本地 MinerU） | 低（绑定 RAGFlow 实例） |
| 推荐度 | ⭐ 默认首选 | 临时 fallback | 生产运维/补数据/诊断 |

## 推荐组合

```
PDF/Office/MD → ragflow-skills (doc-to-md) → handoff bundle
                                              ↓
ragflow-kb-ops (chunk-build/ES backfill) → RAGFlow KB
                                              ↓
                         ragflow-smart-query (检索入口)
```

## 何时切换

| 场景 | 推荐 |
|---|---|
| 新文档入库 | `ragflow-skills` |
| 表格重、需要 MinerU high-accuracy 但 GPU 是 Blackwell | 先用 `ragflow-skills adaptive --decision-only` 或 backend probe/warmup；不确定时回到 `mineru-fastapi` `pipeline` backend |
| 表格重、希望使用 MinerU 公共 v4 platform | 显式选择 `--backend mineru-v4 --table-quality high`；该路径映射到 `model_version=vlm`，不是 FastAPI backend |
| 已有旧 ragflux 脚本，且仅需本地 fast 模式 | 可继续用 `ragflux`，但规划迁移 |
| 需要 ES 关键词回填、task 队列诊断、MySQL 修复 | `ragflow-kb-ops` |
| 需要批量重建 KB 且文件 ≥5 | 用 `ragflow-kb-ops` 分步 API，避免 chunk-build 超时 |
