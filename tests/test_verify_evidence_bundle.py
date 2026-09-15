import copy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
AIRFLOW_DIR = ROOT / "pipelines" / "airflow"
sys.path.insert(0, str(AIRFLOW_DIR))

import inspect_provenance as inspector  # noqa: E402
import provenance  # noqa: E402
import verify_evidence_bundle as verifier  # noqa: E402


def sample_bundle() -> dict:
    record = provenance.build_manifest(
        object_id="interview/002",
        filename="interview.mp4",
        run_id="manual__run-42",
        dag_id="ingest_pipeline",
        task_id="validate_inputs",
        stage="request_validated",
        attempt=1,
        status="SUCCEEDED",
        decision={
            "outcome": "accepted",
            "reason_code": "INPUT_PARAMETERS_ACCEPTED",
            "message": "The request is valid.",
        },
        completed_at=datetime.now(timezone.utc),
        git_commit="b" * 40,
        code_path="/opt/airflow/dags/ingest_pipeline.py",
        code_sha256="c" * 64,
        container_image="babelapha-airflow",
        container_digest="sha256:" + "d" * 64,
    )
    event = provenance.build_openlineage_event(record)
    outbox_uri = (
        "s3://pachyderm/" + provenance.openlineage_event_key(event, "outbox")
    )
    receipt_uri = (
        "s3://pachyderm/" + provenance.openlineage_event_key(event, "delivered")
    )
    event_sha256 = hashlib.sha256(provenance.canonical_json_bytes(event)).hexdigest()
    facet = event["run"]["facets"]["babelapha_execution"]
    receipt = {
        "$schema": provenance.OPENLINEAGE_RECEIPT_SCHEMA_URI,
        "schema_version": provenance.SCHEMA_VERSION,
        "manifest_id": record["manifest_id"],
        "object_id": facet["objectId"],
        "airflow_run_id": facet["airflowRunId"],
        "task_id": facet["taskId"],
        "attempt": facet["attempt"],
        "status": facet["status"],
        "event_type": event["eventType"],
        "outbox_uri": outbox_uri,
        "event_sha256": event_sha256,
        "endpoint": "http://marquez:5000/api/v1/lineage",
        "http_status": 201,
        "delivered_at": "2026-09-15T10:00:00Z",
    }
    receipt_sha256 = hashlib.sha256(
        provenance.canonical_json_bytes(receipt)
    ).hexdigest()
    state = {
        "state": "DELIVERED",
        "integrity": "VERIFIED",
        "outbox_uri": outbox_uri,
        "event_sha256": event_sha256,
        "receipt_uri": receipt_uri,
        "receipt_sha256": receipt_sha256,
        "endpoint": receipt["endpoint"],
        "http_status": receipt["http_status"],
        "delivered_at": receipt["delivered_at"],
        "error": None,
    }
    evidence = {
        "states": {record["manifest_id"]: state},
        "events": {
            record["manifest_id"]: {
                "manifest_id": record["manifest_id"],
                "uri": outbox_uri,
                "sha256": event_sha256,
                "canonicalization": "SORTED_INDENTED_JSON_V1",
                "document": event,
            }
        },
        "receipts": {
            record["manifest_id"]: {
                "manifest_id": record["manifest_id"],
                "uri": receipt_uri,
                "sha256": receipt_sha256,
                "canonicalization": "SORTED_INDENTED_JSON_V1",
                "document": receipt,
            }
        },
        "errors": [],
    }
    return {
        "api_version": "1.7.0",
        "data": inspector.build_evidence_bundle(
            "interview/002",
            [record],
            evidence,
        ),
    }


class EvidenceBundleVerifierTests(unittest.TestCase):
    def test_verifier_reconstructs_documents_cross_links_and_evidence_set(self):
        bundle = sample_bundle()

        result = verifier.verify_evidence_bundle(bundle)

        self.assertEqual(result["verification"], "VERIFIED")
        self.assertEqual(result["object_id"], "interview/002")
        self.assertEqual(result["run_count"], 1)
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["document_count"], 3)
        self.assertEqual(result["openlineage_state_counts"], {"DELIVERED": 1})
        self.assertEqual(
            result["evidence_set_sha256"],
            bundle["data"]["evidence_set"]["sha256"],
        )

    def test_verifier_rejects_tampered_documents_and_fingerprints(self):
        cases = []
        document_tamper = copy.deepcopy(sample_bundle())
        document_tamper["data"]["documents"]["manifests"][0]["document"][
            "decision"
        ]["message"] = "tampered"
        cases.append((document_tamper, "SHA-256 differs"))

        fingerprint_tamper = copy.deepcopy(sample_bundle())
        fingerprint_tamper["data"]["evidence_set"]["sha256"] = "0" * 64
        cases.append((fingerprint_tamper, "could not be reproduced"))

        for payload, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(
                    verifier.EvidenceVerificationError,
                    message,
                ):
                    verifier.verify_evidence_bundle(payload)


if __name__ == "__main__":
    unittest.main()
