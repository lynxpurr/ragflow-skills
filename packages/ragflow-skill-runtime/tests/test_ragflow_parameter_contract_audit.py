from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TOOLS_DIR = ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from ragflow_parameter_contract_audit import (  # noqa: E402
    REQUIRED_SOURCE_FILES,
    SCHEMA,
    audit_parameter_contract,
    render_markdown,
)


VALIDATION_SOURCE = '''
class Base(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

class AutoMetadataField(Base):
    key: str

class AutoMetadataConfig(Base):
    metadata: Annotated[list[AutoMetadataField], Field(default_factory=list)]
    built_in_metadata: Annotated[list[AutoMetadataField], Field(default_factory=list)]

class ParserConfig(Base):
    chunk_token_num: Annotated[int, Field(default=512, ge=1, le=2048)]
{overlap_field}

class CreateDatasetReq(Base):
    parser_config: Annotated[ParserConfig | None, Field(default=None)]
    auto_metadata_config: Annotated[AutoMetadataConfig | None, Field(default=None)]

class UpdateDatasetReq(CreateDatasetReq):
    pass
'''


SOURCE_FIXTURES = {
    "api/apps/restful_apis/dataset_api.py": '''
@manager.route("/datasets", methods=["POST"])
async def create():
    return await validate_and_parse_json_request(request, CreateDatasetReq)

@manager.route("/datasets/<dataset_id>", methods=["PUT"])
async def update(dataset_id):
    return await validate_and_parse_json_request(request, UpdateDatasetReq)

@manager.route("/datasets/<dataset_id>/metadata/config", methods=["GET"])
def get_auto_metadata(dataset_id):
    return dataset_api_service.get_auto_metadata(dataset_id)

@manager.route("/datasets/<dataset_id>/metadata/config", methods=["PUT"])
async def update_auto_metadata(dataset_id):
    cfg, err = await validate_and_parse_json_request(request, AutoMetadataConfig)
    return await dataset_api_service.update_auto_metadata(dataset_id, cfg)
''',
    "api/apps/services/dataset_api_service.py": '''
async def create_dataset(req):
    auto_meta = req.pop("auto_metadata_config", {})
    fields = auto_meta.get("fields", [])
    parser_cfg = req.get("parser_config") or {}
    parser_cfg["metadata"] = fields
    parser_cfg["enable_metadata"] = auto_meta.get("enabled", True)
    return req

async def update_dataset(req):
    auto_meta = req.pop("auto_metadata_config", {})
    fields = auto_meta.get("fields", [])
    parser_cfg = req.get("parser_config") or {}
    parser_cfg["metadata"] = fields
    parser_cfg["enable_metadata"] = auto_meta.get("enabled", True)
    return req

def get_auto_metadata(kb):
    return {"metadata": kb.parser_config.get("metadata"), "built_in_metadata": kb.parser_config.get("built_in_metadata")}

async def update_auto_metadata(kb, cfg):
    kb.parser_config["metadata"] = cfg.get("metadata")
    kb.parser_config["built_in_metadata"] = cfg.get("built_in_metadata")
    return cfg
''',
    "rag/app/naive.py": '''
from common.float_utils import normalize_overlapped_percent

def chunk(parser_config):
    overlapped_percent = normalize_overlapped_percent(parser_config.get("overlapped_percent", 0))
    return naive_merge([], overlapped_percent=overlapped_percent)
''',
    "common/float_utils.py": '''
def normalize_overlapped_percent(overlapped_percent):
    value = float(overlapped_percent)
    if 0 < value < 1:
        value *= 100
    return max(0, min(int(value), 90))
''',
    "web/src/pages/dataset/dataset-setting/form-schema.ts": '''
export const formSchema = z.object({
  parser_config: z.object({
    overlapped_percent: z.number().optional(),
    metadata: z.any().optional(),
    built_in_metadata: z.array(z.object({ key: z.string().optional() })).optional(),
    enable_metadata: z.boolean().optional(),
  }),
});
''',
    "web/src/pages/dataset/dataset-setting/configuration/common-item.tsx": '''
export function OverlappedPercent() {
  return <SliderInputFormField name="parser_config.overlapped_percent" max={0.3} step={0.01} />;
}

export function AutoMetadata() {
  const metadata = form.getValues("parser_config.metadata");
  const builtInMetadata = form.getValues("parser_config.built_in_metadata");
  form.setValue("parser_config.enable_metadata", true);
  return [metadata, builtInMetadata];
}
''',
    "rag/svr/task_executor.py": '''
async def run(task):
    if task["parser_config"].get("enable_metadata", False):
        chat_mdl = LLMBundle(task["tenant_id"], task["llm_id"])
        tasks = []
        for doc in task["docs"]:
            tasks.append(asyncio.create_task(gen_metadata_task(chat_mdl, doc)))
        await asyncio.gather(*tasks)
''',
}


