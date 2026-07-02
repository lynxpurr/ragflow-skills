# 18. MinerU FastAPI 异步协议生产问题与修正计划

状态：P0/P1 已离线验证，P2 Markdown-first 质量增强已离线验证，结构化资产 sidecar 实现后续按需开启
日期：2026-07-02
适用范围：`ragflow-doc-to-md` 作为正式发布版 skill，运行在 Hermes agent 实例中，通过远程部署的 MinerU FastAPI 服务解析 PDF 文档。
结论：不做 `mineru-sync` 或自定义同步 `/parse` wrapper 的过渡修复。正式路线一步到位切换到 MinerU 3.2+ FastAPI v2 异步协议，即 `POST /tasks` 提交任务，轮询 `GET /tasks/{task_id}`，再读取 `GET /tasks/{task_id}/result`。

## 第一部分：问题客观描述

### 1.1 生产使用模式

目标生产形态如下：

- `ragflow-doc-to-md` 安装并运行在一个 Hermes agent 实例中。
- Hermes agent 所在机器不负责启动、监督或维护 MinerU 推理服务。
- PDF 解析由另一台服务器上已经部署好的 MinerU FastAPI 服务完成。
- `ragflow-doc-to-md` 只负责文件提交、任务轮询、结果抽取、handoff bundle 生成、错误报告和发布级验收。

因此，正式发布版本的关键能力不是本地 CLI 调度，也不是同步 HTTP 长连接，而是稳定支持远程 MinerU FastAPI 异步任务协议。

### 1.2 已观察到的问题

当前生产排查中的失败主要来自同步封装路径：

- 自定义 `/parse` wrapper 采用长连接同步请求，PDF 解析时间一长就容易触发客户端、服务端、反向代理之间的超时不一致。
- `mineru-sync` 依赖同步 multipart `/parse` 语义，无法自然表达 MinerU 后台任务的 `pending`、`running`、`completed`、`failed` 等状态。
- 同步 wrapper 内部异常会掩盖真正的 MinerU 失败原因，例如服务端 500、空输出、KeyError 或进程超时被折叠成同一类客户端失败。
- 长任务失败时缺少稳定的 `task_id`、轮询次数、阶段状态、耗时和远程错误详情，无法支撑生产定位。

这些现象说明：继续修补同步 wrapper 只能缓解局部故障，不能形成适合远程 MinerU 服务的正式发布路径。

### 1.3 当前 `ragflow-doc-to-md` 的能力边界

代码层面已经存在 `mineru-fastapi` 后端基础实现：

- 支持向 `/tasks` 提交 multipart 文件。
- 支持轮询 `/tasks/{task_id}`。
- 支持从 `/tasks/{task_id}/result` 抽取 Markdown。
- 支持 `GET /health` 的协议探测。
- CLI 已能显式选择 `--backend mineru-fastapi`。

但按照 Hermes agent 调用远程 MinerU FastAPI 的生产模式看，现状还不足以直接作为正式发布版本：

- 默认配置仍容易引导用户使用 `backend: auto`。在远程 MinerU 场景中，`auto` 可能优先选择本地 `mineru-cli`、同步后端或其他可用后端，不能保证走 FastAPI v2 异步协议。
- 发布级 smoke 和 consumer acceptance 主要覆盖已有后端，缺少针对 `mineru-fastapi` 的端到端假服务验收。
- 转换结果和诊断报告尚不足以记录远程异步任务的关键字段，例如 `task_id`、最终状态、轮询次数、远程耗时、HTTP 状态码、失败阶段和错误分类。
- 对远程服务常见失败的处理还需要收敛，包括连接失败、DNS 失败、TLS 失败、429、502、503、504、轮询超时、任务失败和结果缺失。
- TLS/证书校验策略需要明确。远程服务可能使用企业 CA、自签名证书或内网域名，配置和报告必须可控且不泄露敏感信息。
- 结果资产策略需要明确。当前正式目标应以 Markdown handoff 为主，图片、content list、middle json 等 sidecar 资产如果不纳入首版，就必须在文档和验收中明确边界。
- 文档、模板和报告必须避免包含真实 API key、个人路径、私有 IP、机器标识或一次性生产命令。

### 1.4 协议不匹配的核心风险

正式版本必须对准 MinerU FastAPI v2，而不是兼容任意 MinerU-like HTTP 服务。

目标服务必须至少满足：

- `GET /health` 返回健康状态，并能识别 `protocol_version: 2`。
- `POST /tasks` 接收 multipart 文件字段。
- `GET /tasks/{task_id}` 返回可轮询任务状态。
- `GET /tasks/{task_id}/result` 在任务完成后返回可抽取的 Markdown 内容。

