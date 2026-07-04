# 19. RAGFlux 能力补齐设计与开发计划

状态：P0/P1/P2 已实现并通过离线验证；迁移指引与 RAGFlux 退役门禁已补齐；代表性 PDF 已完成真实 MinerU FastAPI field-trial 和一次性 RAGFlow KB live E2E
日期：2026-07-02；最后更新：2026-07-03
适用范围：`ragflow-doc-to-md` 作为正式文档转换 skill，配合 `ragflow-kb-build`
和 `ragflow-query` 替代 RAGFlux 的文档预处理、入库和检索验证能力。

## 第一部分：问题客观描述

### 1.1 背景

OpenClaw 对同一份 PDF 执行了 RAGFlux 与 `ragflow-doc-to-md` 对比测试。测试结果显示：

- 两者文本抽取质量基本一致，中文识别和表格解析均可用。
- `ragflow-doc-to-md` 复用常驻 MinerU FastAPI 服务，耗时显著低于 RAGFlux 冷启动路径。
- `ragflow-doc-to-md` 质量门被 `image_missing` 阻断，Markdown 引用了图片但本地未落地图片文件。
- RAGFlux 产物更完整，包含图片目录、chunk 标记、`retrieval_hints.json` 和 RAGFlow 入库配置建议。

这说明当前差距不在 MinerU 文本抽取能力，而在三 skill 套件对 RAGFlux 一条龙产物链的默认集成程度。

### 1.2 三 skill 当前分工

目标架构不是让单个 skill 完整复制 RAGFlux，而是拆成流水线：

| 阶段 | 负责 skill | 当前职责 |
| --- | --- | --- |
| 文档转换 | `ragflow-doc-to-md` | PDF/Office/图片转 Markdown，写出 `doc_manifest.json` 和 `quality_report.json` |
| Handoff 富化 | `ragflow-doc-to-md` | `postprocess`、`segment-plan`、`split`、`package --rich` 等离线富化命令 |
| 上库与解析 | `ragflow-kb-build` | 使用 profile 创建 KB、上传 Markdown、触发解析、等待解析完成，生成 `kb_manifest.json` |
| 入库前后质检 | `ragflow-doc-to-md` / `ragflow-kb-build` | doc quality gate、dry-run、smoke/regression/benchmark validation、parse/health/topology reports |
| 检索验证 | `ragflow-query` | direct/agentic 查询、route/report、assistant profile 和 test plan review |

因此，`ragflow-kb-build` 确实接管了入库、解析 profile、KB 级验证和后段诊断，但没有接管原始文档转换和转换产物富化。

### 1.3 已核实的真实缺口

#### 1.3.1 MinerU FastAPI 图片资产未落地

当前 `mineru-fastapi` 路径是 Markdown-first：

- `return_md: true`
- `return_images: false`
- `return_content_list: false`
- `return_middle_json: false`
- `response_format_zip: false`

结果阶段只抽取 Markdown 字符串，没有下载或保存远程图片资产。若 MinerU 返回的 Markdown 包含
`![...](images/xxx.png)` 之类本地图片引用，`quality_report.json` 会检查这些相对路径是否真实存在；
文件不存在时产生 `image_missing` error，并使 `quality_gate.status` 变为 `BLOCKED`。

这是当前生产替代 RAGFlux 的 P0 缺口。

#### 1.3.2 Rich handoff 能力存在，但未并入默认转换路径

`retrieval_hints.json` 不是 RAGFlux 独有能力。当前 `ragflow-doc-to-md package --rich`
已经能生成：

- `metadata.json`
- `artifact_index.json`
- `profile_suggestions.json`
- `retrieval_hints.json`
- `assistant_profile.json`
- `assistant_test_plan.json`
- `package_readme.md`

但普通 `convert` 命令默认只输出 `documents/*.md`、`doc_manifest.json`、`quality_report.json`
和运行报告。因此只跑一次 `convert` 的 host agent 会误判为没有 hints 能力。

#### 1.3.3 Chunk marker 能力存在，但需要显式 postprocess

`<!-- chunk -->` 标记由 `postprocess --profile chunk-markers` 插入，规则是保守地在一级到三级标题边界前插入标记。
普通 `convert` 不会自动修改 Markdown，默认 `postprocess` profile 也是 `safe`。

因此，chunk marker 的缺口不是完全未实现，而是未形成端到端默认工作流。

#### 1.3.4 RAGFlow 入库配置建议没有等价产物

当前三 skill 使用两类配置：

- host-agent 私有运行配置：`templates/ragflow-config.example.yaml` 复制到私有路径后设置 `RAGFLOW_CONFIG`。
- KB 解析 profile：`ragflow-kb-build --profile ...` 或 `profile recommend` 生成的 profile JSON。

