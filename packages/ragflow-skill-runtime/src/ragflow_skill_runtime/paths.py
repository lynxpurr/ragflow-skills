"""Path helpers that avoid machine-specific defaults."""

from __future__ import annotations

from pathlib import Path


def expand_path(path: str | Path) -> Path:
    """Expand user markers and return an absolute path."""

    return Path(path).expanduser().resolve()


def project_config_candidates(start: Path) -> list[Path]:
    """Return portable project-local config candidates."""

    root = start.resolve()
    return [
        root / ".ragflow" / "config.json",
        root / ".ragflow" / "config.yaml",
        root / ".ragflow" / "config.yml",
    ]
