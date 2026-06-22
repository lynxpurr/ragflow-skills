# RAGFlow Skills

Portable public skills for document-to-Markdown conversion, RAGFlow knowledge-base builds, and direct or agentic RAGFlow querying.

## Layout

```text
packages/ragflow-skill-runtime/   # shared portable runtime
skills/ragflow-doc-to-md/         # raw documents -> Markdown handoff
skills/ragflow-kb-build/          # Markdown -> RAGFlow KB + validation
skills/ragflow-query/             # direct/agentic query CLI
tools/build_release.py            # self-contained release artifact builder
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

## Validation

```bash
PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -v

python3 tools/build_release.py --check
python3 tools/vendor_import_smoke.py
python3 tools/platform_smoke_matrix.py
```

## Scope

This repository contains only the public, portable RAGFlow skill suite. Private dedao-specific workflows are intentionally excluded.
