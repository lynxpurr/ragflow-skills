# Branching Policy

Status: active
Date: 2026-06-22

## Branch Roles

| Branch | Purpose |
|---|---|
| `develop` | Default branch. Daily development lands here first. |
| `main` | Stable release branch. Only receives reviewed release merges from `develop`. |
| `feature/<topic>` | Short-lived feature work branched from `develop`. |
| `fix/<topic>` | Short-lived bug fixes branched from `develop`, or from `main` only for urgent release hotfixes. |
| `release/<version>` | Optional stabilization branch cut from `develop` before merging to `main`. |

## Default Workflow

1. Start from `develop`.
2. Create a short-lived topic branch when work is larger than a small docs or build-script edit.
3. Merge topic branches back into `develop`.
4. Run the local validation suite before release:

```bash
PYTHONPATH=packages/ragflow-skill-runtime/src:tools \
  python3 -m unittest discover -s packages/ragflow-skill-runtime/tests -v

python3 tools/build_release.py --check
python3 tools/vendor_import_smoke.py
python3 tools/platform_smoke_matrix.py
python3 tools/release_hygiene_check.py
```

5. Promote to `main` only when `develop` is ready for a stable release snapshot.

## Release Promotion

Use this flow for stable releases:

```bash
git switch develop
git pull --ff-only

# run validation

git switch main
git pull --ff-only
git merge --ff-only develop
git push origin main
```

If `main` cannot fast-forward, stop and inspect the divergence instead of forcing history.

## Rules

- Do not commit generated `dist/` artifacts to source branches.
- Do not commit secrets, local auth files, or machine-specific config.
- Keep `main` deployable and boring.
- Keep active development on `develop`.
- Prefer small commits with clear messages.
- Use force-push only on unpublished topic branches.

## Current Default

`develop` is the intended GitHub default branch for this repository.
