---
doc_type: reference
topic: branching-policy
status: reference
created: 2026-06-22
updated: 2026-08-03
canonical: true
implementation_authority: false
owner_spec: docs/specs/2026-08-02-document-lifecycle-and-spec-archive-design.md
supersedes: []
superseded_by: null
related: []
---

# Branching Policy


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
4. Run the current release validation sequence from
   `docs/reference/release-hardening.md`; do not maintain a second command list here.

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
- Do not edit generated `dist/` files by hand; update `skills/` source files and rebuild
  release artifacts instead.
- Do not commit secrets, local auth files, or machine-specific config.
- Keep `main` deployable and boring.
- Keep active development on `develop`.
- Prefer small commits with clear messages.
- Use force-push only on unpublished topic branches.

## Current Default

`develop` is the intended GitHub default branch for this repository.