但 RAGFlux 风格的 handoff 内 `ragflow_config.yaml` 配置建议并不存在。`profile_suggestions.json`
只是解析 profile 建议，不是完整入库执行建议，也不应混入真实 RAGFlow API key 或私有 endpoint。

#### 1.3.5 `ragflow-kb-build` 只能消费 hints，不能生成 hints

`ragflow-kb-build topology advise`、`topology split-plan` 和 `activation-plan` 可以消费
`retrieval_hints.json`。但是 hints 的生成职责属于 `ragflow-doc-to-md package --rich`，不是
`ragflow-kb-build`。

如果转换阶段没有生成 rich handoff，后续 KB 拓扑建议只能依赖 Markdown 和 metadata，不能得到完整的
section boundary、keyword、question、preferred boundary 等信号。

### 1.4 问题分级

| 等级 | 问题 | 影响 |
| --- | --- | --- |
| P0 | `mineru-fastapi` 图片未落地 | 质量门 BLOCKED，无法作为默认入库路径替代 RAGFlux |
| P1 | 缺少一键端到端 rich handoff 工作流 | host agent 容易只跑 `convert`，漏掉 postprocess 和 package |
| P1 | 缺少非密钥型 RAGFlow 入库建议 sidecar | RAGFlux 使用习惯迁移不完整，用户难以从 handoff 直接进入上库 |
| P1 | rich handoff 与 `kb-build inspect-handoff/topology` 串联不够显式 | 三 skill 能力存在但不易被 Hermes/OpenClaw 自动正确调用 |
| P2 | hints 质量依赖 Markdown 标题和 artifact index | 图片资产未落地时 image artifacts 不完整，章节边界也受 MinerU 标题质量影响 |

## 第二部分：改善方案

### 2.1 总体目标

把 `ragflow-doc-to-md` 从“快速 Markdown 转换器”升级为“可替代 RAGFlux 前处理段的正式 handoff 生成器”，同时保留三 skill 分工：

- `ragflow-doc-to-md` 负责转换、图片资产落地、Markdown 后处理、rich handoff 生成和非密钥入库建议。
- `ragflow-kb-build` 负责使用 handoff 与 profile 执行入库、解析、KB 级验证和拓扑/激活建议。
- `ragflow-query` 负责检索验证、assistant profile review 和 test plan review。

### 2.2 P0：补齐 MinerU FastAPI 图片资产落地

`mineru-fastapi` 后端应支持可控的资产保存模式：

```text
markdown_only     当前默认兼容模式，只保存 Markdown
markdown_assets   保存 Markdown 和 Markdown 引用的图片资产
structured_assets 保存 Markdown、图片、content_list、middle_json 等结构化 sidecar
```

首轮建议实现 `markdown_assets`，不直接扩大到完整模型输出：

- 请求 MinerU 时启用 `return_images`，必要时启用 zip 响应或结果中图片字段。
- 从 `/tasks/{task_id}/result` 识别 Markdown、图片列表、图片下载 URL、base64 图片或 zip 内容。
- 将图片保存到 `documents/images/<document-stem>/...` 或等价稳定目录。
- 重写 Markdown 图片引用为 handoff 内相对路径。
- 更新 `doc_manifest.json`，记录资产或资产 sidecar 引用。
- 更新 `artifact_index.json`，让 rich handoff 能识别 image artifacts。
- 更新 `runtime_report.json` 的 `asset_policy`，记录 requested/saved/manifest_assets。
- 质量门在图片成功落地后不再因同一引用报 `image_missing`。

兼容要求：

- 默认仍可保留 `markdown_only`，但正式 Hermes/OpenClaw 推荐配置应使用 `markdown_assets`。
- 任何远程 URL、API key、原始路径和临时文件路径都必须被 redaction 报告覆盖。
- 图片文件名需要稳定、去危险字符、避免路径穿越和同名覆盖。
- 清理临时 zip 或下载缓存，失败时不得留下半成品污染 handoff。

### 2.3 P1：新增端到端 handoff 富化工作流

当前需要手工串联：

```bash
python scripts/convert.py --input ./raw --output ./handoff --backend mineru-fastapi
python scripts/convert.py postprocess --doc-manifest ./handoff/doc_manifest.json --profile chunk-markers --output ./handoff-rich
python scripts/convert.py package --handoff ./handoff-rich --rich
```

建议新增一个显式 orchestration surface，避免 host agent 漏跑步骤。可选设计：

1. 在 `convert` 增加 opt-in 参数：

```bash
python scripts/convert.py \
  --input ./raw \
  --output ./handoff \
  --backend mineru-fastapi \
  --asset-mode markdown_assets \
  --postprocess-profile chunk-markers \
  --package-rich
```

