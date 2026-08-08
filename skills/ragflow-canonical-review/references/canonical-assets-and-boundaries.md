# Canonical Assets and Boundaries

## Positive selection

Build ingestion candidates from exact approved Markdown paths. Never recursively ingest a
repository root or canonical subtree and rely on later filtering.

Treat control-file placement as instruction scope, not content identity. Keep required
control files in place while excluding them and every non-allowlisted Markdown path from
manifests.

The asset audit accepts newline-delimited paths, JSON or YAML lists, mappings containing
`active_paths`, `paths`, or `allowlist`, and document records containing `path` plus an
optional `status`.

## Asset decisions

Treat an unreferenced asset as an audit signal. Separate document integrity, meaning no
active Markdown reference remains, from knowledge preservation, meaning every stable fact
or visual function is represented elsewhere. Require both before removal.

Classify directories as empty ordinary directories, duplicate-looking directories requiring
reference/hash/ownership comparison, non-canonical evidence with an approved disposition,
historical packages or baselines that remain unchanged, or links and reparse points that
must not be treated as ordinary directories.

## Movement and deletion

Before moving or deleting an asset:

1. Freeze exact references and case-insensitive basename collisions.
2. Inspect source-fact and visual coverage.
3. Confirm document ownership and historical role.
4. Update a canonical rename and its Markdown references atomically.
5. Verify old references are absent and new references resolve.
6. Rerun the audit and record the resulting disposition.

Do not use ignore status, age, directory naming, duplicate-looking content, small dimensions,
or an unreferenced state as deletion authority. Remove an empty directory only after
confirming it has no children, active reference, registered role, or link status.
