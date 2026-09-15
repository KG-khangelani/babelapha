#!/usr/bin/env python3
"""Independently verify one Babelapha provenance evidence-bundle response."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request


DOCUMENT_CANONICALIZATION = "SORTED_INDENTED_JSON_V1"
EVIDENCE_SET_CANONICALIZATION = "SORTED_COMPACT_JSON_V1"
EVIDENCE_SET_SCHEMA_VERSION = "1.0.0"
SUPPORTED_API_VERSION = "1.7.0"


class EvidenceVerificationError(ValueError):
    """The supplied bundle cannot be verified as a coherent evidence snapshot."""


def _document_bytes(document: dict) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _require_mapping(value: object, context: str) -> dict:
    if not isinstance(value, dict):
        raise EvidenceVerificationError(f"{context} must be a JSON object")
    return value


def _require_fields(value: dict, fields: set[str], context: str) -> None:
    if set(value) != fields:
        raise EvidenceVerificationError(f"{context} fields do not match the v1 contract")


def _execution_facet(event: dict, context: str) -> dict:
    try:
        return _require_mapping(
            event["run"]["facets"]["babelapha_execution"],
            f"{context} execution facet",
        )
    except (KeyError, TypeError) as exc:
        raise EvidenceVerificationError(
            f"{context} has no Babelapha execution facet"
        ) from exc


def _index_documents(entries: object, kind: str) -> dict[str, dict]:
    if not isinstance(entries, list):
        raise EvidenceVerificationError(f"documents.{kind} must be an array")
    indexed: dict[str, dict] = {}
    required = {"manifest_id", "uri", "sha256", "canonicalization", "document"}
    for index, raw_entry in enumerate(entries):
        context = f"documents.{kind}[{index}]"
        entry = _require_mapping(raw_entry, context)
        _require_fields(entry, required, context)
        manifest_id = entry["manifest_id"]
        if not isinstance(manifest_id, str) or not manifest_id:
            raise EvidenceVerificationError(f"{context}.manifest_id must be non-empty")
        if manifest_id in indexed:
            raise EvidenceVerificationError(
                f"documents.{kind} repeats manifest ID {manifest_id}"
            )
        if entry["canonicalization"] != DOCUMENT_CANONICALIZATION:
            raise EvidenceVerificationError(
                f"{context} uses unsupported canonicalization {entry['canonicalization']!r}"
            )
        document = _require_mapping(entry["document"], f"{context}.document")
        calculated = _sha256(_document_bytes(document))
        if entry["sha256"] != calculated:
            raise EvidenceVerificationError(
                f"{context} SHA-256 differs from its canonical document bytes"
            )
        indexed[manifest_id] = entry
    return indexed


def _evidence_set_material(bundle: dict) -> tuple[dict, dict]:
    evidence_set = _require_mapping(bundle.get("evidence_set"), "evidence_set")
    _require_fields(
        evidence_set,
        {
            "schema_version",
            "canonicalization",
            "algorithm",
            "sha256",
            "manifest_count",
            "openlineage_event_count",
            "delivery_receipt_count",
        },
        "evidence_set",
    )
    if evidence_set["schema_version"] != EVIDENCE_SET_SCHEMA_VERSION:
        raise EvidenceVerificationError("Unsupported evidence-set schema version")
    if evidence_set["canonicalization"] != EVIDENCE_SET_CANONICALIZATION:
        raise EvidenceVerificationError("Unsupported evidence-set canonicalization")
    if evidence_set["algorithm"] != "SHA-256":
        raise EvidenceVerificationError("Unsupported evidence-set algorithm")

    documents = _require_mapping(bundle.get("documents"), "documents")
    _require_fields(
        documents,
        {"manifests", "openlineage_events", "delivery_receipts"},
        "documents",
    )
    manifests = _index_documents(documents.get("manifests"), "manifests")
    events = _index_documents(documents.get("openlineage_events"), "openlineage_events")
    receipts = _index_documents(documents.get("delivery_receipts"), "delivery_receipts")

    object_id = bundle.get("object_id")
    if not isinstance(object_id, str) or not object_id:
        raise EvidenceVerificationError("object_id must be non-empty")
    run_ids: set[str] = set()
    manifest_material = []
    for manifest_id, entry in manifests.items():
        document = entry["document"]
        try:
            document_manifest_id = document["manifest_id"]
            document_object_id = document["object"]["id"]
            run_id = document["run"]["id"]
            manifest_uri = document["links"]["manifest"]
        except (KeyError, TypeError) as exc:
            raise EvidenceVerificationError(
                f"Manifest {manifest_id} lacks its declared identity"
            ) from exc
        if document_manifest_id != manifest_id:
            raise EvidenceVerificationError(f"Manifest {manifest_id} has the wrong join identity")
        if document_object_id != object_id:
            raise EvidenceVerificationError(f"Manifest {manifest_id} has the wrong object ID")
        if manifest_uri != entry["uri"]:
            raise EvidenceVerificationError(f"Manifest {manifest_id} has the wrong storage URI")
        if not isinstance(run_id, str) or not run_id:
            raise EvidenceVerificationError(f"Manifest {manifest_id} has no run ID")
        run_ids.add(run_id)
        manifest_material.append(
            {
                "manifest_id": manifest_id,
                "manifest_uri": entry["uri"],
                "manifest_sha256": entry["sha256"],
            }
        )

    if bundle.get("record_count") != len(manifests):
        raise EvidenceVerificationError("record_count differs from the manifest document count")
    if bundle.get("run_count") != len(run_ids):
        raise EvidenceVerificationError("run_count differs from the manifest run identities")

    delivery = _require_mapping(bundle.get("openlineage_delivery"), "openlineage_delivery")
    _require_fields(
        delivery,
        {"state_counts", "by_manifest_id", "unmatched", "errors"},
        "openlineage_delivery",
    )
    by_manifest = _require_mapping(delivery.get("by_manifest_id"), "by_manifest_id")
    unmatched = _require_mapping(delivery.get("unmatched"), "unmatched")
    errors = delivery.get("errors")
    if not isinstance(errors, list):
        raise EvidenceVerificationError("openlineage_delivery.errors must be an array")
    if set(by_manifest) != set(manifests):
        raise EvidenceVerificationError(
            "OpenLineage delivery identities differ from the manifest document identities"
        )
    state_counts: dict[str, int] = {}
    for state in by_manifest.values():
        state = _require_mapping(state, "OpenLineage delivery state")
        state_name = state.get("state")
        state_counts[state_name] = state_counts.get(state_name, 0) + 1
    if delivery.get("state_counts") != state_counts:
        raise EvidenceVerificationError("OpenLineage state counts do not match the evidence states")

    all_states = {**by_manifest, **unmatched}
    if len(all_states) != len(by_manifest) + len(unmatched):
        raise EvidenceVerificationError("Matched and unmatched lineage identities overlap")
    for manifest_id, entry in events.items():
        if manifest_id not in manifests:
            raise EvidenceVerificationError(f"Queued event {manifest_id} has no manifest")
        facet = _execution_facet(entry["document"], f"Queued event {manifest_id}")
        if facet.get("manifestId") != manifest_id:
            raise EvidenceVerificationError(f"Queued event {manifest_id} has the wrong join identity")
        state = _require_mapping(all_states.get(manifest_id), f"Queued event {manifest_id} state")
        if state.get("outbox_uri") != entry["uri"] or state.get("event_sha256") != entry["sha256"]:
            raise EvidenceVerificationError(f"Queued event {manifest_id} differs from its delivery state")
    for manifest_id, entry in receipts.items():
        if manifest_id not in manifests:
            raise EvidenceVerificationError(f"Delivery receipt {manifest_id} has no manifest")
        document = entry["document"]
        if document.get("manifest_id") != manifest_id:
            raise EvidenceVerificationError(f"Delivery receipt {manifest_id} has the wrong join identity")
        event = events.get(manifest_id)
        if event is None or document.get("event_sha256") != event["sha256"]:
            raise EvidenceVerificationError(f"Delivery receipt {manifest_id} has the wrong event hash")
        if document.get("outbox_uri") != event["uri"]:
            raise EvidenceVerificationError(f"Delivery receipt {manifest_id} has the wrong outbox URI")
        state = _require_mapping(all_states.get(manifest_id), f"Delivery receipt {manifest_id} state")
        if state.get("receipt_uri") != entry["uri"] or state.get("receipt_sha256") != entry["sha256"]:
            raise EvidenceVerificationError(f"Delivery receipt {manifest_id} differs from its state")

    for manifest_id, state in by_manifest.items():
        if state.get("integrity") != "VERIFIED" or state.get("state") not in {
            "PENDING",
            "DELIVERED",
        }:
            raise EvidenceVerificationError(
                f"Manifest {manifest_id} has unverified OpenLineage evidence"
            )
        if manifest_id not in events:
            raise EvidenceVerificationError(f"Manifest {manifest_id} has no verified queued event")
        if state["state"] == "DELIVERED" and manifest_id not in receipts:
            raise EvidenceVerificationError(f"Manifest {manifest_id} has no verified delivery receipt")
    if unmatched or errors:
        raise EvidenceVerificationError("The evidence bundle contains unmatched or invalid lineage evidence")

    lineage = [
        {"manifest_id": manifest_id, **state}
        for manifest_id, state in sorted(by_manifest.items())
    ]
    unmatched_lineage = [
        {"manifest_id": manifest_id, **state}
        for manifest_id, state in sorted(unmatched.items())
    ]
    ordered_errors = sorted(
        errors,
        key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
    )
    material = {
        "schema_version": EVIDENCE_SET_SCHEMA_VERSION,
        "object_id": object_id,
        "manifests": sorted(
            manifest_material,
            key=lambda item: (item["manifest_uri"], item["manifest_id"]),
        ),
        "lineage": lineage,
        "unmatched_lineage": unmatched_lineage,
        "errors": ordered_errors,
    }
    return evidence_set, {
        "material": material,
        "manifest_count": len(manifests),
        "event_count": sum(
            bool(
                item["state"] != "ORPHANED_RECEIPT"
                and item["outbox_uri"]
                and item["event_sha256"]
            )
            for item in lineage + unmatched_lineage
        ),
        "receipt_count": sum(
            bool(item["receipt_uri"] and item["receipt_sha256"])
            for item in lineage + unmatched_lineage
        ),
        "document_count": len(manifests) + len(events) + len(receipts),
        "state_counts": state_counts,
    }


def verify_evidence_bundle(payload: dict) -> dict:
    """Verify all document hashes, cross-links, counts, and the evidence-set hash."""
    envelope = _require_mapping(payload, "response")
    _require_fields(envelope, {"api_version", "data"}, "response")
    if envelope["api_version"] != SUPPORTED_API_VERSION:
        raise EvidenceVerificationError(
            f"Unsupported API version {envelope['api_version']!r}"
        )
    bundle = _require_mapping(envelope["data"], "data")
    _require_fields(
        bundle,
        {
            "object_id",
            "run_count",
            "record_count",
            "evidence_set",
            "documents",
            "openlineage_delivery",
        },
        "data",
    )
    evidence_set, calculated = _evidence_set_material(bundle)
    material_bytes = json.dumps(
        calculated["material"],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected = {
        "manifest_count": calculated["manifest_count"],
        "openlineage_event_count": calculated["event_count"],
        "delivery_receipt_count": calculated["receipt_count"],
        "sha256": _sha256(material_bytes),
    }
    for field, value in expected.items():
        if evidence_set[field] != value:
            raise EvidenceVerificationError(f"evidence_set.{field} could not be reproduced")
    return {
        "verification": "VERIFIED",
        "api_version": envelope["api_version"],
        "object_id": bundle["object_id"],
        "run_count": bundle["run_count"],
        "record_count": bundle["record_count"],
        "document_count": calculated["document_count"],
        "openlineage_state_counts": calculated["state_counts"],
        "evidence_set_sha256": evidence_set["sha256"],
    }


def load_payload(source: str) -> dict:
    """Read a bundle response from HTTP(S), a local JSON file, or stdin."""
    if source == "-":
        return json.load(sys.stdin)
    parsed = urllib.parse.urlparse(source)
    if parsed.scheme in {"http", "https"}:
        request = urllib.request.Request(source, headers={"Accept": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    is_windows_path = (
        len(parsed.scheme) == 1
        and len(source) >= 3
        and source[1] == ":"
        and source[2] in {"\\", "/"}
    )
    if parsed.scheme and not is_windows_path:
        raise EvidenceVerificationError(f"Unsupported source scheme {parsed.scheme!r}")
    return json.loads(Path(source).read_text(encoding="utf-8"))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify canonical documents and the evidence-set fingerprint in one provenance API bundle."
    )
    parser.add_argument("source", help="Evidence-bundle URL, JSON file, or '-' for stdin")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = verify_evidence_bundle(load_payload(args.source))
    except Exception as exc:
        print(
            json.dumps(
                {"verification": "FAILED", "error": f"{type(exc).__name__}: {exc}"},
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