2. 或新增子命令：

```bash
python scripts/convert.py pipeline \
  --input ./raw \
  --output ./handoff \
  --backend mineru-fastapi \
  --asset-mode markdown_assets \
  --postprocess-profile chunk-markers \
  --package-rich
```

推荐采用第二种，原因是 `convert` 保持现有窄职责，`pipeline` 明确表示会执行多步写入。

`pipeline` 应输出统一摘要：

- `doc_manifest`
- `quality_report`
- `runtime_report`
- `postprocess_report`
- `handoff_package`
- `retrieval_hints`
- `ragflow_ingest_plan`
- `quality_gate.status`

### 2.4 P1：生成非密钥型 RAGFlow 入库建议 sidecar

为替代 RAGFlux 的 `ragflow_config.yaml` 使用体验，新增一个明确非密钥、非运行配置的 sidecar：

```yaml
schema: ragflow_ingest_plan_v1
created_at: "..."
handoff:
  doc_manifest: doc_manifest.json
  retrieval_hints: retrieval_hints.json
recommended_build:
  command: ragflow-kb-build
  profile: profile_suggestions.json
  parser_profile:
    chunk_method: naive
    chunk_size: 512
    chunk_overlap: 64
  quality_gate_required: true
  allow_blocked_default: false
recommended_validation:
  smoke: true
  regression: optional
  benchmark: optional
notes:
  - "No RAGFlow endpoint or API key is stored in this handoff."
```

默认文件名建议使用 `ragflow_ingest_plan.yaml`。如果必须兼容 RAGFlux 用户习惯，可额外提供 opt-in alias
`ragflow_config.yaml`，但文档必须明确它不是 host-agent 私有运行配置，不能写入 API key 或 endpoint。

### 2.5 P1：强化 Hermes/OpenClaw 调用指引

公开 skill 文本和 onboarding prompt 应明确：

- 快速预览：只跑 `convert`。
- 正式入库前处理：跑 `pipeline` 或等价三步命令。
- 如果选择远程 MinerU FastAPI，生产默认使用 `asset-mode: markdown_assets`。
- `retrieval_hints.json` 由 `ragflow-doc-to-md package --rich` 生成。
- `ragflow-kb-build` 消费 `doc_manifest.json`、profile、metadata 和 optional `retrieval_hints.json`。
- `ragflow-query` 消费 `assistant_profile.json` 和 `assistant_test_plan.json` 做检索/assistant review。

### 2.6 P2：提升 retrieval hints 质量

当前 `retrieval_hints.json` 主要基于 Markdown 标题、表格、图片引用、数值候选和 quality risk。
后续可以增强：

- 从 MinerU `content_list` 或 `middle_json` 中提取页码、版面块、标题层级和图片上下文。
- 将图片 caption、周边段落和页码写入 `image_artifacts`。
- 在 `preferred_boundaries` 中融合 chunk markers、标题层级和页码边界。
- 对中文工业目录、产品手册、论文、合同等文档类型增加确定性 keyword/question 模板。

这些增强不应依赖 LLM，也不应自动修改 RAGFlow assistant 设置。

### 2.7 验收标准

替代 RAGFlux 前处理段的最小通过标准：

- 对包含图片引用的 MinerU FastAPI 结果，`documents/images/...` 有对应文件。
- `quality_gate.status` 不再因已落地图片报 `image_missing`。
- 一条正式工作流能产出 Markdown、图片、`doc_manifest.json`、quality/runtime/postprocess 报告、
  `retrieval_hints.json` 和非密钥入库建议 sidecar。
- `ragflow-kb-build --dry-run` 能消费该 handoff，默认拒绝 BLOCKED，PASS 时可进入上库。
- 所有报告和 sidecar 通过 redaction/hygiene 检查，不包含真实密钥、私有 endpoint、个人路径或临时目录。
- Consumer acceptance 和 strict-vendor platform smoke 覆盖正式工作流。

## 第三部分：修正开发任务清单和计划

### 3.1 P0：MinerU FastAPI 图片资产落地

