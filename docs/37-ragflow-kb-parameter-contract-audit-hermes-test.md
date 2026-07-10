# Hermes L0 Test For RAGFlow KB Parameter Contract Audit

Status: reusable L0 source-audit instruction; L1/L2 remain approval-gated
Date: 2026-07-10

## Purpose And Boundary

This instruction lets a Hermes agent independently replay the Stage 8B contract audit
for RAGFlow overlap and automatic metadata. It collects only the eight approved source
files from a reviewed deployment and the pinned upstream tag, then runs the repository's
offline audit tool.

Authorized by default:

- L0 source audit only;
- read public image/tag/version identities;
- copy the eight named source files into a private temporary run root;
- download the same eight public files from a pinned upstream tag;
- run local tests and `tools/ragflow_parameter_contract_audit.py`;
- generate sanitized JSON, Markdown, redaction, and Chinese summary reports.

Not authorized:

- any RAGFlow HTTP/API call, including read-only dataset calls;
- reading container environment variables, config files, secrets, databases, logs, or
  user data;
- dataset creation, update, upload, parse, reparse, delete, or cleanup;
- DeepDoc/native PDF tests;
- script-owned LLM/RAGAS calls;
- committing, pushing, or modifying product code.

If L0 evidence is insufficient, Hermes must stop with `approval_required` for L1 or L2.
It must not upgrade the test level on its own.

## Expected Contract Identity

The current reviewed target is:

- deployment version: `v0.25.5`;
- public deployment image: `infiniflow/ragflow:v0.25.5`;
- image digest:
  `sha256:1025603bd79a373ab0f65e8ee3730710a1bccfb2ba88fd443d57078ebbf24724`;
- upstream tag: `v0.25.5`;
- upstream commit: `90c76e73d072a2fba9ffdd8cdde694a9cb4a31af`.

Hermes must report a mismatch instead of silently replacing these values. A newer
deployment requires a new pinned audit, not reuse of the v0.25.5 conclusion.

## Required Source Files

Copy only these relative paths:

```text
api/utils/validation_utils.py
api/apps/restful_apis/dataset_api.py
api/apps/services/dataset_api_service.py
rag/app/naive.py
common/float_utils.py
web/src/pages/dataset/dataset-setting/form-schema.ts
web/src/pages/dataset/dataset-setting/configuration/common-item.tsx
rag/svr/task_executor.py
```

Do not copy the full deployment tree.

## Copy-Paste Hermes Task

Send the following block to Hermes. Replace angle-bracket placeholders only inside the
private Hermes session.

```text
请在当前 ragflow-skills 仓库执行 Stage 8B L0 参数合同审计。只允许离线源码审计，
不允许调用任何 RAGFlow HTTP/API，不允许创建、更新、上传、解析、重解析、删除 KB，
不允许 DeepDoc 测试，不允许脚本自有 LLM/RAGAS 调用。

先读取：
- docs/37-ragflow-kb-parameter-contract-audit-hermes-test.md
- docs/superpowers/specs/2026-07-10-kb-parameter-stage-8b-contract-audit-design.md
- docs/36-ragflow-kb-parameter-materialization-plan.md

执行边界：
1. 从仓库根目录开始，运行 git status --short --branch 和 git rev-parse HEAD。
2. 建立新的私有临时运行目录；不要把运行产物写进仓库。
3. 只读确认待审部署是 infiniflow/ragflow:v0.25.5，VERSION 为 v0.25.5，
   image digest 为
   sha256:1025603bd79a373ab0f65e8ee3730710a1bccfb2ba88fd443d57078ebbf24724。
4. 只从经确认的 RAGFlow 容器或已提取部署源码根复制文档列出的八个文件。
5. 从上游 tag v0.25.5 下载或提取同样八个文件；该 tag 固定到 commit
   90c76e73d072a2fba9ffdd8cdde694a9cb4a31af。
6. 不得读取容器环境变量、配置、secret、数据库、日志、用户数据、dataset/KB 内容。
7. 运行：
   python3 -m py_compile tools/ragflow_parameter_contract_audit.py
   python3 -m pytest packages/ragflow-skill-runtime/tests/test_ragflow_parameter_contract_audit.py -q
8. 使用 docs/37 中的参数运行 tools/ragflow_parameter_contract_audit.py，输出：
   - ragflow_parameter_contract_audit.json
   - ragflow_parameter_contract_audit.md
   - ragflow_parameter_contract_audit.redaction.json
9. 检查所有八组 deployment/upstream SHA-256 是否一致。
10. 检查 overlap_percent 是否为 runtime_only_not_api_writable，
    automatic_metadata 是否为 contract_conflict，Stage 8C eligible count 是否为 0。
11. 对 JSON、Markdown、redaction sidecar 和最终中文报告做敏感信息复核。
12. 如果需要任何 RAGFlow HTTP read-back，写 approval_required:L1 并停止。
13. 如果需要任何 create/update/parse/reparse/delete，写 approval_required:L2 并停止。

禁止输出：
- 容器名、私有 endpoint、API key/token 及其片段；
- 完整 home/config/run-root 路径；
- dataset id、document id、真实 KB 名称；
- 用户文档、chunk、数据库或日志内容。

最终返回一个简洁中文报告，包含：
- 仓库 commit 和工作区状态摘要；
- deployment/upstream 的公开版本身份；
- 八个文件是否逐一 digest 相同；
- overlap_percent 和 automatic_metadata 的分类与五层证据摘要；
- automatic metadata 的模型/provider、成本、异步 parse/reparse、metadata governance 风险；
- 每条命令的 pass/fail/skip；
- L1/L2 均未执行，并写明 skipped 或 approval_required；
- redaction 检查结论；
- 报告文件的私有相对位置或脱敏位置；
- 残余风险与下一步建议。
```

