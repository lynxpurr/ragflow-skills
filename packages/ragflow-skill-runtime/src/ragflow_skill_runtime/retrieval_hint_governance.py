"""Deterministic candidate-to-reviewed retrieval hint governance."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


CANDIDATE_RETRIEVAL_HINTS_SCHEMA = "ragflow_retrieval_hints_v1"
REVIEW_DECISIONS_SCHEMA = "ragflow_retrieval_hint_review_decisions_v1"
REVIEWED_RETRIEVAL_HINTS_SCHEMA = "ragflow_reviewed_retrieval_hints_v1"
CANDIDATE_GROUPS = (
    "keyword_candidates",
    "question_candidates",
    "table_term_alias_candidates",
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PRODUCT_CATALOG_TYPES = {"zh_product_catalog", "en_product_catalog", "product_catalog"}
_OPERATIONAL_TYPES = {"zh_manual", "en_manual", "manual", "operational_instruction"}


class RetrievalHintGovernanceError(RuntimeError):
    """Raised when retrieval hint review inputs violate the public contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def candidate_artifact_sha256(payload: Mapping[str, Any]) -> str:
    """Return a content identity for the exact candidate artifact."""

    return _sha256(dict(payload))


def _candidate_value(candidate: Mapping[str, Any], group: str) -> str:
    if group == "keyword_candidates":
        return str(candidate.get("term") or candidate.get("value") or "").strip()
    if group == "question_candidates":
        return str(candidate.get("question") or candidate.get("value") or "").strip()
    values = candidate.get("candidate_aliases")
    aliases = [str(item).strip() for item in values] if isinstance(values, list) else []
    return str(candidate.get("normalized_label") or candidate.get("source_label") or "").strip() + "|" + "|".join(aliases)