- [x] 设计 `asset-mode` CLI/config 字段，至少支持 `markdown_only` 和 `markdown_assets`。
- [x] 扩展 `mineru-fastapi` request fields，在 `markdown_assets` 下请求图片资产。
- [x] 调研并固化 MinerU FastAPI v2 图片返回形态：离线覆盖 zip、绝对 URL、相对 URL、base64、结果字段；真实服务若返回新的私有字段形态，纳入 field-trial 观察。
- [x] 实现结果解析器，能从 Markdown 结果和图片资产结果中建立引用映射。
- [x] 实现安全图片写出：稳定目录、文件名清理、重复名处理、sha256、大小限制、路径穿越防护和 staging 写入失败清理。
- [x] 实现 Markdown 图片引用重写，确保引用指向 handoff 内相对路径。
- [x] 扩展 `runtime_report.json` 的 `asset_policy`，记录 requested/saved/manifest_assets/reason，且公开资产记录只保留本地 path、sha256、bytes。
- [x] 扩展 `doc_manifest.json`，记录图片资产清单和关联 Markdown。
- [x] 添加 unit tests：zip 图片、绝对 URL 图片、相对 URL 图片、base64 图片、危险路径、重复文件名、大小限制和鉴权下载。
- [x] 添加 CLI fake MinerU FastAPI 测试：Markdown 引用图片且图片落地后 quality gate PASS。
- [x] 添加 redaction / hygiene 覆盖，确认 endpoint、token、临时路径和原始路径不进入公开运行报告或 release hygiene finding。

P0 实现说明：

- 新增 `--mineru-asset-mode markdown_assets`、`MINERU_ASSET_MODE` 和 `mineru.asset_mode`。
- `markdown_assets` 下会把 MinerU FastAPI 返回的图片保存到 `documents/images/<markdown-stem>/...`，并重写 Markdown 图片引用。
- 图片资产写入使用 staging 目录，中途失败不会留下半成品图片目录。
- 对 MinerU 返回的哈希/opaque 图片文件名执行 semantic rename，Markdown 主引用、
  `doc_manifest.json` 和 `runtime_report.json.asset_policy` 同步指向可读文件名；sha256
  继续保留在公开 manifest/sidecar 中作为完整性审计字段。
- `doc_manifest.json` 的 document entry 可包含 `assets.images[]`，每项记录 `documents/...` 相对路径、sha256 和 bytes。
- `runtime_report.json` 的 `asset_policy.saved.image_assets[]` 只保留可公开的本地资产信息，不记录原始下载 URL、API key 或服务端路径。
- 默认兼容模式仍是 `markdown_only`；Hermes/OpenClaw 正式入库配置推荐 `markdown_assets`。

### 3.2 P1：端到端 pipeline 工作流

- [x] 决定采用 `convert.py pipeline` 子命令或 `convert --package-rich` 参数组合。
- [x] 实现 pipeline 执行顺序：convert -> postprocess -> package rich -> ingest plan。
- [x] 默认 pipeline 使用非破坏性写入，不原地改写输入 Markdown。
- [x] 支持 `--postprocess-profile safe|ocr|chunk-markers`，正式入库推荐 `chunk-markers`。
- [x] pipeline 默认生成 rich handoff。
- [x] 输出统一 JSON 摘要，列出所有生成物路径和 gate 状态。
- [x] 添加失败恢复策略：convert 失败不执行后续步骤；postprocess 失败不伪造 package；package 失败保留前序报告。
- [x] 添加 CLI tests，覆盖 pipeline 成功、非密钥 alias 和危险 sidecar 路径拒绝；quality BLOCKED / postprocess failure / package failure 仍作为后续回归扩展。
- [x] 更新 `SKILL.md` 和 host-agent prompt，把正式入库前处理改为 pipeline。

### 3.3 P1：RAGFlow 入库建议 sidecar

- [x] 定义 `ragflow_ingest_plan_v1` schema。
- [x] 从 `profile_suggestions.json`、`retrieval_hints.json`、quality gate 和 doc manifest 生成 ingest plan。
- [x] 明确 sidecar 不包含 RAGFlow base URL、API key 或 host-agent 私有配置路径。
- [x] 输出推荐 `ragflow-kb-build` dry-run/build 命令模板，命令中使用占位符。
- [x] 可选支持 `--ragflow-config-alias ragflow_config.yaml`，仅作为非密钥兼容 alias。
- [x] 添加 schema identity 和 release hygiene 覆盖。
- [x] 添加 consumer acceptance 检查，验证 pipeline 产物可进入 `ragflow-kb-build --dry-run`。

### 3.4 P1：`ragflow-kb-build` 串联验证

- [x] 增强 `inspect-handoff`，明确报告 rich sidecars 是否齐全、图片资产是否缺失、quality gate 是否可上库。
- [x] 在 `topology advise` 报告中区分“未提供 retrieval hints”和“hints 提供但内容为空”。
- [x] 在 `activation-plan` 中加入 ingest plan 输入，核对 doc manifest、retrieval hints、profile 和 route-test readiness。
- [x] 增加 dry-run fixture：pipeline 产物 -> `ragflow-kb-build --dry-run`。
- [x] 增加 platform smoke：strict-vendor 环境跑完整离线 pipeline 和 kb-build dry-run。

P1 串联验证实现说明：

