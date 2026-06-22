# First Release Candidate

Status: active
Date: 2026-06-23

## RC Goal

Use `v0.1.0-rc1` to validate that the public RAGFlow skills can be distributed as self-contained artifacts before promoting a stable `v0.1.0`.

The RC is successful when:

- all release checklist commands pass;
- release archives and `release-manifest.json` are generated;
- a fresh-agent dry run can use the archives without repository context;
- live integration is either explicitly skipped because credentials are absent, or passes against a reachable test RAGFlow dataset.

## Release Commands

Run from `develop`, sequentially:

```bash
PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -v

python3 tools/build_release.py --check
python3 tools/vendor_import_smoke.py
python3 tools/platform_smoke_matrix.py
python3 tools/release_hygiene_check.py
python3 tools/export_release_archives.py
python3 tools/live_integration_check.py
```

`tools/live_integration_check.py` may return `skipped: true` for RC builds without test RAGFlow credentials. Do not treat that as a failure; treat it as an explicit statement that live endpoint validation has not happened yet.

## Fresh-Agent Dry Run

Give an agent only the artifact directory and this task:

```text
Use the public RAGFlow skill release artifacts in release-artifacts/ to perform a no-network fresh-user dry run. Work only under /tmp/ragflow-forward-test-agent and do not edit the repository. Unpack the three skill archives, create a tiny sample Markdown input, run ragflow-doc-to-md convert in passthrough mode, run ragflow-kb-build build --dry-run against the produced doc_manifest, and inspect ragflow-query enough to verify the host-assisted query interface is discoverable without calling a network endpoint. Report exact commands, success/failure, friction, and produced files.
```

Expected outputs:

- `doc_manifest.json` from `ragflow-doc-to-md`.
- Successful `ragflow-kb-build build --dry-run`.
- `ragflow-query --help` or `ragflow-query ask --help` confirms `--mode agentic` and `--host-assisted`.
- Notes about any confusing instructions or missing artifact affordances.

No-network dry-run example:

```bash
python3 ragflow-doc-to-md/scripts/convert.py --input ./input-docs --output ./handoff --mode passthrough --json
python3 ragflow-kb-build/scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name dry-run-sample --profile ./ragflow-kb-build/templates/default-en-768.json --dry-run --json
python3 ragflow-query/scripts/query.py --help
python3 ragflow-query/scripts/query.py ask --help
```

`build.py --dry-run` validates local inputs and prints JSON; it does not write `kb_manifest.json`.

## RC1 Forward-Test Result

The fresh-agent artifact dry run passed on 2026-06-23.

Observed outputs:

- Archives unpacked successfully under `/tmp/ragflow-forward-test-agent`.
- `ragflow-doc-to-md` produced `handoff/documents/sample.md` and `handoff/doc_manifest.json`.
- `ragflow-kb-build --dry-run` consumed the handoff manifest successfully without network access.
- `ragflow-query ask --help` exposed `--mode agentic` and `--host-assisted`.
- A no-env query probe failed before network work with the expected missing base URL error.

Follow-up fixes applied:

- Host-assisted query examples now include `--base-url` and `--api-key`.
- `ragflow-query` now states that host-assisted mode still retrieves from RAGFlow.
- `ragflow-kb-build` now states that dry-run does not write `kb_manifest.json`.

## Live Integration

When a test RAGFlow endpoint is available:

```bash
RAGFLOW_BASE_URL=https://ragflow.example.test \
RAGFLOW_API_KEY=... \
RAGFLOW_DATASET_ID=... \
python3 tools/live_integration_check.py
```

For a stronger live check, build a temporary KB from one Markdown file, then run validation:

```bash
python3 skills/ragflow-doc-to-md/scripts/convert.py --input ./sample-docs --output ./run/handoff --mode passthrough
python3 skills/ragflow-kb-build/scripts/build.py --doc-manifest ./run/handoff/doc_manifest.json --kb-name kb:rc-smoke --profile skills/ragflow-kb-build/templates/default-en-768.json --output ./run/kb_manifest.json
python3 skills/ragflow-kb-build/scripts/validate.py --kb-manifest ./run/kb_manifest.json --level smoke
```

Do not run the stronger live check against production datasets.

## Promotion

After RC validation:

1. Tag `develop` as `v0.1.0-rc1`.
2. Attach or store the three `.tar.gz` files plus `release-manifest.json`.
3. Collect forward-test and live-test notes.
4. Fix RC findings on `develop`.
5. Promote to `main` only after a clean RC pass.
