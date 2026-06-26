from __future__ import annotations

import json
import unittest

from ragflow_skill_runtime import configured_private_hosts_from_urls, sanitize_report_payload


class ReportSanitizerTests(unittest.TestCase):
    def test_sanitize_report_payload_redacts_shared_sensitive_shapes(self) -> None:
        payload = {
            "headers": "Authorization: Bearer bearer-token-value",
            "message": "api_key=assignment-secret and token=another-secret",
            "url": "https://private.example.local/v1?token=query-secret",
            "paths": [
                "/tmp/user-home/.ragflow/config.yaml",
                "/tmp/user-home/project/report.json",
            ],
            "nested": {"secret": "exact-secret-value"},
        }

        sanitized, report = sanitize_report_payload(
            payload,
            explicit_secrets=["exact-secret-value", "bearer-token-value"],
            private_hosts=["private.example.local"],
            home_paths=["/tmp/user-home"],
            config_paths=["/tmp/user-home/.ragflow/config.yaml"],
        )
        serialized = json.dumps({"payload": sanitized, "report": report}, sort_keys=True)

        self.assertEqual(report["schema"], "ragflow_report_redaction_report_v1")
        self.assertGreaterEqual(report["summary"]["redaction_count"], 7)
        self.assertGreaterEqual(report["rule_counts"]["explicit_secret"], 1)
        self.assertEqual(report["rule_counts"]["bearer_token"], 1)
        self.assertEqual(report["rule_counts"]["query_secret"], 1)
        self.assertGreaterEqual(report["rule_counts"]["assignment_secret"], 2)
        self.assertEqual(report["rule_counts"]["private_host"], 1)
        self.assertGreaterEqual(report["rule_counts"]["home_path"], 1)
        self.assertNotIn("bearer-token-value", serialized)
        self.assertNotIn("assignment-secret", serialized)
        self.assertNotIn("another-secret", serialized)
        self.assertNotIn("query-secret", serialized)
        self.assertNotIn("private.example.local", serialized)
        self.assertNotIn("exact-secret-value", serialized)
        self.assertIn("<redacted:secret>", serialized)
        self.assertIn("<redacted:private-host>", serialized)

    def test_configured_private_hosts_from_urls_excludes_public_hosts(self) -> None:
        hosts = configured_private_hosts_from_urls(
            [
                "https://localhost:9380/api/v1",
                "https://public.example.test/api/v1",
                "http://vpn-endpoint.local:8080/v1",
            ]
        )

        self.assertEqual(hosts, ["vpn-endpoint.local", "localhost"])


if __name__ == "__main__":
    unittest.main()
