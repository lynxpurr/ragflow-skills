# 22. APOLLO 表格 QA 矫正核验与后续优化计划

状态：公共离线开发批次已完成；剩余私有/live gated 项待外部输入
日期：2026-07-04
范围：基于 APOLLO 表格 QA 私有评估结果，校准 `ragflow-doc-to-md` 与
`ragflow-kb-build` 的剩余表格问答质量问题；不执行 live RAGFlow mutation，不引入
script-owned LLM 评估。

## 1. 结论摘要

此前 APOLLO 表格 QA 私有矫正报告的核心判断是有价值的：APOLLO 这类规格表问答质量受
上游表格结构、chunk marker 原子性、RAGFlow parser profile 和查询评估共同影响。但该
报告已经滞后于当前实现，且包含本地运行细节；本文件已提取其合理部分，原始输入报告
不作为 public repo 文件保留。

当前已核验为已实现或已缓解的内容：

- `mineru-fastapi` 已支持 `--mineru-fastapi-backend` 和
  `--mineru-fastapi-server-url`，并通过 CLI、环境变量和配置文件进入运行时。
- `mineru_fastapi_convert()` 已把 resolved backend 写入 FastAPI form，并在提供时透传
  `server_url`；`hybrid-engine` / `vlm-engine` 也会映射到当前兼容 backend 名称。
- `--table-quality standard|high|auto` 已成为正式入口；formal pipeline 默认
  `chunk-markers-dense`，不再把普通 `chunk-markers` 当作表格文档推荐路径。
- OCR cleanup 已跳过 HTML table 和 Markdown pipe table block；`postprocess_report`
  已具备 table integrity / table delta / marker-in-table 观测能力。
- `quality_report` 已补充 HTML/Markdown/content-list table 计数、HTML table
  fingerprints、chunk marker atomicity 和 table-heavy 信号。
- `delimiter` 已加入 `SUPPORTED_PARSER_KEYS`，带反引号的 `` `<!-- chunk -->` `` 不再被
  profile linter 误报。
- rich handoff 已在检测到表格时生成 `table-atomic-*-4096` profile suggestion，包含
  `chunk-markers-dense`、`` `<!-- chunk -->` `` delimiter、较大父 chunk、零 overlap
  和 `avoid_children_delimiter: true`。

仍然成立、应进入下一轮优化的问题：

- APOLLO LLM QA 失败主要已经从“是否能生成 marker”转为“表格语义是否能被检索和回答正确使用”：
  表头术语别名、row/colspan 对齐、跨表比较、多跳召回和 judge 校正仍会影响真实问答。
- KB live build 路径仍只上传 Markdown 文件本身；当前已具备 Markdown+图片的离线上传包计划和本地 zip
  物化，但没有默认执行 live 资产上传。
- 当前 APOLLO 16 问评估仍是私有运行产物，没有被整理成可复用、脱敏、无 live mutation 的
  regression fixture。
- RAGFlow 部署的父 chunk 上限如果低于表格所需长度，delimiter 只能保护边界，不能保证超大表格
  永远不被服务端二次切分。

## 2. 核验依据

本次核验使用以下证据，但不把私有路径、真实服务地址或本地 KB 标识写入本 public docs：