def _write_source_root(
    root: Path,
    *,
    overlap_in_model: bool = False,
    overlap_runtime: bool = True,
    legacy_auto_mapping: bool = True,
    metadata_runtime_coherent: bool = True,
) -> None:
    overlap_field = (
        "    overlapped_percent: Annotated[float, Field(default=0, ge=0, le=90)]"
        if overlap_in_model
        else ""
    )
    fixtures = {
        "api/utils/validation_utils.py": VALIDATION_SOURCE.format(overlap_field=overlap_field),
        **SOURCE_FIXTURES,
    }
    if not overlap_runtime:
        fixtures["rag/app/naive.py"] = "def chunk(parser_config):\n    return naive_merge([])\n"
    if not legacy_auto_mapping:
        service_source = fixtures["api/apps/services/dataset_api_service.py"]
        fixtures["api/apps/services/dataset_api_service.py"] = service_source.replace(
            'auto_meta.get("fields", [])',
            'auto_meta.get("metadata", [])',
        ).replace(
            'auto_meta.get("enabled", True)',
            'bool(auto_meta.get("metadata"))',
        )
    if not metadata_runtime_coherent:
        fixtures["rag/svr/task_executor.py"] = '''
def unrelated_model_path(task):
    chat_mdl = LLMBundle(task["tenant_id"], task["llm_id"])
    return asyncio.create_task(run_unrelated(chat_mdl))

async def run(task):
    if task["parser_config"].get("enable_metadata", False):
        return task
'''
    for relative_path in REQUIRED_SOURCE_FILES:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(fixtures[relative_path].strip() + "\n", encoding="utf-8")


def _audit(deployment: Path, upstream: Path, **overrides):
    kwargs = {
        "deployment_root": deployment,
        "upstream_root": upstream,
        "deployment_version": "v0.25.5",
        "deployment_image": "infiniflow/ragflow:v0.25.5",
        "deployment_image_digest": "sha256:" + "1" * 64,
        "upstream_tag": "v0.25.5",
        "upstream_commit": "9" * 40,
    }
    kwargs.update(overrides)
    return audit_parameter_contract(**kwargs)


