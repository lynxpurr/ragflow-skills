from __future__ import annotations

import contextlib
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ragflow_skill_runtime import (
    RUNTIME_CACHE_REPORT_SCHEMA,
    RUNTIME_CIRCUIT_BREAKER_REPORT_SCHEMA,
    RUNTIME_METRICS_SCHEMA,
    RUNTIME_PARTIAL_FAILURE_REPORT_SCHEMA,
    RUNTIME_RATE_LIMIT_REPORT_SCHEMA,
    RUNTIME_RETRY_TRACE_SCHEMA,
    build_query_endpoint_report,
    classify_endpoint_host,
    render_query_endpoint_report_markdown,
)


class EndpointReportHandler(BaseHTTPRequestHandler):
    authorization = None
    request_count = 0
    statuses = [200]

    def do_HEAD(self) -> None:  # noqa: N802
        EndpointReportHandler.authorization = self.headers.get("Authorization")
        status_index = min(EndpointReportHandler.request_count, len(EndpointReportHandler.statuses) - 1)
        status = EndpointReportHandler.statuses[status_index]
        EndpointReportHandler.request_count += 1
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):  # noqa: A002
        return


@contextlib.contextmanager
def endpoint_report_server(statuses=None):
    EndpointReportHandler.authorization = None
    EndpointReportHandler.request_count = 0
    EndpointReportHandler.statuses = list(statuses or [200])
    server = ThreadingHTTPServer(("127.0.0.1", 0), EndpointReportHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


class QueryEndpointReportTests(unittest.TestCase):
    def test_classifies_local_lan_vpn_and_public_hosts(self) -> None:
        self.assertEqual(classify_endpoint_host("localhost"), "local")
        self.assertEqual(classify_endpoint_host("192.168.10.20"), "lan")
        self.assertEqual(classify_endpoint_host("100.64.10.20"), "vpn")
        self.assertEqual(classify_endpoint_host("api.example.test"), "public")

    def test_endpoint_report_redacts_hosts_queries_and_keys(self) -> None:
        report = build_query_endpoint_report(
            ragflow_base_url="https://192.168.10.20:9380/api/v1",
            ragflow_api_key="sk-test-secret",
            llm_base_url="http://api.example.test/v1",
            extra_endpoints=[
                {"label": "vpn", "url": "http://100.64.10.20:8080/v1?token=fake-secret"},
            ],
        )
        markdown = render_query_endpoint_report_markdown(report)
        serialized = json.dumps(report, sort_keys=True)

        self.assertTrue(report["ok"])
        self.assertEqual(report["schema"], "ragflow_query_endpoint_report_v1")
        self.assertEqual(report["endpoints"][0]["endpoint"]["network_zone"], "lan")
        self.assertEqual(report["endpoints"][1]["endpoint"]["network_zone"], "public")
        self.assertEqual(report["endpoints"][2]["endpoint"]["network_zone"], "vpn")
        self.assertIn("endpoint_public_http", {issue["code"] for issue in report["issues"]})
        self.assertIn("endpoint_url_query", {issue["code"] for issue in report["issues"]})
        self.assertEqual(report["runtime_metrics"]["schema"], RUNTIME_METRICS_SCHEMA)
        self.assertEqual(report["runtime_metrics"]["counters"]["endpoint_count"], 3)
        self.assertEqual(report["runtime_metrics"]["counters"]["status_not_checked"], 3)
        self.assertEqual(report["runtime_metrics"]["latency_ms"]["sample_count"], 0)
        self.assertEqual(report["runtime_cache"]["schema"], RUNTIME_CACHE_REPORT_SCHEMA)
        self.assertFalse(report["runtime_cache"]["enabled"])
        self.assertEqual(report["runtime_rate_limit"]["schema"], RUNTIME_RATE_LIMIT_REPORT_SCHEMA)
        self.assertFalse(report["runtime_rate_limit"]["enabled"])
        self.assertEqual(report["runtime_circuit_breaker"]["schema"], RUNTIME_CIRCUIT_BREAKER_REPORT_SCHEMA)
        self.assertFalse(report["runtime_circuit_breaker"]["enabled"])
        self.assertEqual(report["runtime_partial_failure"]["schema"], RUNTIME_PARTIAL_FAILURE_REPORT_SCHEMA)
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "skipped")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["skipped_count"], 3)
        self.assertEqual(report["summary"]["partial_skipped_count"], 3)
        self.assertIn("RAGFlow Query Endpoint Report", markdown)
        self.assertIn("latency_samples: `0`", markdown)
        self.assertIn("cache_enabled: `false`", markdown)
        self.assertIn("rate_limit_enabled: `false`", markdown)
        self.assertIn("circuit_breaker_enabled: `false`", markdown)
        self.assertIn("partial_failure_status: `skipped`", markdown)
        self.assertIn("partial_failure_skipped: `3`", markdown)
        self.assertIn("<lan-host>", serialized)
        self.assertIn("<vpn-host>", serialized)
        self.assertNotIn("192.168.10.20", serialized)
        self.assertNotIn("100.64.10.20", serialized)
        self.assertNotIn("api.example.test", serialized)
        self.assertNotIn("sk-test-secret", serialized)
        self.assertNotIn("fake-secret", serialized)

    def test_endpoint_report_network_check_uses_fake_endpoint_without_leaking_key(self) -> None:
        with endpoint_report_server() as base_url:
            report = build_query_endpoint_report(
                ragflow_base_url=f"{base_url}/api/v1",
                ragflow_api_key="query-test-key",
                network_check=True,
                timeout=2.0,
            )
        serialized = json.dumps(report, sort_keys=True)

        self.assertTrue(report["ok"])
        self.assertEqual(report["status_counts"]["reachable"], 1)
        self.assertEqual(report["summary"]["reachable_endpoint_count"], 1)
        self.assertEqual(report["runtime_metrics"]["counters"]["status_reachable"], 1)
        self.assertEqual(report["runtime_metrics"]["latency_ms"]["sample_count"], 1)
        self.assertIsNotNone(report["runtime_metrics"]["latency_ms"]["p95"])
        self.assertEqual(report["runtime_cache"]["summary"]["bypass_count"], 1)
        self.assertEqual(report["runtime_rate_limit"]["summary"]["acquire_count"], 0)
        self.assertEqual(report["retry_policy"]["retry_budget"], 1)
        self.assertEqual(report["summary"]["network_attempt_count"], 1)
        self.assertEqual(report["summary"]["retry_count"], 0)
        self.assertEqual(report["endpoints"][0]["retry_trace"]["schema"], RUNTIME_RETRY_TRACE_SCHEMA)
        self.assertEqual(report["endpoints"][0]["retry_trace"]["attempt_count"], 1)
        self.assertEqual(report["endpoints"][0]["retry_trace"]["retry_count"], 0)
        self.assertEqual(EndpointReportHandler.authorization, "Bearer query-test-key")
        self.assertNotIn("query-test-key", serialized)
        self.assertNotIn(base_url, serialized)

    def test_endpoint_report_records_opt_in_rate_limit_acquires(self) -> None:
        with endpoint_report_server() as base_url:
            report = build_query_endpoint_report(
                ragflow_base_url=f"{base_url}/api/v1",
                extra_endpoints=[
                    {"label": "llm", "kind": "llm", "url": f"{base_url}/llm/v1"},
                ],
                network_check=True,
                timeout=2.0,
                rate_limit_per_second=1000,
                rate_limit_burst=2,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(EndpointReportHandler.request_count, 2)
        self.assertEqual(report["runtime_rate_limit"]["schema"], RUNTIME_RATE_LIMIT_REPORT_SCHEMA)
        self.assertTrue(report["runtime_rate_limit"]["enabled"])
        self.assertEqual(report["runtime_rate_limit"]["summary"]["acquire_count"], 2)
        self.assertEqual(report["runtime_rate_limit"]["summary"]["delayed_count"], 0)
        self.assertEqual(report["summary"]["rate_limit_acquire_count"], 2)
        self.assertEqual(report["runtime_metrics"]["counters"]["rate_limit_acquire_count"], 2)

    def test_endpoint_report_short_circuits_after_repeated_failures(self) -> None:
        with endpoint_report_server(statuses=[500, 200]) as base_url:
            report = build_query_endpoint_report(
                ragflow_base_url=f"{base_url}/api/v1",
                extra_endpoints=[
                    {"label": "llm", "kind": "llm", "url": f"{base_url}/llm/v1"},
                ],
                network_check=True,
                timeout=2.0,
                circuit_breaker_failure_threshold=1,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(EndpointReportHandler.request_count, 1)
        self.assertEqual(report["status_counts"]["error"], 1)
        self.assertEqual(report["status_counts"]["circuit_open"], 1)
        self.assertEqual(report["summary"]["network_attempt_count"], 1)
        self.assertEqual(report["summary"]["circuit_breaker_failure_count"], 1)
        self.assertEqual(report["summary"]["circuit_breaker_open_count"], 1)
        self.assertEqual(report["summary"]["circuit_breaker_short_circuit_count"], 1)
        self.assertEqual(report["runtime_circuit_breaker"]["schema"], RUNTIME_CIRCUIT_BREAKER_REPORT_SCHEMA)
        self.assertTrue(report["runtime_circuit_breaker"]["enabled"])
        self.assertEqual(report["runtime_circuit_breaker"]["summary"]["state"], "open")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "failed")
        self.assertEqual(report["runtime_partial_failure"]["summary"]["failure_count"], 1)
        self.assertEqual(report["runtime_partial_failure"]["summary"]["skipped_count"], 1)
        self.assertEqual(report["runtime_metrics"]["counters"]["circuit_breaker_short_circuit_count"], 1)
        self.assertEqual(report["endpoints"][0]["status"], "error")
        self.assertEqual(report["endpoints"][1]["status"], "circuit_open")
        self.assertIn("endpoint_circuit_open", {issue["code"] for issue in report["issues"]})

    def test_endpoint_report_marks_mixed_reachability_as_partial_failure(self) -> None:
        with endpoint_report_server(statuses=[500, 200]) as base_url:
            report = build_query_endpoint_report(
                ragflow_base_url=f"{base_url}/api/v1",
                extra_endpoints=[
                    {"label": "llm", "kind": "llm", "url": f"{base_url}/llm/v1"},
                ],
                network_check=True,
                timeout=2.0,
            )

        markdown = render_query_endpoint_report_markdown(report)

        self.assertFalse(report["ok"])
        self.assertEqual(report["status_counts"]["error"], 1)
        self.assertEqual(report["status_counts"]["reachable"], 1)
        self.assertEqual(report["runtime_partial_failure"]["schema"], RUNTIME_PARTIAL_FAILURE_REPORT_SCHEMA)
        self.assertEqual(report["runtime_partial_failure"]["summary"]["status"], "partial")
        self.assertTrue(report["runtime_partial_failure"]["summary"]["partial"])
        self.assertEqual(report["runtime_partial_failure"]["summary"]["success_count"], 1)
        self.assertEqual(report["runtime_partial_failure"]["summary"]["failure_count"], 1)
        self.assertEqual(report["summary"]["partial_failure_status"], "partial")
        self.assertEqual(report["summary"]["partial_failure_count"], 1)
        self.assertEqual(report["runtime_metrics"]["counters"]["partial_failure_count"], 1)
        self.assertIn("partial_failure_status: `partial`", markdown)
        self.assertIn("partial_failure_failures: `1`", markdown)

    def test_endpoint_report_reuses_cached_reachability_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with endpoint_report_server() as base_url:
                first = build_query_endpoint_report(
                    ragflow_base_url=f"{base_url}/api/v1",
                    ragflow_api_key="query-test-key",
                    network_check=True,
                    timeout=2.0,
                    cache_dir=tmp,
                    cache_ttl_seconds=60,
                )
                second = build_query_endpoint_report(
                    ragflow_base_url=f"{base_url}/api/v1",
                    ragflow_api_key="query-test-key",
                    network_check=True,
                    timeout=2.0,
                    cache_dir=tmp,
                    cache_ttl_seconds=60,
                )

        self.assertTrue(first["ok"])
        self.assertTrue(second["ok"])
        self.assertEqual(EndpointReportHandler.request_count, 1)
        self.assertEqual(first["runtime_cache"]["summary"]["miss_count"], 1)
        self.assertEqual(first["runtime_cache"]["summary"]["write_count"], 1)
        self.assertEqual(first["summary"]["network_attempt_count"], 1)
        self.assertEqual(second["runtime_cache"]["summary"]["hit_count"], 1)
        self.assertEqual(second["summary"]["network_attempt_count"], 0)
        self.assertEqual(second["summary"]["cache_hit_count"], 1)
        self.assertEqual(second["runtime_metrics"]["counters"]["cache_hit_count"], 1)
        self.assertEqual(second["status_counts"]["reachable"], 1)
        self.assertTrue(second["endpoints"][0]["cached"])
        self.assertEqual(second["endpoints"][0]["cache"]["status"], "hit")
        self.assertNotIn("retry_trace", second["endpoints"][0])

    def test_endpoint_report_default_retry_budget_preserves_single_attempt(self) -> None:
        with endpoint_report_server(statuses=[500, 200]) as base_url:
            report = build_query_endpoint_report(
                ragflow_base_url=f"{base_url}/api/v1",
                network_check=True,
                timeout=2.0,
            )

        self.assertFalse(report["ok"])
        self.assertEqual(report["status_counts"]["error"], 1)
        self.assertEqual(report["summary"]["network_attempt_count"], 1)
        self.assertEqual(report["summary"]["retry_count"], 0)
        self.assertEqual(EndpointReportHandler.request_count, 1)
        trace = report["endpoints"][0]["retry_trace"]
        self.assertEqual(trace["schema"], RUNTIME_RETRY_TRACE_SCHEMA)
        self.assertEqual(trace["retry_budget"], 1)
        self.assertEqual(trace["attempt_count"], 1)
        self.assertEqual(trace["retry_count"], 0)
        self.assertEqual(trace["final_status"], "error")
        self.assertTrue(trace["budget_exhausted"])

    def test_endpoint_report_retries_retryable_status_with_explicit_budget(self) -> None:
        with endpoint_report_server(statuses=[500, 200]) as base_url:
            report = build_query_endpoint_report(
                ragflow_base_url=f"{base_url}/api/v1",
                network_check=True,
                timeout=2.0,
                retry_budget=2,
                retry_backoff_seconds=0.0,
            )

        self.assertTrue(report["ok"])
        self.assertEqual(report["status_counts"]["reachable"], 1)
        self.assertEqual(report["summary"]["network_attempt_count"], 2)
        self.assertEqual(report["summary"]["retry_count"], 1)
        self.assertEqual(EndpointReportHandler.request_count, 2)
        self.assertEqual(report["runtime_metrics"]["counters"]["network_attempt_count"], 2)
        self.assertEqual(report["runtime_metrics"]["counters"]["retry_count"], 1)
        trace = report["endpoints"][0]["retry_trace"]
        self.assertEqual(trace["retry_budget"], 2)
        self.assertEqual(trace["attempt_count"], 2)
        self.assertEqual(trace["retry_count"], 1)
        self.assertEqual(trace["final_status"], "reachable")
        self.assertFalse(trace["budget_exhausted"])
        self.assertEqual([attempt["status"] for attempt in trace["attempts"]], ["error", "reachable"])

    def test_endpoint_report_invalid_url_is_error(self) -> None:
        report = build_query_endpoint_report(ragflow_base_url="ftp://ragflow.example.test")

        self.assertFalse(report["ok"])
        self.assertEqual(report["status_counts"]["invalid_url"], 1)
        self.assertEqual(report["issues"][0]["code"], "endpoint_invalid_url")


if __name__ == "__main__":
    unittest.main()
