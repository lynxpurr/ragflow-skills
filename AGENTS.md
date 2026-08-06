# Repository Guidelines

## Project Structure & Module Organization

Shared Python code lives in `packages/ragflow-skill-runtime/src/ragflow_skill_runtime/`, with tests in the adjacent `tests/` directory. Public, self-contained skills are under `skills/ragflow-doc-to-md/`, `skills/ragflow-kb-build/`, and `skills/ragflow-query/`; each may contain `scripts/`, `templates/`, and `references/`. Repository-wide build and validation utilities live in `tools/`. Start documentation discovery at `docs/README.md`; governed specs, plans, references, evidence, and archive material live under `docs/`. Treat `dist/`, `release-artifacts/`, and `output/` as generated products, not source.

## Build, Test, and Development Commands

Run commands from the repository root with Python 3.10 or newer.

- `PYTHONPATH=packages/ragflow-skill-runtime/src:tools python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -v` runs the full unit suite.
- Add `-p 'test_config.py'` to the discovery command for a focused test file.
- `python3 tools/build_release.py --check` verifies self-contained skill artifacts without publishing them.
- `python3 tools/platform_smoke_matrix.py` exercises supported no-network platform paths.
- `python3 tools/release_hygiene_check.py` checks packaging, public/private boundaries, schemas, and generated-report safety.
- `python3 tools/document_lifecycle_check.py` checks documentation classification, metadata, ownership, links, archive rules, and public safety.
- `python3 tools/consumer_acceptance.py --artifacts-dir release-artifacts --work-dir /tmp/ragflow-consumer-acceptance --overwrite` validates archives from a clean consumer view.

## Coding Style & Naming Conventions

Use four-space indentation and follow existing PEP 8-style Python. Prefer type hints for public helpers and keep shared behavior in `ragflow_skill_runtime` rather than duplicating it across skill scripts. Use `snake_case` for functions and modules, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. No repository-wide formatter is configured, so match nearby code. Reports should be JSON-first, with Markdown as a sanitized summary.

## Testing Guidelines

Tests use `unittest` conventions: files named `test_*.py`, classes named `Test*`, and methods named `test_*`. Add focused tests beside the shared runtime suite for every behavior or CLI contract change. Prefer deterministic fixtures, fake clients, and no-network execution. Live MinerU or RAGFlow checks are opt-in and must never be required by the default suite.

## Commit & Pull Request Guidelines

Recent history follows Conventional Commit-style subjects such as `feat(benchmark): add ...`, `fix(validation): harden ...`, and `docs: update ...`. Keep subjects concise and imperative. Branch from `develop`; use `feature/<topic>` or `fix/<topic>` for substantial work. Pull requests should explain scope, public command or report changes, linked issues, and exact validation commands with outcomes. For output-format changes, include sanitized sample excerpts; screenshots are generally unnecessary for this CLI-focused repository.

## Security & Release Hygiene

Never commit API keys, private endpoints, local auth files, or machine-specific paths. Keep fixtures neutral, require explicit approval for live mutation, and edit source under `skills/` rather than generated release artifacts.