def _candidate_document(candidate: Mapping[str, Any]) -> str | None:
    for key in ("source_document", "document"):
        value = candidate.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def decorate_candidate_hints(
    payload: Mapping[str, Any],
    *,
    document_hashes: Mapping[str, str] | None = None,
    document_types: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Add deterministic IDs and source constraints to candidate hint groups."""

    if payload.get("schema") != CANDIDATE_RETRIEVAL_HINTS_SCHEMA:
        raise RetrievalHintGovernanceError(
            f"candidate hint schema must be {CANDIDATE_RETRIEVAL_HINTS_SCHEMA}"
        )
    hashes = dict(document_hashes or {})
    types = dict(document_types or {})
    aggregate_hash = _sha256({key: hashes[key] for key in sorted(hashes)})
    decorated = dict(payload)
    seen: set[str] = set()
    for group in CANDIDATE_GROUPS:
        values = payload.get(group, [])
        if not isinstance(values, list):
            raise RetrievalHintGovernanceError(f"candidate hint {group} must be a list")
        output: list[dict[str, Any]] = []
        kind = group.removesuffix("_candidates").replace("table_term_alias", "table_alias")
        for raw in values:
            if not isinstance(raw, Mapping):
                raise RetrievalHintGovernanceError(f"candidate hint {group} entries must be objects")
            candidate = dict(raw)
            document = _candidate_document(candidate)
            document_hash = hashes.get(document or "", aggregate_hash)
            document_type = str(
                candidate.get("source_document_type")
                or candidate.get("document_type")
                or types.get(document or "")
                or "unknown"
            )
            source_constraint = str(
                candidate.get("source_constraint")
                or (f"document:{document}" if document else f"artifact:{aggregate_hash}")
            )
            value = _candidate_value(candidate, group)
            if not value:
                raise RetrievalHintGovernanceError(f"candidate hint {group} entry has no value")
            identity = {
                "group": group,
                "kind": kind,
                "value": value,
                "source_document": document,
                "source_document_type": document_type,
                "source_constraint": source_constraint,
                "content_sha256": document_hash,
                "candidate_details": {
                    key: raw[key]
                    for key in sorted(raw)
                    if key not in {"candidate_id", "content_sha256", "source_constraint"}
                },
            }
            candidate_id = str(candidate.get("candidate_id") or f"hint-{kind}-{_sha256(identity)[:20]}")
            if candidate_id in seen:
                raise RetrievalHintGovernanceError(f"duplicate candidate id: {candidate_id}")
            seen.add(candidate_id)
            candidate.update(identity)
            candidate["candidate_id"] = candidate_id
            output.append(candidate)
        decorated[group] = output
    decorated["candidate_lineage"] = {
        "hash_algorithm": "sha256",
        "artifact_content_sha256": aggregate_hash,
        "candidate_count": sum(len(decorated[group]) for group in CANDIDATE_GROUPS),
        "activation_requires_reviewed_artifact": True,
    }
    return decorated


def _all_candidates(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    if payload.get("schema") != CANDIDATE_RETRIEVAL_HINTS_SCHEMA:
        raise RetrievalHintGovernanceError(
            f"candidate hint schema must be {CANDIDATE_RETRIEVAL_HINTS_SCHEMA}"
        )
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in CANDIDATE_GROUPS:
        values = payload.get(group, [])
        if not isinstance(values, list):
            raise RetrievalHintGovernanceError(f"candidate hint {group} must be a list")
        for raw in values:
            if not isinstance(raw, Mapping):
                raise RetrievalHintGovernanceError(f"candidate hint {group} entries must be objects")
            candidate = dict(raw)
            candidate_id = candidate.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise RetrievalHintGovernanceError("every candidate requires candidate_id")
            if candidate_id in seen:
                raise RetrievalHintGovernanceError(f"duplicate candidate id: {candidate_id}")
            seen.add(candidate_id)
            _validate_candidate_lineage(candidate, candidate_id=candidate_id)
            candidate["candidate_group"] = group
            candidates.append(candidate)
    return candidates


def _validate_candidate_lineage(candidate: Mapping[str, Any], *, candidate_id: str) -> None:
    content_hash = candidate.get("content_sha256")
    if not isinstance(content_hash, str) or not _SHA256_RE.fullmatch(content_hash):
        raise RetrievalHintGovernanceError(f"candidate {candidate_id} requires content_sha256")
    for field in ("kind", "value", "source_document", "source_document_type", "source_constraint"):
        value = candidate.get(field)
        if not isinstance(value, str) or not value:
            suffix = " lineage" if field == "source_document" else ""
            raise RetrievalHintGovernanceError(f"candidate {candidate_id} requires {field}{suffix}")


def _review_decisions(payload: Mapping[str, Any]) -> tuple[str, dict[str, dict[str, Any]]]:
    if payload.get("schema") != REVIEW_DECISIONS_SCHEMA:
        raise RetrievalHintGovernanceError(f"review decisions schema must be {REVIEW_DECISIONS_SCHEMA}")
    reviewer = payload.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise RetrievalHintGovernanceError("review decisions require reviewer")
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, list):
        raise RetrievalHintGovernanceError("review decisions must be a list")
    decisions: dict[str, dict[str, Any]] = {}
    for raw in raw_decisions:
        if not isinstance(raw, Mapping):
            raise RetrievalHintGovernanceError("review decision entries must be objects")
        item = dict(raw)
        candidate_id = item.get("candidate_id")
        decision = item.get("decision")
        reason = item.get("reason")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise RetrievalHintGovernanceError("review decision requires candidate_id")
        if candidate_id in decisions:
            raise RetrievalHintGovernanceError(f"duplicate review decision: {candidate_id}")
        if decision not in {"accept", "reject"}:
            raise RetrievalHintGovernanceError(f"review decision for {candidate_id} must be accept or reject")
        if not isinstance(reason, str) or not reason.strip():
            raise RetrievalHintGovernanceError(f"review decision for {candidate_id} requires reason")
        decisions[candidate_id] = item
    return reviewer.strip(), decisions


def _catalog_classification_allowed(candidate: Mapping[str, Any], decision: Mapping[str, Any]) -> bool:
    if decision.get("classification") != "product_catalog":
        return True
    document_type = str(candidate.get("source_document_type") or "unknown")
    if document_type in _PRODUCT_CATALOG_TYPES:
        return True
    if document_type in _OPERATIONAL_TYPES:
        return False
    evidence = decision.get("source_evidence")
    return isinstance(evidence, str) and bool(evidence.strip())


def create_reviewed_retrieval_hints(
    candidates: Mapping[str, Any],
    decisions: Mapping[str, Any],
) -> dict[str, Any]:
    """Create an exhaustive, hash-bound reviewed hint artifact."""

    candidate_digest = candidate_artifact_sha256(candidates)
    if decisions.get("input_sha256") != candidate_digest:
        raise RetrievalHintGovernanceError("review decisions input_sha256 does not match candidate artifact")
    candidate_items = _all_candidates(candidates)
    reviewer, decisions_by_id = _review_decisions(decisions)
    candidate_ids = {item["candidate_id"] for item in candidate_items}
    decision_ids = set(decisions_by_id)
    if candidate_ids != decision_ids:
        missing = sorted(candidate_ids - decision_ids)
        unknown = sorted(decision_ids - candidate_ids)
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing[:5]))
        if unknown:
            detail.append("unknown=" + ",".join(unknown[:5]))
        raise RetrievalHintGovernanceError("review decisions must cover every candidate exactly once: " + "; ".join(detail))

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    activation_hints = {group: [] for group in CANDIDATE_GROUPS}
    reviewed_candidates: list[dict[str, Any]] = []
    for candidate in candidate_items:
        candidate_id = str(candidate["candidate_id"])
        decision = decisions_by_id[candidate_id]
        if decision["decision"] == "accept" and not _catalog_classification_allowed(candidate, decision):
            raise RetrievalHintGovernanceError(
                f"candidate {candidate_id} cannot be classified as product catalog without source evidence"
            )
        record = {
            "candidate_id": candidate_id,
            "candidate_group": candidate["candidate_group"],
            "decision": decision["decision"],
            "reason": str(decision["reason"]).strip(),
            "classification": decision.get("classification"),
            "source_evidence": decision.get("source_evidence"),
            "candidate": {key: value for key, value in candidate.items() if key != "candidate_group"},
        }
        reviewed_candidates.append(record)
        if decision["decision"] == "accept":
            accepted.append(record)
            activation_hints[str(candidate["candidate_group"])].append(dict(record["candidate"]))
        else:
            rejected.append(record)

    body: dict[str, Any] = {
        "schema": REVIEWED_RETRIEVAL_HINTS_SCHEMA,
        "created_at": _now(),
        "reviewer": reviewer,
        "input_schema": candidates.get("schema"),
        "input_sha256": candidate_digest,
        "reviewed_candidates": reviewed_candidates,
        "accepted_candidates": accepted,
        "rejected_candidates": rejected,
        "activation_hints": activation_hints,
        "summary": {
            "candidate_count": len(candidate_items),
            "accepted_count": len(accepted),
            "rejected_count": len(rejected),
            "review_complete": True,
        },
    }
    body["output_sha256"] = _sha256({key: value for key, value in body.items() if key not in {"created_at", "output_sha256"}})
    return body


def validate_reviewed_retrieval_hints(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate completeness and ensure rejected candidates are absent from activation hints."""

    if payload.get("schema") != REVIEWED_RETRIEVAL_HINTS_SCHEMA:
        raise RetrievalHintGovernanceError(
            f"reviewed hint schema must be {REVIEWED_RETRIEVAL_HINTS_SCHEMA}"
        )
    reviewer = payload.get("reviewer")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise RetrievalHintGovernanceError("reviewed hint artifact requires reviewer")
    input_sha256 = payload.get("input_sha256")
    if not isinstance(input_sha256, str) or not _SHA256_RE.fullmatch(input_sha256):
        raise RetrievalHintGovernanceError("reviewed hint artifact requires input_sha256")
    reviewed = payload.get("reviewed_candidates")
    if not isinstance(reviewed, list):
        raise RetrievalHintGovernanceError("reviewed hint artifact requires reviewed_candidates")
    accepted_ids: set[str] = set()
    rejected_ids: set[str] = set()
    accepted_records: list[dict[str, Any]] = []
    rejected_records: list[dict[str, Any]] = []
    for raw in reviewed:
        if not isinstance(raw, Mapping):
            raise RetrievalHintGovernanceError("reviewed candidate entries must be objects")
        candidate_id = raw.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise RetrievalHintGovernanceError("reviewed candidate requires candidate_id")
        target = accepted_ids if raw.get("decision") == "accept" else rejected_ids if raw.get("decision") == "reject" else None
        if target is None:
            raise RetrievalHintGovernanceError(f"reviewed candidate {candidate_id} has invalid decision")
        if candidate_id in accepted_ids | rejected_ids:
            raise RetrievalHintGovernanceError(f"duplicate reviewed candidate: {candidate_id}")
        candidate = raw.get("candidate")
        if not isinstance(candidate, Mapping) or candidate.get("candidate_id") != candidate_id:
            raise RetrievalHintGovernanceError(f"reviewed candidate {candidate_id} has invalid candidate lineage")
        _validate_candidate_lineage(candidate, candidate_id=candidate_id)
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise RetrievalHintGovernanceError(f"reviewed candidate {candidate_id} requires reason")
        if raw.get("decision") == "accept" and not _catalog_classification_allowed(candidate, raw):
            raise RetrievalHintGovernanceError(
                f"candidate {candidate_id} cannot be classified as product catalog without source evidence"
            )
        target.add(candidate_id)
        (accepted_records if raw.get("decision") == "accept" else rejected_records).append(dict(raw))
    if payload.get("accepted_candidates") != accepted_records:
        raise RetrievalHintGovernanceError("accepted_candidates must match accepted reviewed_candidates")
    if payload.get("rejected_candidates") != rejected_records:
        raise RetrievalHintGovernanceError("rejected_candidates must match rejected reviewed_candidates")
    activation = payload.get("activation_hints")
    if not isinstance(activation, Mapping):
        raise RetrievalHintGovernanceError("reviewed hint artifact requires activation_hints")
    activation_ids: set[str] = set()
    expected_activation = {group: [] for group in CANDIDATE_GROUPS}
    for record in accepted_records:
        group = record.get("candidate_group")
        candidate = record.get("candidate")
        if group not in expected_activation or not isinstance(candidate, Mapping):
            raise RetrievalHintGovernanceError("accepted reviewed candidates require a valid group and candidate")
        expected_activation[str(group)].append(dict(candidate))
    for group in CANDIDATE_GROUPS:
        values = activation.get(group, [])
        if not isinstance(values, list):
            raise RetrievalHintGovernanceError(f"activation_hints.{group} must be a list")
        for raw in values:
            if not isinstance(raw, Mapping) or not isinstance(raw.get("candidate_id"), str):
                raise RetrievalHintGovernanceError(f"activation_hints.{group} entries require candidate_id")
            activation_ids.add(str(raw["candidate_id"]))
        if values != expected_activation[group]:
            raise RetrievalHintGovernanceError(
                f"activation_hints.{group} must match accepted reviewed candidate contents"
            )
    if activation_ids != accepted_ids:
        raise RetrievalHintGovernanceError("activation hints must contain exactly the accepted candidate IDs")
    if activation_ids & rejected_ids:
        raise RetrievalHintGovernanceError("rejected candidate IDs cannot appear in activation hints")
    summary = payload.get("summary")
    expected_summary = {
        "candidate_count": len(reviewed),
        "accepted_count": len(accepted_records),
        "rejected_count": len(rejected_records),
        "review_complete": True,
    }
    if summary != expected_summary:
        raise RetrievalHintGovernanceError("reviewed hint summary does not match candidate decisions")
    expected = _sha256({key: value for key, value in payload.items() if key not in {"created_at", "output_sha256"}})
    if payload.get("output_sha256") != expected:
        raise RetrievalHintGovernanceError("reviewed hint output_sha256 does not match artifact contents")
    return dict(payload)


def load_reviewed_retrieval_hints(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RetrievalHintGovernanceError(f"reviewed hint file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise RetrievalHintGovernanceError(f"reviewed hint file is not valid JSON: {source}") from exc
    if not isinstance(payload, Mapping):
        raise RetrievalHintGovernanceError("reviewed hint file must contain an object")
    return validate_reviewed_retrieval_hints(payload)
