# RAGFlow Skills

Portable public skills for document-to-Markdown conversion, RAGFlow knowledge-base builds, and direct or host-assisted agentic RAGFlow querying.

## Layout

```text
packages/ragflow-skill-runtime/   # shared portable runtime
skills/ragflow-doc-to-md/         # raw documents -> Markdown handoff
skills/ragflow-kb-build/          # Markdown -> RAGFlow KB + validation
skills/ragflow-query/             # direct and host-assisted agentic query CLI
tools/build_release.py            # self-contained release artifact builder
tools/consumer_acceptance.py      # clean-consumer release artifact acceptance
tools/export_release_archives.py  # deterministic per-skill archive exporter
tools/live_integration_check.py   # opt-in live RAGFlow retrieval check
tools/platform_smoke_matrix.py    # cross-platform no-network smoke matrix
tools/release_hygiene_check.py    # public/private release hygiene gate
docs/                             # architecture and development plans
```

## Release Model

Development keeps one shared runtime source tree:

```text
packages/ragflow-skill-runtime/src/ragflow_skill_runtime/
```

Release artifacts vendor that runtime into each skill:

```text
scripts/_vendor/ragflow_skill_runtime/
```

This keeps development DRY while allowing Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent CLI tools to run the skills without editable installs or local machine paths.

## Stable Release

`v0.1.0` is the first stable release. Replace `OWNER` with the publishing GitHub namespace:

https://github.com/OWNER/ragflow-skills/releases/tag/v0.1.0

Download the per-skill `.tar.gz` archive for the target platform and verify checksums against `release-manifest.json`.

The `develop` branch may contain post-release changes. Use release tags for stable distribution artifacts.

## Host Agent Onboarding

Each public skill includes the same copy-paste onboarding prompt at:

```text
references/user-onboarding-prompt.md
```

Use it when giving the skills to another user. They can paste the prompt into Hermes, OpenClaw, Claude Code, opencode, or a similar controllable CLI agent. The host agent will then read the skill docs, ask only for missing RAGFlow, MinerU service, or local MinerU CLI settings, create a safe local config, run no-network smoke checks, and optionally run a disposable live RAGFlow E2E after user approval.

MinerU supports three execution paths: `mineru-cli` for a local installed MinerU binary, `mineru` / `mineru-agent` for the MinerU Agent API, and `mineru-sync` / `mineru-local` for self-hosted synchronous multipart `/parse` services on localhost, LAN, VPN, or HTTPS. In `auto`, local CLI is preferred when `MINERU_CLI_PATH`, `mineru.cli_path`, or `mineru` on `PATH` is available.

The prompt is duplicated intentionally so each skill archive is self-contained. The canonical source copies are:

```text
skills/ragflow-doc-to-md/references/user-onboarding-prompt.md
skills/ragflow-kb-build/references/user-onboarding-prompt.md
skills/ragflow-query/references/user-onboarding-prompt.md
```

Keep secrets out of the skill folders, repository, release artifacts, and reports. Use host-agent secret stores, environment variables, or private config files such as `~/.hermes/ragflow/config.local.yaml` or `~/.config/ragflow-skills/config.local.yaml`.

## Quality and Segmentation

On `develop`, `ragflow-doc-to-md` also produces `quality_report.json` and writes a lightweight `quality_gate` into `doc_manifest.json`. `ragflow-kb-build` refuses `BLOCKED` handoffs by default unless the user explicitly passes `--allow-blocked`.

Long Markdown files can be inspected with `python scripts/convert.py segment-plan ...` and materialized into ordinary `segments/*.md` files with `python scripts/convert.py split ...`; those segment directories can be ingested with the existing `ragflow-kb-build --input` path.

## Diagnostics

On `develop`, `ragflow-kb-build` includes read-only diagnostics: `scripts/probe.py` checks safe RAGFlow API compatibility, and `scripts/diagnose.py` explains KB manifest, parse-state, short-ID, duplicate-name, suffix-fragment, and zero-chunk symptoms without private database access.

`scripts/append.py` supports safe KB maintenance: it defaults to a non-mutating append plan, can optionally read a live before-snapshot, and only uploads when `--execute` is explicit.

`scripts/cleanup.py` also defaults to a non-mutating plan. Dataset deletion requires `--execute` plus exact dataset ID and KB name confirmation.

## Benchmark Validation

On `develop`, `ragflow-kb-build/scripts/validate.py --level benchmark` supports small public qrels, ranking metrics, threshold gates, baseline deltas, and query-type breakdowns:

