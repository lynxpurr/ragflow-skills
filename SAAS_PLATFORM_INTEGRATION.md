# SaaS Platform Integration Plan

Status: design proposal
Date: 2026-06-23

## Goal

Build first-class document parsing, RAGFlow knowledge-base generation, validation, and retrieval capabilities inside the user's own SaaS agent platform.

The public `ragflow-skills` release remains useful for Hermes, OpenClaw, Claude Code, and third-party code sandboxes. Inside the user's own SaaS platform, however, the better product shape is a native managed-tool architecture:

```text
Agent / User
  -> Platform tool facade
  -> LangGraph workflow
  -> Managed backend services
  -> Artifacts, reports, and answers
```

This avoids exposing raw RAGFlow, MinerU, or Pandoc details to users and keeps service credentials out of code sandboxes.

## Core Principle

Do not make skills start or manage long-running services.

Skills and agent tools should be clients. The SaaS platform should own:

- service deployment;
- secret storage;
- service discovery;
- network routing;
- retry and queue policy;
- tenant isolation;
- audit logs;
- health checks;
- cleanup policies.

## Two Distribution Modes

### Public Portable Mode

Use for external platforms that the user does not fully control:

- Hermes agent;
- OpenClaw deployments outside the SaaS backend;
- Claude Code;
- third-party SaaS code sandboxes.

Shape:

- vendored CLI skills;
- environment-variable configuration;
- HTTPS endpoints;
- no daemon requirement;
- no local machine paths;
- no secrets bundled in artifacts.

### Native SaaS Mode

Use for the user's own SaaS platform.

Shape:

- RAGFlow, MinerU, and conversion workers are managed platform services;
- platform UI exposes connectors and tool toggles;
- LangGraph orchestrates end-to-end workflows;
- code sandboxes receive only scoped tool access or short-lived environment variables;
- users interact with product concepts such as "Parse document", "Create KB", and "Query KB".

## Managed Backend Services

### RAGFlow Service

Role:

- long-running vector knowledge-base service;
- dataset creation;
- Markdown document upload;
- parse trigger and status polling;
- retrieval API.

Deployment:

- Docker Compose, Kubernetes, or platform service runtime;
- internal service name such as `ragflow-api`;
- external HTTPS gateway only when needed by sandbox or external agents.

Platform config:

```text
RAGFLOW_BASE_URL
RAGFLOW_API_KEY
RAGFLOW_TIMEOUT
RAGFLOW_VERIFY_SSL
```

Product UI should hide raw implementation details where possible and expose a connection profile:

```text
RAGFlow
  Enabled: true
  Connection: workspace-ragflow-primary
  Default KB policy: per-project / per-agent / user-selected
  Test connection
```

### MinerU Service

Role:

- heavy PDF and Office document parsing;
- OCR or layout-aware extraction;
- Markdown generation.

Deployment:

- long-running service or worker pool;
- GPU-aware scheduling if needed;
- queue for large files;
- object storage for uploaded inputs and generated Markdown.

Platform config:

```text
MINERU_BASE_URL
MINERU_API_KEY
MINERU_TIMEOUT
```

Recommended tool facade:

```text
parse_document(file, backend="mineru")
convert_to_markdown(file, backend="mineru")
```

The public skill can also support MinerU through a neutral remote converter contract:

```text
DOC_TO_MD_BACKEND=remote
DOC_TO_MD_REMOTE_URL=https://converter.example.com/api/convert
DOC_TO_MD_REMOTE_API_KEY=...
```

### Pandoc Worker

Role:

- stateless conversion for supported Office, EPUB, and markup formats;
- fallback when MinerU is not required.

Deployment options:

- preferred: install `pandoc` in the sandbox or worker image;
- alternative: run a conversion worker service if sandbox images must stay minimal.

Pandoc usually does not need to be a long-running HTTP service. It can be a worker process invoked by a job runner.

### Object Storage

Role:

- raw uploaded files;
- generated Markdown;
- handoff manifests;
- KB manifests;
- validation reports;
- query evidence packages.

Recommended paths:

```text
artifacts/{tenant}/{project}/{job_id}/raw/
artifacts/{tenant}/{project}/{job_id}/markdown/
artifacts/{tenant}/{project}/{job_id}/doc_manifest.json
artifacts/{tenant}/{project}/{job_id}/kb_manifest.json
artifacts/{tenant}/{project}/{job_id}/validation_report.json
```

### Job Queue

Role:

- async document parsing;
- batch KB ingestion;
- parse-status polling;
- validation and benchmark runs.

Use a queue or workflow runtime for jobs longer than one sandbox turn.

## Platform Tool Facade

Expose high-level tools to agents instead of raw services.

Recommended tools:

```text
parse_document
create_knowledge_base
add_documents_to_knowledge_base
validate_knowledge_base
query_knowledge_base
agentic_rag_query
inspect_knowledge_base
```

These tools can be implemented as platform-native LangGraph nodes or service calls. They may reuse code and contracts from `ragflow-skills`, but they should not require agents to shell out to the public skill scripts inside the SaaS product path.

## LangGraph Workflows

### Document To Markdown Graph