如果远程服务只提供同步 `/parse`、`/file_parse` 或自定义 JSON 包装层，则不能作为正式 `ragflow-doc-to-md` 发布路径。它可以保留为遗留兼容能力，但不应进入本次修正方案。

## 第二部分：修正方案

### 2.1 总体决策

正式发布版只推荐一种远程 MinerU 集成方式：

- 后端显式配置为 `mineru-fastapi`。
- 服务端显式满足 MinerU FastAPI v2 异步任务协议。
- `mineru-sync` 和自定义同步 `/parse` wrapper 退为 legacy compatibility，不再作为生产修正目标。
- `auto` 不用于远程 MinerU-only 部署。远程生产配置必须显式指定后端，避免运行时漂移。

### 2.2 Hermes agent 推荐配置

配置模板应为远程 MinerU 场景提供显式 profile，例如：

```yaml
doc_to_md:
  backend: mineru-fastapi

mineru:
  base_url: https://mineru.example.internal
  api_key: ${MINERU_API_KEY}
  timeout: 1800
  poll_interval: 3
  verify_ssl: true
  language: ch
  is_ocr: false
  enable_table: true
  enable_formula: true
```

环境变量形式应等价支持：

```bash
DOC_TO_MD_BACKEND=mineru-fastapi
MINERU_BASE_URL=https://mineru.example.internal
MINERU_API_KEY=<redacted>
DOC_TO_MD_TIMEOUT=1800
```

文档中所有示例必须使用占位符，不出现真实密钥、个人路径、私有主机名或一次性生产文件路径。

### 2.3 FastAPI v2 协议适配要求

请求映射：

- `POST {base_url}/tasks`
- 文件字段：`files`
- 鉴权：配置 API key 时发送 `Authorization: Bearer <token>`
- 表单字段：
  - `lang_list`: 默认 `ch`
  - `backend`: 默认 `pipeline`
  - `parse_method`: `is_ocr=true` 时为 `ocr`，否则为 `auto`
  - `formula_enable`: 来自 `mineru.enable_formula`
  - `table_enable`: 来自 `mineru.enable_table`
  - `return_md`: `true`
  - `return_images`: 首版默认 `false`
  - `return_content_list`: 首版默认 `false`
  - `return_middle_json`: 首版默认 `false`
  - `response_format_zip`: `false`

状态处理：

- 等待态：`pending`、`queued`、`processing`、`running`
- 成功态：`completed`、`done`
- 失败态：`failed`、`error`
- 未识别状态必须作为协议错误报告，不能静默重试到总超时。

结果抽取：

- 优先读取 `results.<document_stem>.md_content`。
- 可兼容读取 `markdown`、`content`、`text`、`md`、`result` 等现有测试覆盖字段。
- 任务完成但 Markdown 为空时必须失败，并给出明确错误：远程任务完成但未产生 Markdown。

### 2.4 远程错误处理与重试策略

`mineru-fastapi` 后端应采用有界重试，而不是无限等待：

- `POST /tasks` 对连接重置、临时 DNS 失败、429、502、503、504 可重试。
- `GET /tasks/{task_id}` 对 429、502、503、504 可重试并继续轮询。
- `GET /tasks/{task_id}/result` 对临时 5xx 可短重试。
- 400、401、403、404、422 应归类为配置错误或协议错误，默认不重试。
- 总耗时受 `mineru.timeout` 控制，单次请求超时、轮询间隔和重试退避都必须计入总预算。

错误报告至少需要区分：

- `not_configured`
- `health_unavailable`
- `wrong_protocol`
- `auth_failed`
- `request_timeout`
- `task_failed`
- `result_missing`
- `result_empty`
- `transient_remote_error`
- `protocol_error`

### 2.5 可观测性与报告

转换报告、backend probe 报告或 handoff sidecar 应补充远程异步任务信息：

- backend：`mineru-fastapi`
- redacted endpoint
- `task_id`
- submit duration
- poll count
- final remote status
- result fetch duration
- total duration
- timeout budget
- error category
- redaction status

报告里只能出现脱敏 endpoint，不能出现 API key、完整 Authorization header、个人目录或生产 PDF 原始路径。

### 2.6 TLS 和网络配置

远程部署必须明确 TLS 策略：

- 默认启用证书校验。
- 企业 CA 通过 Python/系统信任链加载；当前首版配置面显式暴露 `verify_ssl`，不引入单独的 `ca_bundle` 文件管理。
- 如需临时关闭校验，必须显式配置并在报告中标记为不推荐状态。
- backend probe 的网络检查仍应由 `--network-check` 显式开启，避免文档或验收命令误触真实服务。

### 2.7 结果资产策略

正式首版建议采用 Markdown-first 交付：