- `inspect-handoff` 报告新增 `ingestion_readiness`、`sidecar_summary` 和 `assets.images`，能直接指出 rich sidecar 完整性、pipeline sidecar 完整性、图片资产缺失和 quality gate 是否允许进入 live build。
- `topology advise` 报告新增 retrieval hints summary，明确区分未提供 hints、提供但为空、以及 section/keyword/question/image/table 等信号数量。
- `activation-plan` 新增可选 `--ingest-plan` 和 `--profile`，可把 `ragflow_ingest_plan.yaml` 与实际传入的 `doc_manifest.json`、`retrieval_hints.json`、reviewed profile 和 route-test readiness 做离线一致性检查。

### 3.5 P2：Retrieval hints 质量增强

- [x] 引入可选 `content_list` / `middle_json` sidecar 解析，不改变默认无 LLM 策略。
- [x] 将页码、标题层级、图片 caption、表格上下文写入 hints。
- [x] 对中文产品目录、工业手册、论文等文档类型补充 deterministic question/keyword 模板。
- [x] 添加 fixture，验证 section boundaries、preferred boundaries、image artifacts 和 numeric candidates。
- [x] 通过 benchmark/sample 文档评估 hints 对 topology、route-test starter 和 assistant test plan 的改善。

P2 retrieval hints 离线增强实现说明：

- `retrieval_hints.json` 继续使用 `ragflow_retrieval_hints_v1` schema，不破坏现有消费者。
- `section_boundaries` 现在可带 `page_start`、`page_end` 和原有 heading level。
- `image_artifacts` 会合并 artifact index 与 Markdown 图片引用，补充 alt/caption、就近标题、页码、行号、上下文片段和本地文件存在性。
- `table_artifacts` 会从 Markdown 表格块生成表格上下文，包含就近标题、页码、行范围、行数和 header preview。
- `preferred_boundaries` 除 heading boundary 外，还会吸收 page boundary 和 `<!-- chunk -->` boundary。
- `numeric_candidates` 追加页码；`keyword_candidates` 和 `question_candidates` 增加中文产品目录、工业手册、论文以及英文 product/manual/paper 的确定性模板。
- 如果 handoff 根目录存在 `content_list.json`、`middle_json.json`、`middle.json`、`mineru_content_list.json` 或 `mineru_middle_json.json`，会以只读方式提取有限 layout signals；不存在时不影响默认 Markdown-only hints 生成。
- 离线 sample fixture 已验证增强后的 hints 会进入 `topology advise` 的 `route_test_starters`，并推动 `assistant_test_plan` 覆盖视觉、数值和 paraphrase 检查；真实文档集上的 live benchmark 仍应作为 RAGFlux 退役前验收的一部分。

### 3.6 P2：文档和迁移指引

- [x] 更新 `ragflow-doc-to-md/SKILL.md`：区分快速预览和正式入库前处理。
- [x] 更新 `ragflow-kb-build/SKILL.md`：说明如何消费 pipeline 产物和 ingest plan。
- [x] 更新 Hermes/OpenClaw onboarding prompt：引导用户先跑 pipeline，再跑 kb-build dry-run，再决定是否 live build。
- [x] 增加 RAGFlux 迁移表：RAGFlux 产物 -> 三 skill 产物。
- [x] 标注 RAGFlux 退役前必须满足的 release gate。

RAGFlux 产物迁移表：

| RAGFlux 产物/能力 | 三 skill 替代产物/命令 | 状态 |
| --- | --- | --- |
| PDF/Office/image -> Markdown | `ragflow-doc-to-md pipeline --backend mineru-fastapi --mineru-asset-mode markdown_assets` | 已实现；代表性 PDF 真实 MinerU FastAPI field-trial 通过，后续继续多样本观察 |
| 图片目录 | `documents/images/...`，`doc_manifest.json` 的 `assets.images[]`，`artifact_index.json` 的 image artifacts | 已实现；代表性 PDF 落地 21 张本地图片资产，未发现新协议解析缺口 |
| `<!-- chunk -->` 标记 | `pipeline --postprocess-profile chunk-markers` 生成 `postprocess_report.json` 并改写 handoff Markdown | 已实现 |
| `retrieval_hints.json` | `package --rich` / `pipeline` 生成增强 hints，含 section/page/table/image/numeric/template signals | 已实现 |
| `retrieval_hints` 被后续工具消费 | `ragflow-kb-build topology advise/split-plan/activation-plan`，`ragflow-query assistant-profile/assistant-test-plan` | 已实现 |
| RAGFlow 配置建议 | 非密钥 `ragflow_ingest_plan.yaml`，可选非密钥 alias `ragflow_config.yaml` | 已实现；真实 endpoint/API key 仍只放私有 config 或环境变量 |
| 入库 dry-run | `ragflow-kb-build inspect-handoff` + `build.py --dry-run` | 已实现 |
| live build / parse / validate | `ragflow-kb-build` build、`validate.py --level smoke/regression/benchmark`、`parse-report`、`health-report` | 已实现；代表样本经用户批准完成一次性 KB live E2E，后续 live mutation 仍需逐次批准 |
| query / assistant 验证 | `ragflow-query ask`、`assistant-profile recommend`、`assistant-test-plan`、`audit-citations`、`evaluate-answer` | 已实现；assistant 设置不自动修改 |