```text
Receive file
  -> Detect type
  -> Select backend
       - builtin text/html
       - Pandoc
       - MinerU
       - remote converter
  -> Convert to Markdown
  -> Normalize filenames
  -> Write doc_manifest.json
  -> Store artifacts
```

### Knowledge Base Build Graph

```text
Receive doc_manifest
  -> Select RAGFlow connection
  -> Select chunk profile
  -> Create dataset
  -> Upload Markdown documents
  -> Trigger parse
  -> Poll parse status
  -> Write kb_manifest.json
  -> Store artifacts
```

### Knowledge Base Validation Graph

```text
Receive kb_manifest
  -> Run smoke query
  -> Optionally run regression query set
  -> Compute metrics
  -> Write validation_report.json
  -> Write validation_report.md
```

### Agentic Query Graph

```text
Receive user question
  -> Resolve KB / dataset
  -> Retrieve chunks from RAGFlow
  -> Optional rerank / filter
  -> Build evidence package
  -> Synthesize answer with citations
  -> Return answer and sources
```

Current public `ragflow-query --mode agentic --host-assisted` maps well to the "Build evidence package" stage. In the native SaaS path, final synthesis can be handled by the platform's normal LLM layer.

## Configuration Model

### Best Default

Use platform-managed connection profiles.

```text
connection_id: workspace-ragflow-primary
service_type: ragflow
base_url: stored in backend config
api_key: stored in secret store
scopes: project / workspace / tenant
```

Agents should receive a connection name or KB id, not raw API keys.

### Environment Variables

Environment variables remain the best compatibility layer for portable skills and sandbox execution:

```text
RAGFLOW_BASE_URL
RAGFLOW_API_KEY
DOC_TO_MD_BACKEND
DOC_TO_MD_REMOTE_URL
DOC_TO_MD_REMOTE_API_KEY
MINERU_BASE_URL
MINERU_API_KEY
```

The SaaS platform can inject these only into trusted tool execution environments. Avoid exposing them to arbitrary user-visible logs.

### CLI Flags

CLI flags are useful for debugging and local smoke tests, but avoid passing secrets via command-line flags in production because they can appear in process listings and logs.

## Service Persistence

Persistent services:

- RAGFlow;
- MinerU service or worker pool;
- object storage;
- metadata database;
- queue / workflow engine;
- optional query gateway.

Not persistent by default:

- `ragflow-doc-to-md` CLI;
- `ragflow-kb-build` CLI;
- `ragflow-query` CLI;
- consumer acceptance checks;
- Pandoc process invocation.

Use platform service management for persistence:

- Docker Compose restart policies;
- Kubernetes Deployments;
- systemd;
- health checks and readiness probes;
- queue retry policy;
- autoscaling where needed.

## UI Model

Admin or workspace settings:

```text
Document Parsing
  [x] Builtin text/html
  [x] Pandoc
  [x] MinerU
      Connection: mineru-primary
      Test conversion

RAGFlow
  [x] Enable RAGFlow
      Connection: ragflow-primary
      Test connection

Agent Tools
  [x] parse_document
  [x] create_knowledge_base
  [x] validate_knowledge_base
  [x] query_knowledge_base
  [x] agentic_rag_query
```

Users should not normally configure microservice ports. The backend should map connection profiles to internal service names, ports, gateways, and secrets.

## Security Requirements

- Store API keys in platform secret storage.
- Do not write secrets into manifests.
- Do not include secrets in release artifacts.
- Do not print secrets in command output.
- Redact logs.
- Scope RAGFlow access by tenant, workspace, or project.
- Enforce egress allowlists for code sandboxes.
- Prefer short-lived tokens when a sandbox must call a gateway.
- Audit KB creation, document upload, and retrieval calls.

## Recommended Evolution

### Phase A: Native Connector Foundation

- Add RAGFlow connection profiles.
- Add MinerU / remote converter connection profiles.
- Add secret store integration.
- Add health checks.
- Add platform env injection for internal tool workers.

### Phase B: Managed Document And KB Workflows

- Implement `DocumentToMarkdownGraph`.
- Implement `KnowledgeBaseBuildGraph`.
- Store doc and KB manifests as platform artifacts.
- Add job progress and retry support.

### Phase C: Native Retrieval And Agentic Query

- Implement `query_knowledge_base`.
- Implement `agentic_rag_query`.
- Add citations and evidence packages.
- Add optional reranking.

### Phase D: Quality And Operations

- Add validation reports.
- Add scheduled regression watchdog.
- Add parse and retrieval metrics.
- Add cleanup policies for temporary KBs.

## Relationship To Public Skills

Keep both paths:

```text
Public external path:
  portable skill artifacts + CLI + env config

Native SaaS path:
  managed services + LangGraph workflows + platform tools
```

The public skills are still valuable as:

- external distribution artifacts;
- CLI fallback;
- reference implementation for manifests and command semantics;
- compatibility layer for Hermes, OpenClaw, Claude Code, and third-party sandboxes.

The native SaaS path should provide the best product experience by hiding endpoints, secrets, ports, and daemon management behind platform-managed connectors and tools.