```bash
python skills/ragflow-kb-build/scripts/validate.py \
  --kb-manifest ./run/kb_manifest.json \
  --level benchmark \
  --queries skills/ragflow-kb-build/templates/benchmark-queries.example.json \
  --qrels skills/ragflow-kb-build/templates/qrels.example.json \
  --gate-config skills/ragflow-kb-build/templates/benchmark-gate.example.json \
  --report-json ./run/benchmark.json \
  --report-md ./run/benchmark.md
```

The benchmark layer is deterministic and retrieval-only. It does not require an LLM key or private benchmark corpus.

## Profile Engineering

On `develop`, `ragflow-kb-build/scripts/profile.py` provides deterministic chunk-profile review:

```bash
python skills/ragflow-kb-build/scripts/profile.py lint --profile skills/ragflow-kb-build/templates/default-en-768.json
python skills/ragflow-kb-build/scripts/profile.py explain --profile skills/ragflow-kb-build/templates/default-zh-512.json
python skills/ragflow-kb-build/scripts/profile.py recommend --language en --doc-type manual --output ./run/recommended-profile.json
python skills/ragflow-kb-build/scripts/profile.py compare --report ./run/profile-a-validation.json --report ./run/profile-b-validation.json
```

Use `profile compare` after benchmark validation runs to rank profile experiments before accepting a KB profile change.

## Neutral Routing

On `develop`, `ragflow-query --mode auto` can use a user-owned routing config when no explicit KB is passed:

```bash
python skills/ragflow-query/scripts/query.py list-kbs \
  --routing-config skills/ragflow-query/templates/routing-config.example.json

python skills/ragflow-query/scripts/query.py route \
  "Which API configuration should I use?" \
  --routing-config skills/ragflow-query/templates/routing-config.example.json \
  --json

python skills/ragflow-query/scripts/query.py route-test \
  --routing-config skills/ragflow-query/templates/routing-config.example.json \
  --queries skills/ragflow-query/templates/route-test-queries.example.json \
  --report-md ./run/route-test.md
```

Routing is deterministic and private-data-free: users provide their own KB names, dataset IDs, hints, and retrieval params. Explicit `--dataset-id`, `--kb`, or `--kb-manifest` still takes precedence over auto routing.

## Agentic Observability

On `develop`, `ragflow-query ask` returns deterministic evidence weights and can write redaction-safe query trace reports:

```bash
python skills/ragflow-query/scripts/query.py ask \
  "What does this KB say?" \
  --kb-manifest ./run/kb_manifest.json \
  --mode agentic \
  --host-assisted \
  --json \
  --trace-json ./run/query_trace.json \
  --trace-md ./run/query_trace.md
```

After the host agent writes a final answer from retrieved evidence, `audit-citations` can check simple numeric citations such as `[1]` against the query output:

```bash
python skills/ragflow-query/scripts/query.py audit-citations \
  --query-output ./run/query.json \
  --answer-file ./run/answer.md \
  --report-json ./run/citation_audit.json \
  --report-md ./run/citation_audit.md
```

Use `diagnose-result` to combine saved query output, trace, and citation audit into one offline
diagnostic report:

```bash
python skills/ragflow-query/scripts/query.py diagnose-result \
  --query-output ./run/query.json \
  --trace-json ./run/query_trace.json \
  --citation-audit ./run/citation_audit.json \
  --expected-term "important concept" \
  --report-json ./run/query_diagnostic.json \
  --report-md ./run/query_diagnostic.md
```

This remains retrieval-only: no LLM key is required and script-owned synthesis is still deferred.

## Validation

```bash
PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -v

python3 tools/build_release.py --check
python3 tools/vendor_import_smoke.py
python3 tools/platform_smoke_matrix.py
python3 tools/release_hygiene_check.py
python3 tools/export_release_archives.py
python3 tools/consumer_acceptance.py --artifacts-dir release-artifacts --work-dir /tmp/ragflow-consumer-acceptance --overwrite
python3 tools/live_integration_check.py
```

## Scope

This repository contains only the public, portable RAGFlow skill suite. Private dedao-specific workflows are intentionally excluded.

Commercial SaaS agent sandboxes are not a v1 target. The intended public targets are programming-agent CLI environments the user controls or can configure, especially Hermes, OpenClaw, Claude Code, and opencode. A first-party SaaS platform should integrate document parsing, RAGFlow, and retrieval as native backend tools rather than by running these portable skill scripts inside a sandbox.

See `docs/08-cli-agent-integration.md` for CLI agent configuration and invocation patterns.
See `docs/09-high-value-feature-roadmap.md` for completed v0.2+ high-value features and the remaining optional synthesis backlog.