RAGFlux 退役前 release gate：

1. 离线 release gate 通过：runtime tests、`git diff --check`、manifest schema、release hygiene、build release、archive export、consumer acceptance、strict-vendor platform smoke。
2. 真实 MinerU FastAPI field-trial 至少覆盖一份含图片、表格、页码和中文标题的 PDF，确认 `markdown_assets` 后 quality gate 不再因已落地图片 BLOCKED。
3. 正式 pipeline 产物包含 Markdown、本地图片、`doc_manifest.json`、`quality_report.json`、`postprocess_report.json`、`retrieval_hints.json`、rich package sidecars 和 `ragflow_ingest_plan.yaml`。
4. `ragflow-kb-build inspect-handoff` 报告 `ingestion_readiness.status` 为 `ready` 或只有已被用户接受的 review 项；`build.py --dry-run` 成功且不需要 `--allow-blocked`。
5. 经用户批准后，使用一次性 KB 完成 live build、parse wait、smoke validation、direct query、host-assisted query，并保留脱敏报告。
6. 对 RAGFlux 对照样本确认关键指标不退化：图片数量、quality gate、chunk marker、retrieval hints、parse 成功率、chunk 数、smoke query evidence。
7. 清理一次性 KB 或记录 dataset id / KB name 供用户清理；不得把真实 endpoint、API key、私有路径写入 public `skills/`、docs 或 release artifacts。

### 3.7 验证计划

针对 P0/P1/P2 代码和指引实现，至少运行：

```bash
python3 -m py_compile \
  packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_convert.py \
  packages/ragflow-skill-runtime/src/ragflow_skill_runtime/handoff.py \
  packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_postprocess.py \
  skills/ragflow-doc-to-md/scripts/convert.py \
  skills/ragflow-kb-build/scripts/build.py

python3 -m pytest \
  packages/ragflow-skill-runtime/tests/test_doc_convert.py \
  packages/ragflow-skill-runtime/tests/test_doc_convert_cli.py \
  packages/ragflow-skill-runtime/tests/test_handoff.py \
  packages/ragflow-skill-runtime/tests/test_kb_build_cli.py -q

git diff --check
python3 tools/release_hygiene_check.py
```

若 public CLI、release tooling 或 acceptance 行为发生变化，还需要跑完整 release-facing chain：

```bash
python3 -m pytest packages/ragflow-skill-runtime/tests -q
git diff --check
python3 tools/manifest_schema_check.py
python3 tools/release_hygiene_check.py
python3 tools/build_release.py --check
python3 tools/export_release_archives.py
python3 tools/consumer_acceptance.py --work-dir /tmp/ragflow-acceptance-capability-parity --overwrite
python3 tools/platform_smoke_matrix.py --profile strict-vendor-env --work-dir /tmp/ragflow-platform-capability-parity
```

### 3.8 推荐执行顺序

1. 先实现 P0 图片资产落地，因为它直接导致 quality gate BLOCKED。
2. 再实现 pipeline 工作流，把已有 postprocess 和 package rich 串起来。
3. 再实现非密钥 ingest plan sidecar，补齐 RAGFlux 使用体验。
4. 最后增强 hints 质量和 kb-build activation/topology 串联。

P0/P1/P2 离线能力补齐完成后，`ragflow-doc-to-md + ragflow-kb-build + ragflow-query`
已具备作为 RAGFlux 退役候选替代链路的基础。2026-07-03 的代表性 PDF 现场 gate
已经验证真实 MinerU FastAPI、一次性 KB live E2E 和 retained package baseline 对比；
后续正式发布判断应继续区分“代表样本通过”和“广泛语料质量保证”。

### 3.9 现场 gate 执行记录（2026-07-03）

本记录只描述当前这轮 RAGFlux 能力补齐后的现场验收。P0/P1/P2 的离线实现、
公开 skill 指引、release hygiene、consumer acceptance、strict-vendor platform smoke
和提交推送已完成；现场 gate 用一个代表性中文产品 PDF 验证现有 public CLI surface，
没有新增命令或私有 adapter。

已完成基线：