- 必须产出 `documents/*.md`。
- 必须产出 `doc_manifest.json`。
- 必须产出质量或转换报告。
- 默认不要求保存 MinerU 图片、middle json、model output、content list。
- `runtime_report.json` 的 `remote_attempts[].asset_policy` 必须显式记录：
  - `mode: markdown_only`
  - `requested.return_images: false`
  - `requested.return_content_list: false`
  - `requested.return_middle_json: false`
  - `manifest_assets: false`

如果后续要支持图片和结构化 sidecar，应作为独立增强项实现，并明确输出目录、manifest schema、RAGFlow handoff 兼容方式和脱敏规则。

未来资产 sidecar 草案如下，本轮不写出该 sidecar：

```json
{
  "schema": "ragflow_mineru_fastapi_asset_sidecar_v1",
  "source_path": "paper.pdf",
  "markdown_path": "documents/paper.md",
  "task_id": "task-id",
  "assets": {
    "images": [
      {
        "path": "documents/images/paper/chart.png",
        "source_key": "chart.png",
        "sha256": "..."
      }
    ],
    "content_list": "artifacts/mineru/paper.content_list.json",
    "middle_json": "artifacts/mineru/paper.middle.json"
  },
  "redaction": {
    "endpoint_redacted": true,
    "secrets_redacted": true
  }
}
```

该 schema 真正启用前必须同步更新 `doc_manifest.json` 的资产引用、`artifact_index.json`、RAGFlow handoff dry-run 验收和脱敏测试。

### 2.8 Markdown 质量 gate

P2 将质量报告从“文件存在/图片存在”扩展为 Markdown-first 质量信号：

- 空 Markdown：`markdown_empty`，阻断。
- PDF 内容或页信号过低：`page_signal_low`，要求人工复核。
- 替换字符或控制字符比例过高：`garbled_text_high_ratio`，阻断。
- 表格型源文件没有 Markdown 表格结构：`table_structure_missing`，要求人工复核。
- 数学公式分隔符不平衡：`formula_suspicious_unbalanced_delimiter`，要求人工复核。

质量报告的每个文档条目应包含 `quality_signals`，记录行数、标题数、表格数、公式标记数、页标记数、替换字符比例和控制字符比例。

### 2.9 验证命令

网络探测使用占位符环境变量：

```bash
python3 skills/ragflow-doc-to-md/scripts/convert.py backend probe \
  --backend mineru-fastapi \
  --mineru-base-url "$MINERU_BASE_URL" \
  --mineru-api-key "$MINERU_API_KEY" \
  --network-check \
  --json
```

远程 warmup 使用小型公开 fixture：

```bash
python3 skills/ragflow-doc-to-md/scripts/convert.py backend warmup \
  --backend mineru-fastapi \
  --mineru-base-url "$MINERU_BASE_URL" \
  --mineru-api-key "$MINERU_API_KEY" \
  --fixture ./tests/fixtures/tiny.pdf \
  --fail-on-failed \
  --json
```

转换验收：

```bash
python3 skills/ragflow-doc-to-md/scripts/convert.py \
  --input ./tests/fixtures/tiny.pdf \
  --output /tmp/ragflow-doc-to-md-handoff \
  --backend mineru-fastapi \
  --mineru-base-url "$MINERU_BASE_URL" \
  --mineru-api-key "$MINERU_API_KEY" \
  --json
```

这些命令不得写入正式文档中的真实 endpoint、真实 key 或个人文件路径。

### 2.10 gated live validation runbook

真实远程 MinerU 验证必须由用户显式提供 endpoint、授权和批准，且仅使用可公开的小型 fixture：

1. 准备占位符环境变量，不把真实值写入仓库、文档或 shell 历史片段：
   `DOC_TO_MD_BACKEND=mineru-fastapi`、`MINERU_BASE_URL`、`MINERU_API_KEY`、`MINERU_VERIFY_SSL=true`。
2. 先运行 `backend probe --network-check --json --redaction-report <path>`，确认 `protocol_version` 为 `2`。
3. 再运行 `backend warmup --fixture <tiny-public.pdf> --fail-on-failed --json --redaction-report <path>`。
4. 最后运行正式转换到一次性输出目录，并保留 `doc_manifest.json`、`quality_report.json`、`runtime_report.json` 和 redaction sidecar。
5. 只共享脱敏后的报告摘要，不共享原始 endpoint、Authorization header、生产 PDF 路径或包含敏感文件名的输出目录。
6. 若需要清理远端任务缓存或对象存储，必须由 MinerU 服务运维侧执行；本 skill 不调用任何远端清理或管理 API。

## 第三部分：修正开发任务清单和计划

### 3.1 P0：发布阻断项