class RagflowParameterContractAuditTests(unittest.TestCase):
    def test_classifies_v0255_overlap_and_automatic_metadata_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deployment = root / "deployment"
            upstream = root / "upstream"
            _write_source_root(deployment)
            _write_source_root(upstream)

            report, redaction = _audit(deployment, upstream)

        self.assertEqual(report["schema"], SCHEMA)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["source_integrity"]["all_required_files_identical"])
        by_id = {item["id"]: item for item in report["candidates"]}
        self.assertEqual(by_id["overlap_percent"]["classification"], "runtime_only_not_api_writable")
        self.assertEqual(by_id["automatic_metadata"]["classification"], "contract_conflict")
        side_effects = by_id["automatic_metadata"]["side_effects"]
        self.assertTrue(side_effects["model_provider_dependency"])
        self.assertEqual(side_effects["cost_scope"], "potentially_billable")
        self.assertEqual(side_effects["execution_scope"], "asynchronous_per_chunk_during_parse")
        self.assertEqual(side_effects["activation_scope"], "parse_or_reparse_required")
        self.assertEqual(side_effects["metadata_governance"], "generated_chunk_metadata")
        self.assertTrue(side_effects["unresolved_gate"])
        self.assertEqual(report["summary"]["stage8c_eligible_candidate_count"], 0)
        self.assertEqual(report["safety"]["ragflow_calls"], 0)
        self.assertFalse(report["safety"]["writes_live_ragflow"])
        self.assertFalse(report["safety"]["script_owned_llm_calls"])
        self.assertEqual(redaction["schema"], "ragflow_report_redaction_report_v1")
        auto_request = by_id["automatic_metadata"]["evidence_layers"]["request_model"][0]
        self.assertIn("AutoMetadataConfig", auto_request["field_contract"]["annotation"])
        self.assertIn("default=None", auto_request["field_contract"]["default"])
        metadata_contract = auto_request["nested_field_contracts"]["metadata"]
        self.assertIn("AutoMetadataField", metadata_contract["annotation"])
        self.assertIn("default_factory=list", metadata_contract["default"])

        markdown = render_markdown(report)
        overlap_row = markdown.index("| `overlap_percent` |")
        metadata_row = markdown.index("| `automatic_metadata` |")
        overlap_details = markdown.index("### Overlapped percent")
        self.assertLess(overlap_row, metadata_row)
        self.assertLess(metadata_row, overlap_details)

    def test_source_drift_fails_audit_and_blocks_stage8c(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deployment = root / "deployment"
            upstream = root / "upstream"
            _write_source_root(deployment, overlap_in_model=True)
            _write_source_root(upstream, overlap_in_model=True)
            path = upstream / "common/float_utils.py"
            path.write_text(path.read_text(encoding="utf-8") + "# upstream drift\n", encoding="utf-8")

            report, _ = _audit(deployment, upstream)

        self.assertFalse(report["ok"])
        self.assertFalse(report["source_integrity"]["all_required_files_identical"])
        self.assertIn("source_drift", {item["check"] for item in report["issues"]})
        self.assertEqual(report["summary"]["stage8c_eligible_candidate_count"], 0)

    def test_missing_required_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deployment = root / "deployment"
            upstream = root / "upstream"
            _write_source_root(deployment)
            _write_source_root(upstream)
            (upstream / "rag/svr/task_executor.py").unlink()

            report, _ = _audit(deployment, upstream)

        self.assertFalse(report["ok"])
        self.assertIn("required_source_missing", {item["check"] for item in report["issues"]})
        self.assertTrue(all(item["classification"] == "audit_incomplete" for item in report["candidates"]))

    def test_malformed_contract_identities_are_reported(self) -> None:
        invalid_values = (
            ("deployment_version", "version with spaces"),
            ("deployment_image", "private host/image"),
            ("deployment_image_digest", "sha256:short"),
            ("upstream_tag", "tag with spaces"),
            ("upstream_commit", "not-a-commit"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deployment = root / "deployment"
            upstream = root / "upstream"
            _write_source_root(deployment, overlap_in_model=True)
            _write_source_root(upstream, overlap_in_model=True)
            for key, value in invalid_values:
                with self.subTest(key=key):
                    report, _ = _audit(deployment, upstream, **{key: value})
                    self.assertFalse(report["ok"])
                    self.assertIn("invalid_contract_identity", {item["check"] for item in report["issues"]})
                    self.assertEqual(report["summary"]["stage8c_eligible_candidate_count"], 0)

    def test_metadata_runtime_evidence_must_share_the_enable_metadata_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deployment = root / "deployment"
            upstream = root / "upstream"
            _write_source_root(deployment, metadata_runtime_coherent=False)
            _write_source_root(upstream, metadata_runtime_coherent=False)

            report, _ = _audit(deployment, upstream)

        candidate = next(item for item in report["candidates"] if item["id"] == "automatic_metadata")
        self.assertFalse(report["ok"])
        self.assertEqual(candidate["classification"], "audit_incomplete")
        runtime_rules = candidate["evidence_layers"]["runtime_consumer"]
        self.assertFalse(next(item for item in runtime_rules if item["rule"] == "metadata_runtime_model_dependency")["matched"])
        self.assertFalse(next(item for item in runtime_rules if item["rule"] == "metadata_runtime_async_per_chunk")["matched"])

    def test_metadata_parser_config_conflict_remains_without_legacy_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deployment = root / "deployment"
            upstream = root / "upstream"
            _write_source_root(deployment, legacy_auto_mapping=False)
            _write_source_root(upstream, legacy_auto_mapping=False)

            report, _ = _audit(deployment, upstream)

        candidate = next(item for item in report["candidates"] if item["id"] == "automatic_metadata")
        parser_contract = candidate["evidence_layers"]["request_model"][1]
        legacy_mapping = candidate["evidence_layers"]["service_mapping"][0]
        self.assertFalse(legacy_mapping["matched"])
        self.assertFalse(parser_contract["matched"])
        self.assertEqual(
            parser_contract["missing_fields"],
            ["built_in_metadata", "enable_metadata", "metadata"],
        )
        self.assertEqual(candidate["classification"], "contract_conflict")
        self.assertFalse(candidate["stage8c_eligible"])

    def test_source_root_location_does_not_change_semantic_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_deployment = root / "first" / "deployment"
            first_upstream = root / "first" / "upstream"
            second_deployment = root / "different-location" / "deployment"
            second_upstream = root / "different-location" / "upstream"
            for path in (first_deployment, first_upstream, second_deployment, second_upstream):
                _write_source_root(path)

            first, _ = _audit(first_deployment, first_upstream)
            second, _ = _audit(second_deployment, second_upstream)

        self.assertEqual(first, second)

    def test_overlap_requires_request_frontend_and_runtime_agreement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            complete_deployment = root / "complete-deployment"
            complete_upstream = root / "complete-upstream"
            _write_source_root(complete_deployment, overlap_in_model=True)
            _write_source_root(complete_upstream, overlap_in_model=True)
            complete, _ = _audit(complete_deployment, complete_upstream)

            incomplete_deployment = root / "incomplete-deployment"
            incomplete_upstream = root / "incomplete-upstream"
            _write_source_root(incomplete_deployment, overlap_in_model=True, overlap_runtime=False)
            _write_source_root(incomplete_upstream, overlap_in_model=True, overlap_runtime=False)
            incomplete, _ = _audit(incomplete_deployment, incomplete_upstream)

        complete_overlap = next(item for item in complete["candidates"] if item["id"] == "overlap_percent")
        incomplete_overlap = next(item for item in incomplete["candidates"] if item["id"] == "overlap_percent")
        self.assertEqual(complete_overlap["classification"], "writable_contract_confirmed")
        self.assertTrue(complete_overlap["stage8c_eligible"])
        self.assertEqual(incomplete_overlap["classification"], "audit_incomplete")
        self.assertFalse(incomplete_overlap["stage8c_eligible"])

    def test_cli_writes_path_safe_json_markdown_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            deployment = root / "private-deployment-source"
            upstream = root / "private-upstream-source"
            output = root / "output"
            output.mkdir()
            _write_source_root(deployment)
            _write_source_root(upstream)
            report_json = output / "contract_audit.json"
            report_md = output / "contract_audit.md"
            redaction_json = output / "contract_audit.redaction.json"

            result = subprocess.run(
                [
                    sys.executable,
                    str(TOOLS_DIR / "ragflow_parameter_contract_audit.py"),
                    "--deployment-root",
                    str(deployment),
                    "--upstream-root",
                    str(upstream),
                    "--deployment-version",
                    "v0.25.5",
                    "--deployment-image",
                    "infiniflow/ragflow:v0.25.5",
                    "--deployment-image-digest",
                    "sha256:" + "1" * 64,
                    "--upstream-tag",
                    "v0.25.5",
                    "--upstream-commit",
                    "9" * 40,
                    "--report-json",
                    str(report_json),
                    "--report-md",
                    str(report_md),
                    "--redaction-report",
                    str(redaction_json),
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            combined = result.stdout + report_json.read_text(encoding="utf-8") + report_md.read_text(encoding="utf-8")
            redaction = json.loads(redaction_json.read_text(encoding="utf-8"))

        self.assertIn("runtime_only_not_api_writable", combined)
        self.assertIn("contract_conflict", combined)
        self.assertIn("Stage 8C eligible: `false`", combined)
        self.assertNotIn(str(deployment), combined)
        self.assertNotIn(str(upstream), combined)
        self.assertEqual(redaction["schema"], "ragflow_report_redaction_report_v1")


if __name__ == "__main__":
    unittest.main()
