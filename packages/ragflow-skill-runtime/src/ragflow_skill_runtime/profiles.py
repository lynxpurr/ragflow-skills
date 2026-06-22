"""Chunk profile loading and linting."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .config import read_config_file


class ProfileError(RuntimeError):
    """Raised when a build profile is invalid."""


@dataclass(frozen=True)
class ChunkProfile:
    profile_id: str
    chunk_method: str = "naive"
    chunk_size: int = 512
    chunk_overlap: int = 64
    embedding_model: str | None = None
    parser_config: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ChunkProfile":
        profile_id = data.get("profile_id") or data.get("id")
        if not isinstance(profile_id, str) or not profile_id.strip():
            raise ProfileError("profile_id is required")
        chunk_size = int(data.get("chunk_size", data.get("chunk_token_num", 512)))
        chunk_overlap = int(data.get("chunk_overlap", 64))
        if chunk_size <= 0:
            raise ProfileError("chunk_size must be positive")
        if chunk_overlap < 0:
            raise ProfileError("chunk_overlap must be non-negative")
        if chunk_overlap >= chunk_size:
            raise ProfileError("chunk_overlap must be smaller than chunk_size")
        parser_config = data.get("parser_config", {})
        if parser_config is None:
            parser_config = {}
        if not isinstance(parser_config, dict):
            raise ProfileError("parser_config must be an object")

        parser_config = dict(parser_config)
        parser_config.setdefault("chunk_token_num", chunk_size)
        parser_config.setdefault("auto_keywords", 0)
        parser_config.setdefault("auto_questions", 0)

        return cls(
            profile_id=profile_id.strip(),
            chunk_method=str(data.get("chunk_method", "naive")),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            embedding_model=data.get("embedding_model"),
            parser_config=parser_config,
        )

    def to_dataset_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chunk_method": self.chunk_method,
            "parser_config": self.parser_config,
        }
        if self.embedding_model:
            payload["embedding_model"] = self.embedding_model
        return payload

    def to_manifest_dict(self) -> dict[str, Any]:
        return {
            "id": self.profile_id,
            "chunk_method": self.chunk_method,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "embedding_model": self.embedding_model,
            "parser_config": self.parser_config,
        }


def load_profile(path: str | Path) -> ChunkProfile:
    """Load a JSON or simple YAML chunk profile."""

    profile_path = Path(path)
    if profile_path.suffix.lower() == ".json":
        try:
            data = json.loads(profile_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise ProfileError(f"profile not found: {profile_path}") from exc
        except json.JSONDecodeError as exc:
            raise ProfileError(f"profile is not valid JSON: {profile_path}") from exc
    else:
        data = read_config_file(profile_path)
    if not isinstance(data, dict):
        raise ProfileError("profile must be an object")
    return ChunkProfile.from_dict(data)
