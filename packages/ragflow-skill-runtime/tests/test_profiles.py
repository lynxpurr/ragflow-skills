from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ragflow_skill_runtime.profiles import ChunkProfile, ProfileError, load_profile


class ProfileTests(unittest.TestCase):
    def test_load_profile_from_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(
                json.dumps(
                    {
                        "profile_id": "default-en-768",
                        "chunk_method": "naive",
                        "chunk_size": 768,
                        "chunk_overlap": 96,
                        "embedding_model": "bge-m3",
                        "parser_config": {"auto_keywords": 1},
                    }
                ),
                encoding="utf-8",
            )
            profile = load_profile(path)

        self.assertEqual(profile.profile_id, "default-en-768")
        self.assertEqual(profile.parser_config["chunk_token_num"], 768)
        self.assertEqual(profile.parser_config["auto_keywords"], 1)
        self.assertEqual(profile.parser_config["auto_questions"], 0)

    def test_profile_rejects_overlap_larger_than_chunk(self) -> None:
        with self.assertRaises(ProfileError):
            ChunkProfile.from_dict(
                {
                    "profile_id": "bad",
                    "chunk_size": 128,
                    "chunk_overlap": 128,
                }
            )

    def test_dataset_payload_filters_internal_parser_config_keys(self) -> None:
        profile = ChunkProfile.from_dict(
            {
                "profile_id": "default-zh-512",
                "chunk_size": 512,
                "parser_config": {
                    "chunk_token_num": 512,
                    "auto_keywords": 0,
                    "__language__": "Chinese",
                },
            }
        )

        payload = profile.to_dataset_payload()
        manifest = profile.to_manifest_dict()

        self.assertNotIn("__language__", payload["parser_config"])
        self.assertEqual(payload["parser_config"]["chunk_token_num"], 512)
        self.assertEqual(manifest["parser_config"]["__language__"], "Chinese")


if __name__ == "__main__":
    unittest.main()