## Reference Command

After Hermes has prepared `<deployment-source-root>` and `<upstream-source-root>`, the
audit command is:

```bash
python3 tools/ragflow_parameter_contract_audit.py \
  --deployment-root <deployment-source-root> \
  --upstream-root <upstream-source-root> \
  --deployment-version v0.25.5 \
  --deployment-image infiniflow/ragflow:v0.25.5 \
  --deployment-image-digest sha256:1025603bd79a373ab0f65e8ee3730710a1bccfb2ba88fd443d57078ebbf24724 \
  --upstream-tag v0.25.5 \
  --upstream-commit 90c76e73d072a2fba9ffdd8cdde694a9cb4a31af \
  --report-json <private-report-root>/ragflow_parameter_contract_audit.json \
  --report-md <private-report-root>/ragflow_parameter_contract_audit.md \
  --redaction-report <private-report-root>/ragflow_parameter_contract_audit.redaction.json
```

## Hermes Final Report Template

```markdown
# Hermes RAGFlow Parameter Contract Audit Report

Date:
Agent:
Repository commit:
Worktree status: clean / dirty-with-described-files
Authorization level: L0 only

## Contract Identity

Deployment version:
Deployment image:
Deployment image digest:
Upstream tag:
Upstream commit:

## Source Integrity

Required files: 8
Complete file pairs:
Identical file pairs:
All required files identical: true/false
Drift or missing files:

## Candidate Results

| Candidate | Classification | Stage 8C Eligible | Main Evidence |
| --- | --- | --- | --- |
| overlap_percent | | | |
| automatic_metadata | | | |

## Automatic Metadata Side Effects

Model/provider dependency:
Potential cost:
Async per-chunk execution:
Parse/reparse requirement:
Metadata-governance impact:

## Commands

| Command | Status | Evidence |
| --- | --- | --- |
| py_compile | pass/fail | |
| focused tests | pass/fail | |
| contract audit | pass/fail | |

## Gated Levels

L1 read-only HTTP: skipped / approval_required
L2 disposable mutation: skipped / approval_required
RAGFlow HTTP calls performed: 0
RAGFlow writes performed: 0
Script-owned LLM/RAGAS calls: 0

## Redaction Review

Secrets exposed: no/yes
Private endpoints exposed: no/yes
Container names exposed: no/yes
Full private paths exposed: no/yes
Dataset/document/KB identifiers exposed: no/yes
User data or raw chunks exposed: no/yes

## Artifacts

JSON:
Markdown:
Redaction sidecar:

## Decision

Audit reproducible:
Stage 8B conclusion corroborated:
Stage 8C eligible candidates:
Residual risks:
Next action:
```

## Acceptance Criteria

The Hermes L0 replay passes when:

1. The repository tool tests pass.
2. All eight deployment/upstream file pairs are present and identical.
3. The audit completes with `ok: true`.
4. Overlap is `runtime_only_not_api_writable`.
5. Automatic metadata is `contract_conflict` with all side-effect gates visible.
6. No candidate is Stage 8C eligible.
7. L1 and L2 are not executed.
8. Reports contain no prohibited private or live values.

A passing L0 replay confirms source-contract evidence only. It is not live API
acceptance and does not authorize Stage 8C.