- 私有输入报告：APOLLO 表格 QA 矫正报告；已消化为本文件，不在 public repo 保留原文。
- 当前设计状态：`docs/21-ragflow-doc-to-md-table-quality-design.md`。
- 相关实现：
  - `skills/ragflow-doc-to-md/scripts/convert.py`
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_convert.py`
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_postprocess.py`
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/doc_quality.py`
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/handoff.py`
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/apollo_qa.py`
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/kb_build.py`
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/query_table_strategy.py`
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/profiles.py`
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/ragflow_client.py`
  - `skills/ragflow-kb-build/scripts/build.py`
  - `skills/ragflow-query/scripts/query.py`
  - `tools/schema_identity_check.py`
  - `tools/report_surface_inventory.py`
  - `tools/generated_markdown_audit.py`
- 相关测试：
  - `packages/ragflow-skill-runtime/tests/test_doc_convert.py`
  - `packages/ragflow-skill-runtime/tests/test_doc_convert_cli.py`
  - `packages/ragflow-skill-runtime/tests/test_doc_postprocess.py`
  - `packages/ragflow-skill-runtime/tests/test_handoff.py`
  - `packages/ragflow-skill-runtime/tests/test_profiles.py`
  - `packages/ragflow-skill-runtime/tests/test_apollo_qa.py`
  - `packages/ragflow-skill-runtime/tests/test_kb_build.py`
  - `packages/ragflow-skill-runtime/tests/test_kb_build_cli.py`
  - `packages/ragflow-skill-runtime/tests/test_query_table_strategy.py`
  - `packages/ragflow-skill-runtime/tests/test_query_cli.py`
  - `packages/ragflow-skill-runtime/tests/test_schema_identity_check.py`
  - `packages/ragflow-skill-runtime/tests/test_report_surface_inventory.py`
  - `packages/ragflow-skill-runtime/tests/test_runtime_resilience_inventory.py`
- 私有 APOLLO 评估产物名：
  - `2026-07-04-mineru-hybrid-auto-vs-pipeline-table-quality`
  - `2026-07-04-ragflow-apollo-fastapi-table-atomic`
  - `2026-07-04-apollo-table-qa-evaluation-report`
  - `2026-07-04-apollo-table-qa-llm-evaluation-report`

## 3. 新的问题描述

APOLLO 问题不再应描述为“`ragflow-doc-to-md` 固定 pipeline、缺少 chunk marker 支持”。这些
关键工程问题已经实现或缓解。新的问题应描述为：

> 对复杂规格表文档，`ragflow-doc-to-md` 已能产出 table-safe Markdown handoff 和表格 profile
> 建议，但从 Markdown handoff 到真实 RAGFlow 问答仍存在语义保真缺口：上游表格 header/rowspan/
> colspan 的结构解释、表头术语别名、图片资产入库、父 chunk 长度上限、跨表多跳召回和评估 judge
> 都可能让“检索到答案”不能稳定转化为“回答正确”。

可以分为四层：

| 层级 | 当前状态 | 剩余风险 |
| --- | --- | --- |
| 上游解析 | `table-quality high/auto` 可选择 hybrid/VLM 类 backend；APOLLO 证据显示 hybrid 表头分层与温度符号更好 | 术语符号、row/colspan、多级表头仍可能对 LLM 不透明；pipeline 的表1/表2混淆不应靠下游硬修 |
| Markdown 后处理 | OCR cleanup 已 table-safe；dense marker 会在表格边界插入 marker | 旧报告中的“直接改写表头”不宜作为通用默认，应改为可审阅别名/语义 sidecar |
| RAGFlow 入库 | profile suggestion 已给出 delimiter、较大父 chunk 和避免 child delimiter 的建议；KB 侧已有离线 asset upload plan/zip 物化和父 chunk 预检 | live build 仍未默认携带本地图片资产；部署上限较小时，超大表格仍可能被二次切分 |
| 查询与评估 | 纯检索能证明答案常在 top chunks 中；已具备 no-LLM table strategy report 与外部 judge request/review 边界 | 完整 16 问仍需私有侧脱敏 fixture 和 saved result；row/colspan 读取、跨表答案合成和严格 judge 仍需人工/外部复核 |

## 4. 旧报告任务校准

| 旧报告建议 | 核验结论 | 新处理方式 |
| --- | --- | --- |
| 增加 `--mineru-fastapi-backend` | 已实现 | 保持现有实现和测试；继续观察不同 MinerU 版本 backend 命名 |
| 透传 `server_url` | 已实现 | 保持 endpoint redaction；只在 `*-http-client` 类 backend 需要时配置 |
| 默认使用 `chunk-markers-dense` | 已实现于 formal pipeline | 保留 `chunk-markers` 作为兼容 alias；正式入库继续推荐 dense |
| 修复 `chunk-markers` 改写 HTML table 空格 | 已实现 | 保持 table protected spans 和 fixture 覆盖 |
| `delimiter` 加入白名单 | 已实现 | 保持 `test_profiles` 覆盖 |
| 表头符号标准化 | 方向合理，但不宜硬编码全局替换 | 改为“术语别名 sidecar / review hint”，由文档或领域 profile 审核后生效 |
| pipeline 表1/表2混淆 | 证据成立，但不宜做低可信后处理重构 | 正式表格路径优先 high/auto backend；只给 pipeline 结果风险提示 |
| row/colspan 结构不清 | 证据成立 | 增加表格结构评分、header 层级摘要、row/colspan review hints |
| 自动打包 Markdown + images 入库 | 公共离线计划已实现，live 上传仍 gated | 已有 `asset-upload-plan` 和本地 zip 物化；真正 live zip/批量资产上传需确认 API 语义、fake-client 覆盖和显式批准 |
| 提升 RAGFlow chunk 上限 | 属于部署/服务端能力 | CLI 侧只做风险提示和 profile 建议；服务端调整不纳入 public skill 默认行为 |
| 改进 LLM judge | 外部 request/review 边界已完成，仍不能启用 script-owned LLM | 保持 no-LLM normalized judge 为基线；外部 candidate 只作为 advisory/generated artifact |
| 16 问 QA 回归 | 公共 schema/harness 已完成，完整 16 问填充仍在私有侧 gated | 私有侧按 `apollo_table_qa_fixture_v1` 填入脱敏用例，再运行 validate/evaluate/table-strategy/judge-review |

## 5. 更新方案

### P0：APOLLO 表格 QA 离线回归基线

把现有 16 问私有用例整理为可复用的脱敏 fixture。公开 fixture 不包含私有源路径、本地 KB 名、真实
dataset 标识或原始 live run 细节，只保留问题、期望事实、可接受答案、表格来源类别、难度和评估方式。

验收：

- fixture 能被离线测试读取并通过 schema 校验。
- 支持对已有 retrieval/answer JSON 结果做 no-network 评估。
- 严格字符串 judge 与 normalized semantic contains judge 分开统计，避免把“表述不同但事实正确”误判为失败。
- 不调用 LLM，不访问 RAGFlow。

### P0：术语别名与表格语义 sidecar

不要在通用 postprocess 中直接把 `$MPE_E$` 改成 `MPEr`。更稳妥的做法是生成可审阅 sidecar：

- 从 HTML table header、caption、邻近标题和 retrieval hints 中提取原始术语。
- 记录“源标签、规范化标签、候选别名、证据行/表格、置信度、是否需要人工确认”。
- 对 APOLLO 这类专用术语，只在 fixture 或用户提供的领域 alias profile 中声明映射。
- 查询或 QA 评估可消费该 sidecar 做 query expansion，但 Markdown 原文保持可审计。

验收：

- HTML table header 中的数学/下标/大小写变体可被稳定提取。
- APOLLO fixture 能表达 `$MPE_E$` 与用户问题术语之间的候选别名，但不会全局改写 Markdown。
- sidecar 通过 redaction scan，不包含私有路径或 live 标识。

### P0：表格结构风险评分

在现有 table fingerprint 基础上补充 per-table 语义风险信号：

- header depth、rowspan/colspan count、最大列数、最大 cell 数；
- 是否存在多型号合并表头；
- 是否存在同一行/列多个候选型号标签；
- 是否存在表格超长、疑似跨页、caption 缺失或相邻表格缺少上下文。

验收：

- APOLLO HH-A 扭矩类表格能被标记为 row/colspan 或多型号 header review 风险。
- 风险只产生 review hints，不做不可逆 Markdown 重写。
- `quality_report` / `retrieval_hints` / `assistant_test_plan` 至少有一个稳定消费路径。

### P1：KB 侧图片资产入库方案

`ragflow-doc-to-md` 已能生成本地 Markdown assets，但 `ragflow-kb-build` 当前 build 路径仍逐个上传
Markdown 文件，没有把引用图片自动随文档进入 RAGFlow。需要新增 KB 侧设计，先支持非 live 包装计划：

- 读取 doc manifest 和 Markdown image refs。
- 生成上传包计划，明确哪些 Markdown、图片和 sidecar 会进入包。
- 离线测试覆盖本地 zip/package 物化；真正批量上传 fake-client 覆盖留到确认 live API 语义后再开启。
- live 上传必须沿用现有 mutation gate 和 cleanup 规则。

验收：

- dry-run 能报告缺失图片、孤儿图片、包内相对路径和预计上传文件。
- 单元/CLI 测试覆盖 Markdown+images 上传计划和本地 zip 包内容；live/fake-client 上传执行不在未获批准的公共默认路径内。
- 未获批准时不执行 live mutation。

### P1：父 chunk 上限与表格原子性预检

在生成 profile suggestion 或 ingest readiness 时增加“预计父 chunk 风险”：

- 根据表格字符数、cell 数、估算 token 长度和用户 profile 的 `chunk_token_num` 判断风险。
- 如果用户部署只允许较小父 chunk，明确说明 delimiter 只能控制边界，不能保证超大表格不被服务端切分。
- 对超大表格给出拆表、提高服务端上限或人工复核建议。

验收：

- `table-atomic-*-4096` 仍是优先建议。
- 使用较小父 chunk 的 profile 会触发 review warning。
- 不假设所有 RAGFlow 部署都支持 4096。

### P1：跨表比较检索策略

APOLLO 证据显示跨表比较问题比单表查值更脆弱。下一步应利用已有 query/fusion 能力做 no-LLM 对比：

- 为跨表问题生成多 query expansion：一个 query 锁定表1，一个 query 锁定表2，再融合。
- 用 retrieval hints 的 table caption/source heading 做 query hint。
- 比较 direct top-k、multi-query、fusion/RRF 的召回变化。

验收：

- 不调用生成模型。
- 报告每种检索策略对 16 问 fixture 的命中率和失败类别。
- 跨表问题至少能说明是“召回不足”还是“答案合成错读”。

### P2：外部 judge request/review

如果后续需要 LLM-as-judge，应沿用 Phase 38 的 request/review 边界：

- skill 只生成 judge request artifact。
- 外部或 host-approved 模型产出 judge candidate。
- review 命令验证候选结构、引用、事实字段、redaction 和可重复摘要。

验收：

- 默认无模型调用。
- candidate 必须标记 advisory/generated。
- normalized no-LLM judge 仍作为基线。

## 6. 任务清单

| 状态 | 优先级 | 负责面 | 任务 | 产物 | 验收门 |
| --- | --- | --- | --- | --- | --- |
| 公共框架完成；私有 16 问填充 gated | P0 | maintainer/tests | 将 16 问 APOLLO QA 转成脱敏 fixture schema | `apollo_table_qa_fixture_v1` fixture + tests | no-network schema/read tests |
| 完成 | P0 | maintainer/tests | 实现已有 retrieval/answer JSON 的离线评估器 | normalized contains / strict contains report | fixture tests，误判校正样例 |
| 完成 | P0 | doc-to-md runtime | 增加表格术语候选提取 sidecar | `table_term_alias_candidates` report section | 不改写 Markdown；redaction clean |
| 完成 | P0 | doc-to-md runtime | 增加 per-table 结构风险评分 | table semantic risk fields | HH-A 类 row/colspan fixture 触发 review |
| 完成 | P0 | handoff | 将术语候选和结构风险接入 retrieval hints | hint fields + assistant test starters | `inspect-handoff` 可读到摘要 |
| 完成 | P1 | kb-build | 设计 Markdown+images 上传包 dry-run | `ragflow_kb_asset_upload_plan_v1` | local package/CLI tests；live disabled |
| 完成 | P1 | kb-build | 增加表格父 chunk 风险预检 | ingest readiness / dry-run warning | 小父 chunk profile fixture 触发 warning |
| 完成 | P1 | query | 为跨表问题增加 no-LLM retrieval strategy report | direct vs multi-query/fusion comparison | APOLLO fixture 离线报告 |
| 完成 | P1 | docs | 更新 host-agent 表格入库指引 | concise usage section | 不含私有路径或服务地址 |
| 完成 | P2 | optional LLM boundary | 设计外部 judge request/review | `apollo_table_qa_judge_request_v1` / `apollo_table_qa_judge_review_report_v1` | 默认不调用模型 |
| gated；未获明确 live 批准不执行 | P2 | live gated | 代表样本 live KB 创建/查询/清理验证 | sanitized field-trial evidence | 明确批准、cleanup、redaction |

## 7. 当前建议用法

含复杂表格、正式入库前处理时，优先使用：

```bash
python scripts/convert.py pipeline \
  --input <source> \
  --output <handoff> \
  --backend mineru-fastapi \
  --mineru-base-url <mineru-fastapi-base-url> \
  --table-quality high \
  --mineru-asset-mode markdown_assets \
  --postprocess-profile chunk-markers-dense \
  --json