- [x] P0/P1/P2 离线能力补齐完成，并通过完整 release-facing chain。
- [x] 公开 skill 文案已使用 legacy workflow 中性表述，避免旧项目名进入 public release surface。
- [x] 迁移表、退役 gate、Hermes/OpenClaw onboarding 指引已更新并推送到 `develop`。

现场 gate：

- [x] 真实 MinerU FastAPI field-trial：选择至少一份含图片、表格、页码和中文标题的 PDF，
  使用 `ragflow-doc-to-md pipeline --backend mineru-fastapi --mineru-asset-mode markdown_assets
  --postprocess-profile chunk-markers` 生成 handoff，记录图片落地数量、quality gate、
  `doc_manifest.json`、`runtime_report.json` 和 `retrieval_hints.json`。
- [x] 真实 MinerU FastAPI 返回形态已被现有解析器覆盖；未发现需要新增协议解析器的脱敏样本。
- [x] 真实 handoff 入库前检查：`ragflow-kb-build inspect-handoff` 报告
  `ingestion_readiness.status` 为 `ready`，`build.py --dry-run` 通过，且没有依赖
  `--allow-blocked`。
- [x] 经用户明确批准后，使用一次性 RAGFlow KB 完成 live build、parse wait、smoke validation、
  direct query、host-assisted query，并保留脱敏报告。
- [x] 完成同一对照样本的 RAGFlux retained package baseline 对比；新链路无关键静态退化，并有
  新的 live parse/query evidence。
- [x] 清理一次性 KB；自动 delete 成功，无需用户手动清理。
- [x] 将 field-trial 结果按 `docs/15-field-trial-observation-plan.md` 记录为脱敏证据。

执行结果：

- 第一轮完整样本运行在 MinerU 转换输出前遇到 CUDA out-of-memory；释放 GPU 压力后，完整 PDF
  pipeline 通过。这说明阻断来自服务资源竞争，而不是 `ragflow-doc-to-md` 图片资产落地或
  handoff parser 缺陷。
- 完整 pipeline 产物：quality gate `PASS`，1 个 Markdown 文档，21 张本地图片资产，9 个
  `<!-- chunk -->` 标记，10 个 section boundaries，21 个 image artifacts，26 个
  question candidates，rich sidecars 和 `ragflow_ingest_plan.yaml` 齐全。
- 入库前检查：`inspect-handoff` 为 `ready`，dry-run 通过。
- live E2E：一次性 KB build 成功，parse wait 完成，RAGFlow 生成 13 个 chunks；smoke
  validation 通过且无空结果；direct query 和 host-assisted query 均返回 evidence；cleanup
  execute 成功。
- curated field-trial metrics：`ok: true`，0 findings，quality `PASS`，无 runtime failure，
  无 zero-result query output。
- RAGFlux retained package baseline：quality `PASS`，可上库包有 15 张图片、25 个 chunk
  markers、12 个 sections 和 `ragflow_config.yaml`。新 pipeline 有 21 张本地资产、9 个
  chunk markers、10 个 section boundaries、19 个 preferred boundaries、21 个 image
  artifacts、26 个 question candidates 和非密钥 `ragflow_ingest_plan.yaml`。

遗留观察项：

- RAGFlux 的 chunk marker 更密；新 pipeline 采用较保守的标题边界策略。由于 live parse 生成
  13 个 chunks 且 smoke/query 通过，这不是本样本阻断项，但后续多样本文档应继续观察 chunk
  边界质量。
- RAGFlow model-provider probe 在当前服务版本上返回 provider path 兼容性 404，但 dataset
  build、parse、validate、query 和 cleanup 均成功；该问题不阻断本轮退役 gate。
- live 健康报告缺少 embedding model 显式值，且本轮未单独提供 activation plan；两者是
  advisory review note，不是 live failure。
- 本轮只按用户批准对新 replacement path 做了一次性 KB live E2E；如果需要 RAGFlux retained
  package 的严格 paired live A/B，需要另行批准第二次 disposable KB mutation。

### 3.10 本轮改善收尾结论与后续路线

本轮能力补齐的核心结论：

1. RAGFlux 退役的关键缺口已经从“能力缺失”转为“现场运行质量持续观察”。P0 图片资产落地、
   P1 pipeline / ingest plan / kb-build 串联、P2 retrieval hints 增强均已完成，并通过离线
   release-facing validation。
2. 在代表性中文产品 PDF 上，`ragflow-doc-to-md pipeline --backend mineru-fastapi
   --mineru-asset-mode markdown_assets --postprocess-profile chunk-markers` 可以胜任正式入库前处理：
   quality gate `PASS`，本地图片资产落地，rich sidecars 齐全，`inspect-handoff` ready，
   dry-run 通过。
