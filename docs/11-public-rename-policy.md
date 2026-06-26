# Public Rename Policy

Status: active

This policy applies before changing public CLI commands, schema names, skill names,
artifact names, profile IDs, or report fields that downstream agents may call directly.
Rename work must be planned as a compatibility change, not as a silent replacement.

## CLI Aliases

Public CLI command renames must keep a deprecated alias unless the release notes explain
why an alias is impossible or unsafe. Alias handlers must call the canonical command path,
emit the same output schema, and have tests that prove both names work.

## Schema Migration

Public schema renames must keep the old schema readable for a documented migration window.
Migration code must record the old schema name, canonical schema name, compatibility status,
and any lossy fields. Schema identity checks must be updated before the rename ships.

## Documentation Updates

Rename pull requests must update public `SKILL.md` files, shared references, onboarding
prompts, release docs, and examples in the same change. Historical design notes may retain
old names only when the context is explicitly legacy or migration-related.

## Downstream Gates

Release hygiene must include compatibility facade checks for declared aliases and naming
drift checks for old or experimental public names. Consumer acceptance, platform smoke, or
focused unit tests must prove aliases and canonical names route to the same behavior.

## Release Notes

Release notes must name the old and new public identifiers, the deprecation window, the
required user action, and the compatibility guarantees. Breaking renames require explicit
approval and a rollback plan before release.

## Rollback Plan

Every public rename must include rollback instructions. The rollback plan must say how to
restore old CLI names, schema readers, docs, downstream gates, and release artifacts if
consumers report compatibility failures.
