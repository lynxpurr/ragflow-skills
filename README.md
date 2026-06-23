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

This keeps development DRY while allowing Claude Code, OpenClaw, Hermes, and SaaS agent sandboxes to run the skills without editable installs or local machine paths.

## Current Release Candidate

`v0.1.0-rc1` is available as a GitHub prerelease:

https://github.com/lynxpurr/ragflow-skills/releases/tag/v0.1.0-rc1

Download the per-skill `.tar.gz` archive for the target platform and verify checksums against `release-manifest.json`.

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