3. 三 skill 拆分后的职责边界成立：`ragflow-doc-to-md` 负责转换和 handoff 富化，
   `ragflow-kb-build` 负责上库、解析、验证和健康报告，`ragflow-query` 负责 direct /
   host-assisted 检索验证。RAGFlux 的“一条龙”能力已被拆成更可治理的流水线。
4. 代表样本 live E2E 证明 replacement path 可完成一次性 KB build、parse wait、smoke
   validation、direct query、host-assisted query 和 cleanup；这使其可以作为默认正式链路的候选。
5. 本轮通过的是代表样本验收，不等同于所有文档类型的广泛质量保证，也不等同于 RAGFlux retained
   package 的严格 paired live A/B。后续是否扩大为默认发布路径，应依赖更多样本文档的持续观察。

后续需要持续关注的事项：

- MinerU 资源压力：CUDA OOM 来自服务资源竞争时，应先释放或降低 GPU 压力，再判断是否存在协议或
  parser 缺陷。Hermes/OpenClaw 应把 MinerU 服务状态、端口和显存占用纳入运行前检查。
- MinerU FastAPI 协议漂移：如果真实服务返回离线 fixture 未覆盖的新图片、zip、base64、
  content-list 或 middle-json 形态，应先记录脱敏样本，再做最小解析器扩展。
- Chunk 边界质量：RAGFlux retained package 的 chunk marker 更密；新 pipeline 的 marker 更保守。
  当前样本 live parse 和 smoke query 已通过，但多样本文档应继续观察 chunk 数、召回质量和边界可读性。
- 图片资产语义：新 pipeline 本地资产数多于 Markdown 引用数，说明 artifact index 捕获了额外图片。
  后续应观察这些额外资产是否提高检索/审计价值，还是会带来无效资产膨胀。
- RAGFlow 版本兼容：model-provider probe 在当前服务版本出现 provider path 兼容性 404，但 dataset
  build/parse/query/cleanup 正常。后续应把 provider probe 与 dataset API 可用性分开判断。
- 私有凭据生命周期：live 配置可能过期，临时配置只能保存在私有路径，使用后必须删除；public docs
  只记录脱敏事实，不记录 endpoint、token、dataset id、document id、KB name、run root 或原始路径。
- Manifest 可解释性：live 健康报告中 embedding model 缺失、activation plan 未单独提供仍是
  advisory review note。后续如果要给用户更强的发布信心，应补齐这些信息链路。
- Cleanup 可靠性：一次性 KB 必须默认预览后执行 cleanup，并保留 cleanup 成功或手动清理所需的脱敏事实。
- 多文档类型覆盖：当前代表样本是中文工业产品 PDF。后续还应覆盖扫描件、长文档、论文、合同、复杂表格、
  大量图片、低质量 OCR 和多文档批量 handoff。

后续可以新增但不应立即默认展开的功能：

- `structured_assets` 生产模式：在 `markdown_assets` 稳定后，按 opt-in 增加 content_list、
  middle_json、页码、版面块、图片上下文和表格结构 sidecar 的完整保存与 schema 化。
- 自适应 chunk-marker profile：在现有 `chunk-markers` 基础上增加 conservative / dense /
  ragflux-compatible 等 profile，并用离线 fixture 和 live smoke 对比验证不同密度的召回影响。
- 现场验收批处理器：提供一个非默认、显式 run-root 的 field-trial runner，串联 pipeline、
  inspect、dry-run、可选 live E2E、cleanup 和脱敏摘要，减少 Hermes/OpenClaw 临场编排成本。
- Retained package 对比报告：把本轮临时 comparison 口径产品化为只读报告，固定比较 quality、图片、
  chunk marker、hints、sidecars 和 live evidence，同时明确 paired live A/B 需要额外批准。
- RAGFlow provider compatibility probe：按 RAGFlow 版本拆分 provider/model probe endpoint，
  避免 provider path 404 被误判为 dataset build/query 不可用。
- Activation plan 自动串联：在 pipeline handoff 或 kb-build dry-run 后更显式地产生 route-test
  readiness、assistant test plan 和 activation checklist，帮助用户完成上库后的检索启用。
- Handoff 完整度评分：基于 quality gate、图片落地、sidecar 完整性、hint 信号、dry-run ready
  和 redaction 结果生成一个 advisory score，供 host agent 决定是否提示用户进入 live build。
- 多样本退役观察矩阵：已在 `tools/field_trial_metrics.py` 中以
  `ragflow_retirement_observation_matrix_v1` 离线 summary 形式实现；后续继续把真实
  PDF/Office/图片样本按文档类型、图片/表格复杂度、OCR 难度、parse chunk 数和
  smoke/query/cleanup 结果汇总，作为最终默认发布路径的证据。