```

入库前复核：

```bash
ragflow-kb-build inspect-handoff --handoff <handoff>
ragflow-kb-build asset-upload-plan --doc-manifest <handoff>/doc_manifest.json \
  --report-json <run>/asset_upload_plan.json \
  --report-md <run>/asset_upload_plan.md
ragflow-kb-build --doc-manifest <handoff>/doc_manifest.json --profile <reviewed-profile.json> --dry-run
```

表格 profile 应优先使用 rich handoff 生成的 `table-atomic-*-4096` 建议；如果部署不支持较大父 chunk，
先降低为部署允许值并接受 `table_parent_chunk_preflight` review warning，不要设置 `children_delimiter`。

如需外部 judge，只生成 request/review artifact，不由 skill 调用模型：

```bash
ragflow-kb-build qa apollo-judge-request \
  --fixture <apollo-fixture.json> \
  --results <saved-results.json> \
  --target answer \
  --output <run>/apollo_judge_request.json \
  --report-md <run>/apollo_judge_request.md \
  --redaction-report <run>/apollo_judge_request.redaction.json

ragflow-kb-build qa apollo-judge-review \
  --request <run>/apollo_judge_request.json \
  --candidate <external-candidate.json> \
  --report-json <run>/apollo_judge_review.json \
  --report-md <run>/apollo_judge_review.md \
  --redaction-report <run>/apollo_judge_review.redaction.json
