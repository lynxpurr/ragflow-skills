# First Release Candidate

Status: rc2 published
Date: 2026-06-23

## RC Goal

Use release candidates to validate that the public RAGFlow skills can be distributed as self-contained artifacts before promoting a stable `v0.1.0`.

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
python3 tools/consumer_acceptance.py --artifacts-dir release-artifacts --work-dir /tmp/ragflow-consumer-acceptance --overwrite
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

The scripted version of this consumer path is:

```bash
python3 tools/consumer_acceptance.py --artifacts-dir release-artifacts --work-dir /tmp/ragflow-consumer-acceptance --overwrite
```

To exercise the GitHub Release download path through `gh`, use:

```bash
python3 tools/consumer_acceptance.py --github-release v0.1.0-rc1 --repo lynxpurr/ragflow-skills --work-dir /tmp/ragflow-consumer-acceptance-github --overwrite
```

For the current RC2 release, use:

```bash
python3 tools/consumer_acceptance.py --github-release v0.1.0-rc2 --repo lynxpurr/ragflow-skills --work-dir /tmp/ragflow-consumer-acceptance-rc2-github --overwrite --download-timeout 90
```

For private repositories, run `gh auth login` first or set `GH_TOKEN`/`GITHUB_TOKEN`. The harness preserves GitHub CLI auth environment only for the release download step, disables interactive `gh` prompts, and accepts `--download-timeout` for slow networks. GitHub assets download to a separate temporary directory by default so `--overwrite` can safely clean the consumer work directory. The unpacked skill checks still run with a minimal consumer environment.

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

## RC1 GitHub Release

`v0.1.0-rc1` is published as a GitHub prerelease:

https://github.com/lynxpurr/ragflow-skills/releases/tag/v0.1.0-rc1

Attached assets:

- `ragflow-doc-to-md.tar.gz` - 18136 bytes - sha256 `cff6003ad2e34ab60a5e7c2bc401c956db3d1678b11abec12c7d6f32b74d0f27`
- `ragflow-kb-build.tar.gz` - 19561 bytes - sha256 `dac700556c6af22ed9e67d536cf52871220fba625e6e75da145ea158202ec3ba`
- `ragflow-query.tar.gz` - 18497 bytes - sha256 `877813a68de7137169918dedb825374380de544d3fb79b025e7ee8af873aa26d`
- `release-manifest.json` - 1129 bytes - asset sha256 `4eef930cdb12c567182c39e549223ea711e74a658f9fa30b63b66565976d7789`

The release manifest records `source_commit: 082ccec`.

## Post-RC1 Scope Update

After RC1, `develop` was refocused on Hermes, OpenClaw, Claude Code, opencode, and similar programming-agent CLI tools. Commercial SaaS agent sandboxes are no longer an active public-skill target.

Do not promote RC1 directly to stable. Cut `v0.1.0-rc2` from the updated `develop` branch, regenerate all three skill archives, and rerun consumer acceptance before stable `v0.1.0`.

## RC2 GitHub Release

`v0.1.0-rc2` is published as a GitHub prerelease:

https://github.com/lynxpurr/ragflow-skills/releases/tag/v0.1.0-rc2

RC2 source commit: `9fa41d7`.

Attached assets:

- `ragflow-doc-to-md.tar.gz` - 23046 bytes - sha256 `c19c38298e62a6d13b5b652a6cb96a10dbf5f71f2a127e2e1cfbd602ebed70a4`
- `ragflow-kb-build.tar.gz` - 23045 bytes - sha256 `19b507a406936d48e4b4a12b40b0525ef26d4cc25a3bd45b15447a03ec23d2a0`
- `ragflow-query.tar.gz` - 21982 bytes - sha256 `6403e3cc99f4fe8996a9dac13dbb80e7d564df4b408faac794d1fa1c04557dfd`
- `release-manifest.json` - 1129 bytes - asset sha256 `27d2d8118c8fb26dc75a30b40775f2affcdc6c8af630717acc633130e3addb0a`

RC2 includes the post-RC1 target refocus and configuration hardening:

- public scope is Hermes, OpenClaw, Claude Code, opencode, and similar controllable CLI-agent environments;
- each public skill ships `templates/ragflow-config.example.yaml`;
- `ragflow-doc-to-md` supports a named MinerU service backend through `MINERU_*` config;
- endpoint docs are remote-first for RAGFlow and MinerU;
- `timeout` and `verify_ssl` config values survive local credential overlays and CLI partial overrides;
- `verify_ssl` is wired through to the HTTP client.

## RC2 Validation Result

RC2 local artifact consumer acceptance passed on 2026-06-23:

```bash
python3 tools/consumer_acceptance.py --artifacts-dir release-artifacts --work-dir /tmp/ragflow-consumer-acceptance-rc2-local --overwrite
```

RC2 GitHub Release consumer acceptance also passed on 2026-06-23:

```bash
python3 tools/consumer_acceptance.py --github-release v0.1.0-rc2 --repo lynxpurr/ragflow-skills --work-dir /tmp/ragflow-consumer-acceptance-rc2-github --overwrite --download-timeout 90
```

Observed result:

- `ok: true`
- source type: `github-release`
- artifacts downloaded from `v0.1.0-rc2`
- vendored runtime was present
- `ragflow-doc-to-md` produced `doc_manifest.json`
- `ragflow-kb-build --dry-run` consumed the handoff manifest
- `ragflow-query` exposed direct and host-assisted query interfaces
- missing RAGFlow config failed before network work with the expected base URL error

Live RAGFlow/MinerU validation has not been run for RC2 because no disposable live endpoint credentials were provided in this environment.

## RC1 GitHub Consumer Acceptance

The GitHub Release artifact path passed on 2026-06-23:

```bash
python3 tools/consumer_acceptance.py --github-release v0.1.0-rc1 --repo lynxpurr/ragflow-skills --work-dir /tmp/ragflow-consumer-acceptance-github --overwrite --download-timeout 30
```

Observed result:

- `ok: true`
- source type: `github-release`
- artifacts downloaded from `v0.1.0-rc1`
- `ragflow-doc-to-md` produced `doc_manifest.json`
- `ragflow-kb-build --dry-run` consumed the handoff manifest
- `ragflow-query` exposed direct and host-assisted query interfaces
- missing RAGFlow config failed before network work with the expected base URL error

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
RAGFLOW_BASE_URL=https://ragflow.example.test \
RAGFLOW_API_KEY=... \
python3 tools/consumer_acceptance.py --github-release v0.1.0-rc1 --repo lynxpurr/ragflow-skills --work-dir /tmp/ragflow-consumer-acceptance-live --overwrite --download-timeout 30 --live-build
```

`--live-build` creates a disposable KB from the sample Markdown produced during consumer acceptance, waits for parsing, runs `ragflow-kb-build validate --level smoke`, then runs `ragflow-query` in direct and host-assisted modes. It does not delete the created KB automatically; run it only in a test workspace and clean up the KB after validation.

## Promotion

After RC validation:

1. Tag `develop` as a release candidate.
2. Attach or store the three `.tar.gz` files plus `release-manifest.json`.
3. Collect forward-test and live-test notes.
4. Fix RC findings on `develop`.
5. Promote to `main` only after a clean RC pass.

Items 1-4 are complete for RC2. The GitHub Release consumer acceptance path is also complete. Before stable `v0.1.0`, either run or explicitly waive the stronger live RAGFlow endpoint check.
