# User Onboarding Prompt

Give this prompt to a host agent such as Hermes, OpenClaw, Claude Code, opencode, or another controllable CLI agent after the RAGFlow skills are installed or unpacked.

The prompt asks the host agent to gather only missing service information, configure the skills safely, and run smoke or E2E validation without exposing secrets.

## Quick Hermes/OpenClaw Task Prompt

Use this shorter prompt when the host agent only needs to configure a remote MinerU FastAPI v2 parser for `ragflow-doc-to-md` and then guide the user through validation:

```text
请读取 ragflow-doc-to-md/SKILL.md、references/host-agent-setup.md 和 templates/ragflow-config.example.yaml，为我配置远程 MinerU FastAPI v2 文档解析。

请自行和我交互，只询问缺失信息，不要让我手动拼接命令。你需要确认：
- RAGFlow base URL、API key 或 secret 名称/位置。
- MinerU 服务是否是 FastAPI v2：/health、/tasks、/tasks/{task_id}、/tasks/{task_id}/result。
- MinerU base URL、API key 或 secret 名称/位置。
- SSL 是否校验；只有自签名或内网测试时才询问是否临时关闭。
- 是否需要解析 PDF / Office / 图片型文档，以及语言、OCR、表格、公式选项是否使用默认值。

请使用稳定配置文件，不要把真实 API key 写入 skill 目录、git 仓库、项目文档或 release artifacts。Hermes 默认使用 ~/.hermes/ragflow/config.local.yaml，OpenClaw 使用 ~/.config/openclaw/ragflow/config.local.yaml、/etc/openclaw/ragflow/config.local.yaml、/var/lib/openclaw/ragflow/config.local.yaml 或挂载的 secret/config 路径。设置 RAGFLOW_CONFIG 指向该文件。

配置文件中应明确：

doc_to_md:
  backend: mineru-fastapi

mineru:
  base_url: <MinerU FastAPI base URL>
  api_key: ${MINERU_API_KEY}
  timeout: 1800
  poll_interval: 3
  verify_ssl: true
  asset_mode: markdown_assets

请记住优先级：--mineru-base-url 高于 MINERU_BASE_URL，高于配置文件中的 mineru.base_url；--mineru-asset-mode 高于 MINERU_ASSET_MODE，高于配置文件中的 mineru.asset_mode。生产配置优先写入私有配置文件或环境变量；临时调试才使用命令行覆盖。正式入库前处理使用 markdown_assets，让 Markdown 图片引用落地到本地 documents/images/...；快速文本预览才使用 markdown_only。

请先运行无网络 smoke test，再在我确认后运行 MinerU backend probe、warmup 和一次最小转换验证。正式入库前处理必须使用 ragflow-doc-to-md pipeline，并从 stdout 或 doc_manifest.json 确认 handoff_mode: formal_ingest；如果看到 handoff_mode: thin_preview，只能把它当快速预览，不能当正式 KB 入库 handoff。所有报告只输出脱敏 endpoint、路径和结论，不输出 API key。
```

## Full Host-Agent Prompt

