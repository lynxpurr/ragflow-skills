# 22. APOLLO 表格 QA 矫正核验与后续优化计划

状态：问题核验与后续任务建议
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
- KB 侧仍只上传 Markdown 文件本身，没有自动把 Markdown 引用的本地图片资产一起打包或上传。
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
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/profiles.py`
  - `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/ragflow_client.py`
  - `skills/ragflow-kb-build/scripts/build.py`
- 相关测试：
  - `packages/ragflow-skill-runtime/tests/test_doc_convert.py`
  - `packages/ragflow-skill-runtime/tests/test_doc_convert_cli.py`
  - `packages/ragflow-skill-runtime/tests/test_doc_postprocess.py`
  - `packages/ragflow-skill-runtime/tests/test_handoff.py`
  - `packages/ragflow-skill-runtime/tests/test_profiles.py`
  - `packages/ragflow-skill-runtime/tests/test_kb_build.py`
  - `packages/ragflow-skill-runtime/tests/test_kb_build_cli.py`
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
| RAGFlow 入库 | profile suggestion 已给出 delimiter、较大父 chunk 和避免 child delimiter 的建议 | KB build 仍未携带本地图片资产；部署上限较小时，超大表格仍可能被二次切分 |
| 查询与评估 | 纯检索能证明答案常在 top chunks 中；LLM 生成式评估更暴露真实错读 | 跨表比较、术语别名、row/colspan 读取、严格字符串 judge 都会造成真实 QA 失败或误判 |

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
| 自动打包 Markdown + images 入库 | 仍未实现 | 作为 `ragflow-kb-build` 独立方案推进，先 dry-run/fake-client，live 需批准 |
| 提升 RAGFlow chunk 上限 | 属于部署/服务端能力 | CLI 侧只做风险提示和 profile 建议；服务端调整不纳入 public skill 默认行为 |
| 改进 LLM judge | 方向合理，但不能启用 script-owned LLM | 先做 no-LLM normalized judge 和外部 judge request/review artifact |
| 16 问 QA 回归 | 仍未纳入正式 regression | 整理为脱敏 fixture，先做离线 regression harness |

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
- fake-client 测试 zip 或批量上传路径。
- live 上传必须沿用现有 mutation gate 和 cleanup 规则。

验收：

- dry-run 能报告缺失图片、孤儿图片、包内相对路径和预计上传文件。
- fake-client 覆盖 Markdown+images 打包上传。
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

| 优先级 | 负责面 | 任务 | 产物 | 验收门 |
| --- | --- | --- | --- | --- |
| P0 | maintainer/tests | 将 16 问 APOLLO QA 转成脱敏 fixture schema | `apollo_table_qa_fixture_v1` fixture + tests | no-network schema/read tests |
| P0 | maintainer/tests | 实现已有 retrieval/answer JSON 的离线评估器 | normalized contains / strict contains report | fixture tests，误判校正样例 |
| P0 | doc-to-md runtime | 增加表格术语候选提取 sidecar | `table_term_alias_candidates` report section | 不改写 Markdown；redaction clean |
| P0 | doc-to-md runtime | 增加 per-table 结构风险评分 | table semantic risk fields | HH-A 类 row/colspan fixture 触发 review |
| P0 | handoff | 将术语候选和结构风险接入 retrieval hints | hint fields + assistant test starters | `inspect-handoff` 可读到摘要 |
| P1 | kb-build | 设计 Markdown+images 上传包 dry-run | asset upload plan report | fake-client tests；live disabled |
| P1 | kb-build | 增加表格父 chunk 风险预检 | ingest readiness warning | 小父 chunk profile fixture 触发 warning |
| P1 | query | 为跨表问题增加 no-LLM retrieval strategy report | direct vs multi-query/fusion comparison | APOLLO fixture 离线报告 |
| P1 | docs | 更新 host-agent 表格入库指引 | concise usage section | 不含私有路径或服务地址 |
| P2 | optional LLM boundary | 设计外部 judge request/review | judge request/review schemas | 默认不调用模型 |
| P2 | live gated | 代表样本 live KB 创建/查询/清理验证 | sanitized field-trial evidence | 明确批准、cleanup、redaction |

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
ragflow-kb-build --doc-manifest <handoff>/doc_manifest.json --profile <reviewed-profile.json> --dry-run
```

表格 profile 应优先使用 rich handoff 生成的 `table-atomic-*-4096` 建议；如果部署不支持较大父 chunk，
先降低为部署允许值并接受 review warning，不要设置 `children_delimiter`。

## 8. 边界

- 不把 APOLLO 私有原始路径、本地 KB 名、真实服务地址或 live dataset 标识写入 public docs。
- 不在 `ragflow-doc-to-md` 中创建或修改 RAGFlow KB。
- 不默认启用 script-owned LLM judge、LLM 表格重写或 live disposable workflow。
- 不把 `$MPE_E$` / `$MPE_P$` 这类领域映射硬编码成全局 postprocess 规则；先用可审阅 sidecar
  和 fixture 验证收益。
