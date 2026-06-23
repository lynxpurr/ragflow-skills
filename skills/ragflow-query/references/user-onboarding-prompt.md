# User Onboarding Prompt

Give this prompt to a host agent such as Hermes, OpenClaw, Claude Code, opencode, or another controllable CLI agent after the RAGFlow skills are installed or unpacked.

The prompt asks the host agent to gather only missing service information, configure the skills safely, and run smoke or E2E validation without exposing secrets.

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
- 先识别 MinerU 服务协议：`ragflow-doc-to-md --backend mineru` / `mineru-agent` 支持 MinerU Agent API（`/parse/file` 创建任务、上传文件、轮询任务、下载 Markdown）；`--backend mineru-sync` / `mineru-local` 支持同步 multipart `/parse` 服务。默认 MinerU 可能在内网、远程机器、VPN、HTTPS gateway 或本机上，不要把部署位置和协议混为一谈。
- 不确定 MinerU 协议时，不要把配置文件里的 `doc_to_md.backend` 从 `auto` 改成 `mineru`。确认 Agent API 后用 `mineru`，确认同步 multipart `/parse` 后用 `mineru-sync`。
- 不要直接修改 release artifact 或 skill 里的 `scripts/_vendor`。如果需要新增 backend，请报告为源码级需求，由维护者修改 `packages/ragflow-skill-runtime` 后重新构建发布包。
- 只询问缺失的信息，不要让我手动拼接每一条命令。

请先检查并报告：
- 当前目录结构中是否能找到三个 skill。
- 是否存在 templates/ragflow-config.example.yaml。
- 是否存在 references/host-agent-setup.md。
- 当前是否已有 RAGFLOW_CONFIG、RAGFLOW_BASE_URL、RAGFLOW_API_KEY。
- 当前是否已有 MINERU_BASE_URL、MINERU_API_KEY。

如果缺少 RAGFlow 配置，请向我询问：
- RAGFlow base URL
- RAGFlow API key 或 secret 名称/位置
- 是否需要关闭 SSL 校验，仅在自签名或内网测试时使用

如果我要解析 PDF / Office / 图片型文档，请再向我询问：
- 是否使用 MinerU 服务
- MinerU 服务协议是 Agent API，还是同步 multipart /parse
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
  # Keep auto unless the MinerU protocol is confirmed.
  # Use mineru/mineru-agent for Agent API; use mineru-sync/mineru-local for sync multipart /parse.
  backend: auto

mineru:
  # Agent API example: https://mineru.example.com/api/v1/agent
  # Sync multipart example: http://mineru.internal:8777/api/v1
  base_url: https://mineru.example.com/api/v1/agent
  api_key: ${MINERU_API_KEY}
  timeout: 300
  poll_interval: 3
  language: ch
  page_range:
  enable_table: true
  is_ocr: false
  enable_formula: true

配置完成后，请设置 RAGFLOW_CONFIG 指向该配置文件。

第一阶段：无网络 smoke test

请创建临时目录和一个很小的 Markdown 示例，然后运行：
- ragflow-doc-to-md passthrough，确认生成 doc_manifest.json
- ragflow-kb-build --dry-run，确认能消费 doc_manifest.json
- ragflow-query ask --help，确认 direct / agentic / host-assisted 参数可见

这一步不得连接 RAGFlow 或 MinerU。

第二阶段：可选的 MinerU 测试

如果我提供了测试 PDF / Office 文件，并且 MinerU 配置完整，请运行一次最小转换测试：
- 如果服务是 MinerU Agent API 或兼容 gateway，使用 ragflow-doc-to-md --backend mineru
- 如果服务是同步 multipart /parse，使用 ragflow-doc-to-md --backend mineru-sync
- 如果协议无法识别，请报告协议差异并跳过，不要猜测 backend
- 生成 Markdown handoff
- 报告转换产物路径和 warning

如果 MinerU 信息不完整或协议无法识别，请跳过并说明缺哪些字段或协议差异。

第三阶段：真实 RAGFlow live E2E

执行前先问我是否允许创建一次性测试 KB。

如果我允许，请使用一次性 KB 名称：
kb:ragflow-skills-e2e-YYYYMMDD-HHMM

然后执行：
- ragflow-doc-to-md 生成 doc_manifest.json
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
```