- [x] 重写本问题文档，移除同步 wrapper 过渡方案、真实密钥、个人路径和生产机器细节。
- [x] 更新 `skills/ragflow-doc-to-md/templates/ragflow-config.example.yaml`，为远程 Hermes agent 场景提供显式 `mineru-fastapi` 配置示例。
- [x] 更新 `skills/ragflow-doc-to-md/SKILL.md`，说明远程 MinerU FastAPI 部署必须显式使用 `DOC_TO_MD_BACKEND=mineru-fastapi`，不推荐使用 `auto`。
- [x] 在 `tools/platform_smoke_matrix.py` 增加 fake MinerU FastAPI v2 服务 smoke，覆盖 `/health`、`/tasks`、状态轮询和 `/result`。
- [x] 在 `tools/consumer_acceptance.py` 增加 `mineru-fastapi` 验收路径，确认生成 handoff bundle 并能进入后续 dry-run。
- [x] 增加脱敏检查，确保 FastAPI endpoint、Authorization header、API key、个人路径不会进入 Markdown 报告、JSON 报告或 handoff sidecar。

验收标准：

- fake `mineru-fastapi` smoke 能在无真实 MinerU 服务时稳定通过。
- `backend probe --backend mineru-fastapi --network-check` 能正确识别健康、未配置、错误协议和认证失败。
- 远程-only 配置文档不再推荐 `backend: auto`。
- 文档和报告中不含真实密钥、个人路径或私有 endpoint。

### 3.2 P1：生产可用性增强

- [x] 为 `mineru-fastapi` 转换结果补充异步任务可观测字段：`task_id`、`poll_count`、`final_status`、阶段耗时、总耗时和错误分类。
- [x] 增加有界 retry/backoff 机制，覆盖提交、轮询、结果拉取中的临时网络错误和 429/5xx。
- [x] 增强 health probe 严格性：协议版本缺失、协议版本不匹配、状态字段异常时必须返回 `wrong_protocol` 或明确错误分类。
- [x] 增加任务状态解析测试，覆盖 `pending`、`queued`、`processing`、`running`、`completed`、`done`、`failed`、`error` 和未知状态。
- [x] 增加结果缺失和空 Markdown 测试，确保失败信息可操作。
- [x] 明确 TLS 配置：默认校验证书，支持企业 CA 配置或记录系统信任链要求。

验收标准：

- 网络瞬断或临时 5xx 不会立刻导致转换失败，但总等待时间仍受 `mineru.timeout` 约束。
- 远程任务失败时，用户能从报告中看到失败阶段、远程状态和脱敏后的 endpoint。
- 未完成、空结果、协议不兼容都能产生稳定错误类别。

### 3.3 P2：结果质量与资产增强

- [x] 评估是否支持 `return_images`、`return_content_list`、`return_middle_json`，并设计 sidecar 输出 schema。
- [x] 明确 Markdown-only 首版不启用图片资产保存；`runtime_report.json` 记录 `asset_policy.manifest_assets=false`，后续真正启用时再补 manifest 引用、路径规范、清理策略和 RAGFlow handoff 兼容测试。
- [x] 增强 Markdown 质量 gate，区分空文档、页数过低、乱码比例过高、表格丢失和公式解析异常。
- [x] 编写 gated live validation runbook，仅在用户显式提供 endpoint 和授权后运行真实远程 MinerU 验证。

验收标准：

- Markdown-only 首版边界清晰，不误导用户以为图片或结构化 sidecar 已经进入正式交付。
- 如果后续启用资产增强，生成物必须进入 manifest，并通过脱敏和平台 smoke；当前首版以 `asset_policy` 明确记录未启用。

### 3.4 推荐执行顺序

1. 完成 P0 文档、配置模板和发布验收补齐，先保证正式路径清晰且可离线验证。
2. 完成 P1 的可观测性、错误分类、重试和 TLS 策略，使远程生产故障可诊断。
3. P2 当前完成 Markdown-first 质量增强和资产策略固化；真实图片和结构化 sidecar 输出保持为后续按需增强。

### 3.5 最终发布门槛

发布前至少满足：

- `python3 -m py_compile` 覆盖 runtime 和 CLI 入口。
- `python3 -m pytest` 覆盖 `mineru-fastapi` runtime、CLI、probe、warmup、错误分类和脱敏测试。
- `tools/platform_smoke_matrix.py` 包含 fake `mineru-fastapi` 路径并通过。
- `tools/consumer_acceptance.py` 包含 fake `mineru-fastapi` 路径并通过。
- Hermes agent 示例配置显式使用 `mineru-fastapi`。
- `ragflow-kb-build --dry-run` 能消费 `ragflow-doc-to-md` 生成的 handoff bundle。
- 所有公开文档、模板、报告和测试 fixture 都不包含真实密钥、个人路径或私有 endpoint。