```

外部 candidate 必须标记 `advisory=true` 与 `generated=true`；review 会校验 case id、每题 verdict、
evidence refs、隐私字面量，以及“外部 pass 不可覆盖 normalized no-LLM baseline fail”。

## 8. 边界

- 不把 APOLLO 私有原始路径、本地 KB 名、真实服务地址或 live dataset 标识写入 public docs。
- 不在 `ragflow-doc-to-md` 中创建或修改 RAGFlow KB。
- 不默认启用 script-owned LLM judge、LLM 表格重写或 live disposable workflow。
- 不把 `$MPE_E$` / `$MPE_P$` 这类领域映射硬编码成全局 postprocess 规则；先用可审阅 sidecar
  和 fixture 验证收益。

## 9. 开发启动记录

日期：2026-07-04

已启动 P0 离线回归基线的第一段实现：

- 新增 `apollo_table_qa_fixture_v1` 的 no-network schema/read validation helper。
- 新增 `apollo_table_qa_evaluation_report_v1`，可对已有 retrieval/answer JSON 做 strict
  contains 与 normalized contains 分开统计。
- 新增 `ragflow-kb-build qa apollo-validate` 与 `ragflow-kb-build qa apollo-evaluate`，默认不访问
  RAGFlow、不调用模型、不执行 live mutation。
- normalized contains 支持在 fixture 中声明术语别名和格式变体，用于 APOLLO 表头符号、
  单位、温度符号等误判校正；Markdown 原文仍保持不改写。
- schema identity gate 已登记新增 report schema，避免后续 release hygiene 漏检。

当时尚未关闭的 P0 条目：

- 原私有 16 问 QA 原文未进入 public repo；当前实现先提供可验证框架和脱敏样例测试。
  后续需要由 host agent 在私有侧把 16 问按 `apollo_table_qa_fixture_v1` 填入，再运行
  `qa apollo-validate` 确认无私有路径、真实服务地址、dataset/document id 或 KB 名称。
- 表格术语候选 sidecar、per-table 结构风险评分、以及 retrieval hints 接入仍按任务清单继续推进。

日期：2026-07-05

已推进 P0 术语别名 sidecar 的第一段实现：

- `retrieval_hints.json` 新增 `table_term_alias_candidates` 字段，从 table artifacts 的 HTML/Markdown
  header、caption 和邻近 heading 中提取可审阅术语候选。
- 候选记录包含 `source_label`、`normalized_label`、`candidate_aliases`、table evidence、review
  confidence、`requires_review` 和 `rewrites_markdown=false`。
- `$MPE_E$`、`MPE<sub>P</sub>` / `MPE P` 等数学、下标、大小写和空格变体会生成候选别名；
  普通 caption 不会被过度拆成宽泛别名。
- `inspect-handoff` 的 retrieval-hints richness 摘要可看到 `table_term_alias_candidate_count`。

同日后续推进了 P0 per-table 结构风险评分：

- HTML table artifact 新增 `header_depth`，并在 `retrieval_hints.json` 的 `table_artifacts`
  中保留 `cell_count`、`rowspan_count`、`colspan_count`、`header_depth` 等结构信号。
- `retrieval_hints.json` 的每个 HTML table artifact 会生成 review-only
  `semantic_risk_score`、`semantic_risks`、`review_required`，必要时附带
  `model_label_candidates`。
- 已覆盖多级表头、rowspan/colspan、疑似列错位、大表、caption 缺失、多型号合并表头等风险；
  HH-A / HH-B 类复杂表头 fixture 会触发 `multi_level_header_review`、
  `merged_cells_review` 和 `multi_model_header_review`。
- `assistant_test_plan.json` 新增 `table_structure_review` starter，用于提醒人工或 host agent
  在问答前复核 header 层级、合并单元格对齐和表格引用。
- `inspect-handoff` 的 retrieval-hints richness 摘要新增 `table_semantic_risk_count`。

当前仍未关闭的 P0 条目：

- 原私有 16 问 QA 仍需在私有侧完成脱敏填充后，才能形成更完整的 APOLLO 回归覆盖。

同日继续推进了 P1 no-LLM query expansion / 跨表检索策略报告：

- 新增 `ragflow_table_query_strategy_report_v1`，由 `ragflow-query table-strategy` 离线生成。
- 输入为脱敏 `apollo_table_qa_fixture_v1` 与 rich handoff 的 `retrieval_hints.json`；可选输入已有
  direct / multi-query / fusion saved result JSON 做离线策略对比。
- 报告从 `table_artifacts` 的 caption、source heading、`model_label_candidates`、`semantic_risks`
  以及 `table_term_alias_candidates` 生成 direct top-k、hint multi-query 和 RRF fusion 策略建议。
- 报告显式标记 `offline_only=true`、`llm_calls=0`、`ragflow_calls=0`；不执行 live 检索、不调用模型、
  不改写 Markdown。
- 对 HH-A / HH-B 类跨型号复杂表头 fixture，会生成 `rrf_fusion` 策略；对 MPEE / `$MPE_E$`
  类表头别名，会生成 term-alias query expansion。

当时仍未关闭的 P1 条目：

- 私有 16 问还需要在私有侧填入脱敏 fixture，并把 direct / multi-query / fusion saved result JSON
  喂给 `table-strategy`，才能得到完整 16 问策略命中率报告。
- 该报告目前只生成 query expansion 和离线对比计划；后续如需自动执行真实 RAGFlow 检索，仍需沿用
  现有 live mutation/query gate 与显式批准。

同日继续推进了 P1 KB 侧 Markdown+images 上传包 dry-run：

- 新增 `ragflow_kb_asset_upload_plan_v1`，由 `ragflow-kb-build asset-upload-plan` 离线生成。
- 输入为 `doc_manifest.json`；报告读取 Markdown 图片引用和 doc_manifest `assets.images`，列出预计进入包的
  Markdown、图片和 rich handoff sidecar。
- 报告会标记 `offline_only=true`、`live_upload_enabled=false`、`llm_calls=0`、`ragflow_calls=0`，
  不创建 KB、不上传 RAGFlow、不触发 parse。
- dry-run 能报告缺失图片、逃逸 handoff root 的图片、远程图片引用、孤儿图片、包内相对路径和预计上传文件。
- 可选 `--package-zip` 只在本地物化 zip 包，便于 host agent 或后续 fake-client 测试检查包内容；live 上传仍需沿用
  现有 mutation gate、cleanup 规则和显式批准。
- schema identity gate 已登记新增报告 schema，避免后续 release hygiene 漏检。

当时仍未关闭的 P1 条目：

- 该上传包目前只完成离线计划和本地 zip 物化；如需真正让 RAGFlow live 接收 Markdown+images 包，还需要先确认
  目标 RAGFlow 上传 API 是否支持 zip/批量资产语义，并通过 fake-client 与明确 live gate 推进。
- 父 chunk 上限与表格原子性预检、host-agent 表格入库指引仍可作为后续离线小片继续推进。

同日继续推进了 P1 父 chunk 上限与表格原子性预检：

- `retrieval_hints.json` 的 table artifacts 新增 `source_text_chars`、`estimated_parent_chunk_tokens`、
  `recommended_min_parent_chunk_tokens`、`table_atomic_target_tokens`，用于解释表格原子性 profile 建议。
- `profile_suggestions.json` 的 signals 新增 `max_table_estimated_parent_chunk_tokens` 和
  `table_atomic_target_tokens`；`table-atomic-*-4096` 仍保持为表格文档优先建议。
- `ingest_readiness_report.json` 新增 `table_parent_chunk_preflight` check，明确
  `deployment_limit_assumption=unknown`，并说明 delimiter 只能控制边界，不能覆盖服务端更低的父 chunk 上限。
- `ragflow-kb-build --dry-run` 在用户传入实际 profile 时会输出 `table_parent_chunk_preflight`；小父 chunk
  profile 会触发 `table_parent_chunk_profile_too_small` review warning，但不执行 live mutation。
- 该检查不假设所有 RAGFlow 部署都支持 4096；如果估算表格超过 4096，会建议拆表、调整部署上限或人工复核。

当时仍未关闭的 P1 条目：

- host-agent 表格入库指引需要把 `inspect-handoff`、`asset-upload-plan`、表格 profile review 和 dry-run
  父 chunk warning 串成一段简明流程。

同日完成 P1 host-agent 表格入库指引：

- 三个 public skill 的共享 `references/host-agent-setup.md` 新增 `Complex Table Ingest Review` 小节。
- 指引串联 `ragflow-doc-to-md pipeline --table-quality high|auto`、`chunk-markers-dense`、
  `inspect-handoff`、`asset-upload-plan`、`table-atomic-*-4096` profile review 和
  `table_parent_chunk_preflight` dry-run warning。
- 指引明确该流程在 live approval 前保持 offline，并说明 children delimiter 不应作为表格原子性修复手段。

当前 P1 公共离线任务已完成；当时剩余项属于私有 fixture 填充、可选外部 judge request/review 或 live-gated 验证。

同日继续推进并完成 P2 外部 judge request/review 边界：

- 新增 `apollo_table_qa_judge_request_v1`，由 `ragflow-kb-build qa apollo-judge-request`
  生成外部评审请求；request 包含脱敏 fixture case、已有 retrieval/answer 结果摘要、evidence refs、
  strict/normalized no-LLM baseline 摘要和 `llm_invoked=false`。
- 新增 `apollo_table_qa_judge_review_report_v1`，由 `ragflow-kb-build qa apollo-judge-review`
  对外部 candidate 做 deterministic review。
- candidate 必须显式标记 `advisory=true` 与 `generated=true`，并为 request 中每个 case 给出
  `pass|review|fail` verdict；未知 case、遗漏 case、非法 evidence refs 和隐私字面量会被拒绝。
- review 保持 normalized no-LLM judge 为基线：如果 baseline fail，外部 candidate 的 `pass` 不能覆盖该失败。
- 该边界仍是 no-LLM / no-live：`script_owned_llm_calls=0`，不访问 RAGFlow，不执行 live mutation。
- schema identity gate 已登记 judge request/review schema，CLI 和 runtime 测试覆盖 request 生成、review
  接受、未标记 candidate 拒绝、未知 case 拒绝和 baseline override 拒绝。

当前公共离线开发批次已清空；仍未关闭的内容只剩：

- 私有 16 问 QA 需要在 public repo 外完成脱敏填充后，才能把完整用例喂给当前 fixture/evaluate/table-strategy/judge
  流程。
- 代表样本 live KB 创建/查询/清理验证仍需用户在当前线程明确批准，并按 live field-trial runbook 保留私有原始产物、
  清理 disposable KB、只写入脱敏摘要。

## 10. 查漏补缺审计

日期：2026-07-05

本次回顾重新按任务表逐项核对设计、实现、CLI、测试和 release gate，补正了以下文档漂移：

- `核验依据` 增补 APOLLO fixture/evaluate/judge、KB asset upload plan、table strategy report、schema identity
  和 report surface inventory 的实现与测试文件，避免只引用早期 doc-to-md 表格质量路径。
- 将 KB 侧图片资产项从“fake-client 打包上传已覆盖”校准为“离线 upload plan + 本地 zip/package 物化已覆盖”；
  真正 live zip/批量资产上传仍需确认 RAGFlow API 语义、fake-client 测试和显式 live 批准。
- 将旧报告校准表中的 `LLM judge`、`16 问 QA 回归` 状态更新为当前 request/review/harness 已完成但私有填充仍 gated。
- 同步 `docs/21-ragflow-doc-to-md-table-quality-design.md` 的剩余风险段，说明 per-table 结构风险评分、
  parent chunk preflight、APOLLO QA harness、table strategy report 和 asset upload plan 已在 docs/22 后续批次补齐。

审计后仍没有新增可公开、离线、可验证的未完成任务。剩余仅为私有 16 问填充和 live KB 验证，两者都需要
外部输入或明确 live approval。

## 11. 本轮优化总结与后续方向

日期：2026-07-05

### 已完成任务

本轮围绕 APOLLO 复杂表格 QA，从早期“表格转换和 marker 是否正确”推进到“handoff 到检索、入库预检和
评估边界是否可审计”的公共离线闭环，已完成以下任务：

- **表格转换主路径校准**：确认 `--table-quality standard|high|auto`、MinerU FastAPI backend 选择、
  `server_url` 透传、`chunk-markers-dense` formal handoff、table-safe OCR cleanup 和 `delimiter`
  profile 白名单已经落地。
- **APOLLO QA 离线基线**：新增 `apollo_table_qa_fixture_v1` 校验框架和
  `apollo_table_qa_evaluation_report_v1`，支持对已有 retrieval/answer JSON 做 strict contains 与
  normalized contains 分开统计，不访问 RAGFlow、不调用模型。
- **表格语义 sidecar**：在 `retrieval_hints.json` 中补充 `table_term_alias_candidates`，为 `$MPE_E$`、
  `MPE<sub>P</sub>`、大小写、下标、空格和单位变体提供可审阅别名候选，不改写 Markdown 原文。
- **表格结构风险评分**：在 table artifacts 中补充 header depth、rowspan/colspan、cell count、
  `semantic_risk_score`、`semantic_risks`、`review_required` 和 `model_label_candidates`，并把结构风险接入
  retrieval hints 和 assistant test starters。
- **跨表检索策略报告**：新增 `ragflow_table_query_strategy_report_v1` 和 `ragflow-query table-strategy`，
  基于脱敏 fixture 与 retrieval hints 生成 direct、hint multi-query 和 RRF fusion 的 no-LLM 对比计划。
- **KB 资产上传 dry-run**：新增 `ragflow_kb_asset_upload_plan_v1` 和 `ragflow-kb-build asset-upload-plan`，
  可离线检查 Markdown 图片引用、缺失/孤儿/远程图片、rich sidecar 和本地 zip/package 内容；live 上传保持 gated。
- **父 chunk 原子性预检**：在 handoff/ingest readiness 和 `ragflow-kb-build --dry-run` 中增加
  `table_parent_chunk_preflight`，用表格字符数和 token 估算提示小父 chunk profile、服务端二次切分和超大表风险。
- **host-agent 表格入库指引**：三个 public skill 的共享 `references/host-agent-setup.md` 已补充
  `Complex Table Ingest Review`，串联 high/auto conversion、inspect、asset plan、table-atomic profile 和
  dry-run warning。
- **外部 judge request/review 边界**：新增 `apollo_table_qa_judge_request_v1` 与
  `apollo_table_qa_judge_review_report_v1`，通过 `ragflow-kb-build qa apollo-judge-request/review` 生成和审查
  advisory/generated 外部 judge candidate，normalized no-LLM baseline 仍是不可覆盖基线。
- **release gate 补齐**：新增/变更的 report schema 均纳入 schema identity；新增 CLI Markdown/report surface
  纳入 release hygiene、generated Markdown audit 和 runtime resilience inventory。

### 后续需要注意和跟踪的问题

- **私有 16 问仍未公共化**：当前 public repo 只包含 schema/harness 和脱敏样例测试；完整 16 问需要在私有侧脱敏后
  填入 fixture，再运行 `apollo-validate`、`apollo-evaluate`、`table-strategy` 和 `apollo-judge-review`。
- **live KB 验证仍需批准**：代表样本的真实 KB 创建、上传、解析、查询和清理仍属于 live mutation，必须由用户在当前线程明确批准，
  并按 field-trial runbook 保留私有原始产物、清理 disposable KB、只写入脱敏摘要。
- **资产上传仍是离线计划**：`asset-upload-plan` 已能物化本地 zip/package，但是否能被目标 RAGFlow API 作为 Markdown+图片包
  正确解析，仍需要确认 API 语义、fake-client 契约和批准后的 live disposable 验证。
- **表格结构风险只能提示不能修复**：rowspan/colspan、多级表头、跨页表和型号族错位仍主要取决于上游解析质量；
  当前 sidecar 和 semantic risks 只能帮助复核、检索扩展和评估分桶，不能无损重建错误表格。
- **父 chunk 上限是部署事实**：`table-atomic-*-4096` 和 delimiter 是推荐 profile，不代表所有 RAGFlow 部署都支持足够大的父 chunk；
  如果服务端上限更低，仍需拆表、调整部署或接受人工复核。
- **外部 judge 只能 advisory**：judge request/review 提供结构化边界，但不启用 script-owned LLM；外部模型输出必须通过
  review gate，且不能覆盖 normalized no-LLM baseline fail。
- **跨表策略仍需 saved results**：table strategy report 可以生成 expansion/fusion 计划；要量化 16 问 direct vs multi-query vs fusion
  命中率，仍需私有侧保存各策略 retrieval/answer JSON 后离线对比。
- **文档状态需要防漂移**：docs/21 是表格转换主路径设计，docs/22 是 APOLLO QA 矫正闭环；后续更新任一侧时，应同步校准另一侧的
  “已完成/仍需跟踪”段落。

### 后续升级改进方向

- **私有 APOLLO 回归包**：在 public schema 不变的前提下，于私有 run root 维护完整 16 问 fixture、saved retrieval/answer results、
  table strategy report、judge request/review 和脱敏摘要，形成可重复回归流水线。
- **资产入库 live 适配**：确认目标 RAGFlow 是否支持 zip 或批量资产语义；先补 fake-client 契约测试，再在明确批准下做 disposable KB
  live build/query/cleanup 验证。
- **表格语义 profile 扩展**：允许用户提供领域 alias profile、型号族词表、单位规范和表头别名规则，由 query expansion / QA evaluation 消费，
  但继续禁止通用 postprocess 对 Markdown 原文做不可逆替换。
- **跨表检索自动执行器**：在现有 `table-strategy` 离线计划基础上，增加显式 gated 的 saved-query 执行模式，用 fake client 覆盖 direct、
  multi-query 和 fusion/RRF 输出，再按 live query gate 逐步验证。
- **结构风险到评估分桶**：把 `semantic_risks` 与 QA case difficulty、failure category 和 judge rationale 关联起来，区分召回不足、表头错读、
  行列错位、跨表合成错误和严格字符串误判。
- **多样本观测矩阵**：除 APOLLO 代表规格表外，继续收集扫描件、长 PDF、图片密集文档、跨页大表、Office 表格和多文档 handoff 的脱敏指标，
  观察 `standard`、`auto`、`high` 的质量、耗时、失败率和 fallback 行为。
- **LLM backend 仍走 Phase 38 gate**：如果后续手工外部 judge 使用频率足够高，才考虑 script-owned LLM backend；启动前必须具备显式 LLM
  config、fake-provider fixtures、advisory 标记、citation/baseline compatibility 和 redaction gate。
