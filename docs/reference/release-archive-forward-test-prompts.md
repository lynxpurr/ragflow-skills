---
doc_type: reference
topic: release-forward-test-prompts
status: reference
created: 2026-06-27
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Release Archive Forward-Test Prompts


These templates let a host agent validate the public RAGFlow skill release archives
without repository context, network access, real credentials, or live RAGFlow mutation.
Use them after `python3 tools/export_release_archives.py` has produced
`release-artifacts/`.

## Requirements

- Validate installed artifacts from `release-artifacts/`, not the source tree.
- Inspect `release-manifest.json` and unpack `ragflow-doc-to-md.tar.gz`,
  `ragflow-kb-build.tar.gz`, and `ragflow-query.tar.gz`.
- Use `python3` and work only under the requested `/tmp/ragflow-forward-test-*`
  directory.
- Do not edit the repository, skill source folders, `dist/`, or `release-artifacts/`.
- Do not call network endpoints, use real API keys, create RAGFlow datasets, upload
  documents to RAGFlow, or run any live mutation.
- Report exact commands, pass/fail status, friction, and produced files.

## Hermes Template

```text
Use the public RAGFlow skill release artifacts in release-artifacts/ to validate
installed artifacts as Hermes. Work only under /tmp/ragflow-forward-test-hermes.
Do not edit the repository, dist/, or release-artifacts/. Do not use network
access, real credentials, RAGFlow endpoints, dataset creation, uploads, or any
live mutation.

Steps:
1. Inspect release-artifacts/release-manifest.json and confirm it lists
   ragflow-doc-to-md.tar.gz, ragflow-kb-build.tar.gz, and ragflow-query.tar.gz.
2. Recreate /tmp/ragflow-forward-test-hermes, copy or read the archives from
   release-artifacts/, and unpack all three archives under that work directory.
3. Create a tiny Markdown file under ./input-docs.
4. Run:
   python3 ragflow-doc-to-md/scripts/convert.py --input ./input-docs --output ./handoff --mode passthrough --json
5. Run:
   python3 ragflow-kb-build/scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name forward-test --profile ./ragflow-kb-build/templates/default-en-768.json --dry-run --json
6. Run:
   python3 ragflow-query/scripts/query.py --help
   python3 ragflow-query/scripts/query.py ask --help
7. Report exact commands, success or failure, friction, and produced files. Confirm
   doc_manifest.json was produced, the kb-build command was dry-run only, and
   ragflow-query exposed the host-assisted query interface without calling a
   network endpoint.
```

## OpenClaw Template

```text
Use the public RAGFlow skill release artifacts in release-artifacts/ to validate
installed artifacts as OpenClaw. Work only under /tmp/ragflow-forward-test-openclaw.
Do not edit the repository, dist/, or release-artifacts/. Do not use network
access, real credentials, RAGFlow endpoints, dataset creation, uploads, or any
live mutation.

Steps:
1. Inspect release-artifacts/release-manifest.json and confirm it lists
   ragflow-doc-to-md.tar.gz, ragflow-kb-build.tar.gz, and ragflow-query.tar.gz.
2. Recreate /tmp/ragflow-forward-test-openclaw, copy or read the archives from
   release-artifacts/, and unpack all three archives under that work directory.
3. Create a tiny Markdown file under ./input-docs.
4. Run:
   python3 ragflow-doc-to-md/scripts/convert.py --input ./input-docs --output ./handoff --mode passthrough --json
5. Run:
   python3 ragflow-kb-build/scripts/build.py --doc-manifest ./handoff/doc_manifest.json --kb-name forward-test --profile ./ragflow-kb-build/templates/default-en-768.json --dry-run --json
6. Run:
   python3 ragflow-query/scripts/query.py --help
   python3 ragflow-query/scripts/query.py ask --help
7. Report exact commands, success or failure, friction, and produced files. Confirm
   doc_manifest.json was produced, the kb-build command was dry-run only, and
   ragflow-query exposed the host-assisted query interface without calling a
   network endpoint.
```

## Expected Report

The host-agent result should include:

- the release manifest path and archive names checked;
- the work directory used;
- the commands run from the unpacked installed artifacts;
- whether `handoff/doc_manifest.json` exists;
- whether `ragflow-kb-build --dry-run` succeeded without writing a live
  `kb_manifest.json`;
- whether `ragflow-query` help exposed the host-assisted query interface;
- any missing instructions, confusing paths, or install friction.