```text
请帮我配置并验证这一组 RAGFlow skills：

- ragflow-doc-to-md
- ragflow-kb-build
- ragflow-query

你的目标：
1. 自动识别当前 workspace 中这三个 skill 的位置。
2. 读取每个 skill 的 SKILL.md。
3. 优先读取 references/host-agent-setup.md，按其中的约定完成配置和测试。
4. 引导我提供缺失的 RAGFlow / MinerU 服务信息。
5. 自行创建安全的本机配置文件或环境变量。
6. 先执行无网络 smoke test。
7. 在我确认可以创建测试知识库后，执行真实 RAGFlow live E2E。
8. 最后给出中文验收报告和清理建议。

重要安全要求：
- 不要把真实 API key 写入 skill 文件夹、git 仓库、项目文档、release artifacts 或聊天总结。
- 不要在输出中明文打印 API key。
- 不要在配置片段、报告或注释里输出 API key 的前缀、后缀、局部片段或看起来像真实 token 的值；只写 `${ENV_VAR}`、secret 名称或已脱敏占位符。
- 优先使用宿主 agent 的 secret store、环境变量或私有 config 文件保存密钥。
- RAGFlow 和 MinerU 是外部服务，不要尝试从 skill 内启动或守护这些服务。
- 默认 RAGFlow / MinerU 可能在远程机器、LAN、VPN 或 HTTPS gateway 上，不要假设它们和 agent 在同一台机器。
- 先识别 MinerU 执行模式：`mineru-fastapi` 支持 MinerU 3.2+ FastAPI v2（`/tasks` 提交任务、`/tasks/{task_id}` 轮询、`/tasks/{task_id}/result` 读取 Markdown）；本机已安装 MinerU CLI 时可使用 `ragflow-doc-to-md --backend mineru-cli`，或在确实希望本地优先时保持 `auto`；`mineru` / `mineru-agent` 支持 MinerU Agent API（`/parse/file` 创建任务、上传文件、轮询任务、下载 Markdown）；`mineru-sync` / `mineru-local` 仅作为同步 multipart `/parse` legacy compatibility。默认 MinerU 可能是本机 CLI、内网远程服务、VPN、HTTPS gateway 或在线服务，不要把部署位置和协议混为一谈。
- 不确定 MinerU 协议时，不要把配置文件里的 `doc_to_md.backend` 从 `auto` 改成 `mineru`。确认 FastAPI v2 后用 `mineru-fastapi`，本机 CLI 可用 `mineru-cli` 或有意选择 `auto`，确认 Agent API 后用 `mineru`，确认同步 multipart `/parse` 后才用 `mineru-sync`。
- MinerU FastAPI endpoint 的配置优先级是：`--mineru-base-url` 高于 `MINERU_BASE_URL`，高于配置文件中的 `mineru.base_url`。生产配置优先使用私有 config 文件或环境变量；命令行参数只用于临时覆盖。
- 不要直接修改 release artifact 或 skill 里的 `scripts/_vendor`。如果需要新增 backend，请报告为源码级需求，由维护者修改 `packages/ragflow-skill-runtime` 后重新构建发布包。
- 正式 RAGFlow KB 入库前处理默认使用 `ragflow-doc-to-md pipeline`。普通 `convert` 输出的 `handoff_mode: thin_preview` 只用于快速预览；不要拿它和 legacy thick package 做正式能力对比，也不要直接进入 live build。
- 只询问缺失的信息，不要让我手动拼接每一条命令。

请先检查并报告：
- 当前目录结构中是否能找到三个 skill。
- 是否存在 templates/ragflow-config.example.yaml。
- 是否存在 references/host-agent-setup.md。
- 当前是否已有 RAGFLOW_CONFIG、RAGFLOW_BASE_URL、RAGFLOW_API_KEY。
- 当前是否已有 MINERU_CLI_PATH、MINERU_BASE_URL、MINERU_API_KEY。

如果缺少 RAGFlow 配置，请向我询问：
- RAGFlow base URL
- RAGFlow API key 或 secret 名称/位置
- 是否需要关闭 SSL 校验，仅在自签名或内网测试时使用

如果我要解析 PDF / Office / 图片型文档，请再向我询问：
- 是否使用 MinerU 服务
- 是否优先使用本机 MinerU CLI；如果是，MinerU CLI 路径或是否已经在 PATH 上
- MinerU 服务协议是 FastAPI v2、Agent API，还是同步 multipart /parse
- MinerU base URL
- MinerU API key 或 secret 名称/位置
- 语言、OCR、表格、公式等选项是否使用默认值

请按宿主环境选择配置路径：
- Hermes: ~/.hermes/ragflow/config.local.yaml
- OpenClaw: ~/.config/openclaw/ragflow/config.local.yaml、/etc/openclaw/ragflow/config.local.yaml、/var/lib/openclaw/ragflow/config.local.yaml 或挂载的 secret/config 路径
- Claude Code / opencode: ~/.config/ragflow-skills/config.local.yaml
- 只有在工作目录稳定且私有时，才使用 .ragflow/config.local.yaml

请基于 templates/ragflow-config.example.yaml 创建配置。真实密钥优先使用环境变量占位符，例如：

ragflow:
  base_url: https://ragflow.example.com
  api_key: ${RAGFLOW_API_KEY}
  timeout: 60
  verify_ssl: true

doc_to_md:
  # Remote Hermes-agent deployments should pin the intended converter.
  # Use mineru-fastapi for MinerU 3.2+ protocol-v2 async services.
  # Use auto only when local CLI discovery is intentionally allowed.
  backend: mineru-fastapi

mineru:
  # Optional local CLI example: /opt/mineru/bin/mineru
  cli_path: ${MINERU_CLI_PATH}
  cli_backend: pipeline
  # FastAPI v2 async example: https://mineru.example.internal
  # Agent API example: https://mineru.example.com/api/v1/agent
  # Legacy sync multipart example: http://mineru.example.internal:8777/api/v1
  base_url: https://mineru.example.internal
  api_key: ${MINERU_API_KEY}
  timeout: 1800
  poll_interval: 3
  verify_ssl: true
  asset_mode: markdown_assets
  language: ch
  page_range:
  enable_table: true
  is_ocr: false
  enable_formula: true

配置完成后，请设置 RAGFLOW_CONFIG 指向该配置文件。
如果用户临时提供 `--mineru-base-url` 或 `--mineru-asset-mode`，请说明它只覆盖本次命令；需要长期稳定运行时，应同步更新 `mineru.base_url` / `mineru.asset_mode` 或 `MINERU_BASE_URL` / `MINERU_ASSET_MODE`。

第一阶段：无网络 smoke test

请创建临时目录和一个很小的 Markdown 示例，然后运行：
- ragflow-doc-to-md passthrough，确认生成 doc_manifest.json
- ragflow-kb-build --dry-run，确认能消费 doc_manifest.json
- ragflow-query ask --help，确认 direct / agentic / host-assisted 参数可见

这一步不得连接 RAGFlow 或 MinerU。

旧一体化流程迁移说明：
- 转换和 handoff 产物由 ragflow-doc-to-md pipeline 接管。
- RAGFlow 配置建议由非密钥 ragflow_ingest_plan.yaml 接管；真实 RAGFlow endpoint 和 API key 仍只放私有配置或环境变量。
- 入库、解析、质量验证由 ragflow-kb-build 接管。
- 后续检索和 assistant 验证由 ragflow-query 接管。

第二阶段：可选的 MinerU 测试

如果我提供了测试 PDF / Office 文件，并且 MinerU 配置完整，请运行一次最小转换测试：
- 如果服务是 MinerU FastAPI v2，正式入库前处理使用 ragflow-doc-to-md pipeline --backend mineru-fastapi --mineru-asset-mode markdown_assets --postprocess-profile chunk-markers，并确认输出 Markdown、本地图片资产、postprocess_report.json、retrieval_hints.json 和 ragflow_ingest_plan.yaml
- 确认 pipeline stdout 或 doc_manifest.json 中的 handoff_mode 是 formal_ingest；若是 thin_preview，请重新运行 pipeline
- 如果本机 MinerU CLI 可用且用户希望本地优先，使用 ragflow-doc-to-md --backend auto 或 --backend mineru-cli，并确认输出 Markdown
- 如果服务是 MinerU Agent API 或兼容 gateway，使用 ragflow-doc-to-md --backend mineru
- 如果服务是同步 multipart /parse，使用 ragflow-doc-to-md --backend mineru-sync
- 如果没有可用 CLI 且服务协议无法识别，请报告协议差异并跳过，不要猜测 backend
- 生成正式 Markdown handoff；快速预览才单独使用 convert
- 报告转换产物路径和 warning

如果 MinerU 信息不完整、CLI 不可用且协议无法识别，请跳过并说明缺哪些字段或协议差异。

第三阶段：真实 RAGFlow live E2E

执行前先问我是否允许创建一次性测试 KB。

如果我允许，请使用一次性 KB 名称：
kb:ragflow-skills-e2e-YYYYMMDD-HHMM

然后执行：
- ragflow-doc-to-md pipeline 生成 doc_manifest.json、retrieval_hints.json 和 ragflow_ingest_plan.yaml
- 先确认 handoff_mode: formal_ingest，再运行 ragflow-kb-build inspect-handoff 和 --dry-run
- ragflow-kb-build --dry-run 消费 doc_manifest.json 和用户确认的 profile
- ragflow-kb-build 创建 RAGFlow KB、上传 Markdown、触发解析、等待完成
- ragflow-kb-build validate --level smoke
- ragflow-query --mode direct 查询
- ragflow-query --mode agentic --host-assisted 查询

请确认：
- dataset / KB 创建成功
- 文档上传成功
- parse 成功完成
- chunk 数大于 0
- smoke validation 通过
- direct query 返回 evidence
- host-assisted query 返回 evidence

清理要求：
- 测试结束后尝试删除一次性 KB。
- 如果脚本没有自动删除能力，请报告 KB 名称和 dataset id，让我清理。

最终请用中文报告：
- 使用的 skill 路径
- 使用的配置文件路径
- RAGFlow base URL，但隐藏 API key
- MinerU base URL，但隐藏 API key
- 无网络 smoke test 结果
- MinerU 测试结果，若跳过则说明原因
- live E2E 结果，若跳过则说明原因
- 创建的 KB 名称和 dataset id
- 上传文档数量、parse 状态、chunk 数
- validate smoke 结果
- direct / host-assisted 查询摘要
- 产生的 doc_manifest.json、kb_manifest.json、validation report、query output 路径
- 测试 KB 是否已清理
- 是否可以把当前配置视为可用

旧一体化流程退役前，请额外确认：
- 真实 MinerU FastAPI 样本文档已通过 pipeline 生成本地图片资产，quality gate 未因已落地图片 BLOCKED。
- handoff 中存在 postprocess_report.json、retrieval_hints.json、assistant_profile.json、assistant_test_plan.json 和 ragflow_ingest_plan.yaml。
- ragflow-kb-build inspect-handoff 和 --dry-run 均通过。
- 经我明确批准后，至少一个一次性 KB 完成 live build、parse、smoke validation、direct query 和 host-assisted query。
- 所有报告和总结均未暴露真实 API key、私有 endpoint 明文、个人路径或 release artifacts 外的临时目录。
```
