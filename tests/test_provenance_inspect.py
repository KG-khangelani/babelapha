import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "pipelines" / "airflow" / "inspect_provenance.py"
SPEC = importlib.util.spec_from_file_location("babelapha_provenance_inspect", MODULE_PATH)
inspector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(inspector)
provenance = inspector.sys.modules["provenance"]


class MemoryS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs["Body"]

    def get_object(self, *, Key, **_kwargs):
        return {"Body": io.BytesIO(self.objects[Key])}

    def get_paginator(self, _name):
        client = self

        class Paginator:
            @staticmethod
            def paginate(*, Prefix, **_kwargs):
                keys = sorted(key for key in client.objects if key.startswith(Prefix))
                return [{"Contents": [{"Key": key} for key in keys]}]

        return Paginator()

    def list_objects_v2(
        self,
        *,
        Prefix,
        Delimiter,
        MaxKeys,
        ContinuationToken=None,
        **_kwargs,
    ):
        prefixes = sorted(
            {
                Prefix + key[len(Prefix) :].split(Delimiter, 1)[0] + Delimiter
                for key in self.objects
                if key.startswith(Prefix) and Delimiter in key[len(Prefix) :]
            }
        )
        start = int(ContinuationToken or 0)
        selected = prefixes[start : start + MaxKeys]
        next_index = start + len(selected)
        return {
            "CommonPrefixes": [{"Prefix": prefix} for prefix in selected],
            "IsTruncated": next_index < len(prefixes),
            "NextContinuationToken": str(next_index) if next_index < len(prefixes) else None,
        }


def sample_record(
    *,
    task_id="validate_media",
    status="SUCCEEDED",
    recorded_at="2026-09-15T08:00:00Z",
    dag_id="ingest_pipeline",
    parameters=None,
):
    if parameters is None:
        parameters = {
            "dag_code_bundle_sha256": "e" * 64,
            "git_identity_status": "VERIFIED_BUNDLE_ATTESTATION",
        }
    source = provenance.artifact(
        "s3://pachyderm/incoming/interview-042/interview.mp4",
        sha256="a" * 64,
        size_bytes=42,
        media_type="video/mp4",
        pachyderm_commit="pachyderm-commit-42",
        s3_version_id="version-42",
        etag="etag-42",
    )
    return provenance.build_manifest(
        object_id="interview-042",
        filename="interview.mp4",
        run_id="manual__run-42",
        dag_id=dag_id,
        task_id=task_id,
        stage=task_id,
        attempt=1,
        status=status,
        decision={
            "outcome": "valid" if status == "SUCCEEDED" else "failed",
            "reason_code": "FFPROBE_ACCEPTED_MEDIA" if status == "SUCCEEDED" else "TASK_FAILED",
            "message": "Visible stage decision.",
        },
        inputs=[source],
        outputs=[source] if status == "SUCCEEDED" else [],
        completed_at=recorded_at,
        git_commit="b" * 40,
        code_path="/opt/airflow/dags/ingest_pipeline.py",
        code_sha256="c" * 64,
        container_image="registry/validate",
        container_digest="sha256:" + "d" * 64,
        parameters=parameters,
        airflow_version="3.3.1",
    )


class ProvenanceInspectorTests(unittest.TestCase):
    def test_catalog_lists_canonical_media_ids_with_pagination(self):
        client = MemoryS3()
        client.objects = {
            "provenance/interview-001/run/task/1-succeeded.json": b"{}",
            "provenance/interview%2F002/run/task/1-succeeded.json": b"{}",
            "provenance/third%20item/run/task/1-succeeded.json": b"{}",
        }

        with mock.patch.object(inspector, "_s3_client", return_value=client):
            first = inspector.list_media_items(limit=2)
            second = inspector.list_media_items(cursor=first["next_cursor"], limit=2)

        self.assertEqual(
            [item["object_id"] for item in first["items"]],
            ["interview/002", "interview-001"],
        )
        self.assertEqual(first["item_count"], 2)
        self.assertEqual(first["next_cursor"], "2")
        self.assertEqual(second["items"], [{"object_id": "third item"}])
        self.assertIsNone(second["next_cursor"])
        self.assertIn("interview/002", inspector.render_catalog_text(first))

    def test_catalog_rejects_noncanonical_object_prefixes_and_invalid_limits(self):
        class InvalidPrefixClient:
            @staticmethod
            def list_objects_v2(**_kwargs):
                return {
                    "CommonPrefixes": [{"Prefix": "provenance/lower%2fslash/"}],
                    "IsTruncated": False,
                }

        with mock.patch.object(inspector, "_s3_client", return_value=InvalidPrefixClient()):
            with self.assertRaisesRegex(ValueError, "Non-canonical"):
                inspector.list_media_items()
        for limit in (0, 201, True):
            with self.subTest(limit=limit):
                with self.assertRaisesRegex(ValueError, "between 1 and 200"):
                    inspector.list_media_items(limit=limit)

    def test_text_view_exposes_required_milestone_evidence(self):
        records = [
            sample_record(),
            sample_record(task_id="transcode", status="FAILED", recorded_at="2026-09-15T08:01:00Z"),
        ]
        rendered = inspector.render_text(inspector.build_view("interview-042", records))

        for expected in (
            "Run: manual__run-42",
            "DAG: ingest_pipeline",
            "Task coverage: 2/8 recorded",
            "Task contract: source=CURRENT_REGISTRY_FALLBACK evidence=FALLBACK",
            "No immutable execution record: validate_inputs, inspect_source, virus_scan, verify_outputs, mark_complete, verify_provenance",
            "[FAILED] stage=transcode task=transcode attempt=1",
            "decision=TASK_FAILED",
            "sha256=" + "a" * 64,
            "pachyderm_commit=pachyderm-commit-42",
            "s3_version=version-42",
            "git=https://github.com/KG-khangelani/babelapha@" + "b" * 40,
            "identity=VERIFIED_BUNDLE_ATTESTATION",
            "code=/opt/airflow/dags/ingest_pipeline.py sha256=" + "c" * 64,
            "bundle_sha256=" + "e" * 64,
            "container=registry/validate digest=sha256:" + "d" * 64,
        ):
            self.assertIn(expected, rendered)

    def test_task_coverage_exposes_missing_stages_without_inventing_state(self):
        records = [
            sample_record(task_id="validate_inputs"),
            sample_record(
                task_id="inspect_source",
                status="RETRYING",
                recorded_at="2026-09-15T08:01:00Z",
            ),
            sample_record(
                task_id="inspect_source",
                status="FAILED",
                recorded_at="2026-09-15T08:02:00Z",
            ),
        ]

        run = inspector.build_view("interview-042", records)["runs"][0]

        self.assertEqual(run["dag_id"], "ingest_pipeline")
        self.assertEqual(
            run["task_coverage"],
            {
                "contract_known": True,
                "contract_source": "CURRENT_REGISTRY_FALLBACK",
                "contract_sha256": provenance.pipeline_task_contract("ingest_pipeline")["sha256"],
                "contract_evidence_status": "FALLBACK",
                "records_with_embedded_contract": 0,
                "record_count": 3,
                "expected_task_ids": list(provenance.PIPELINE_TASK_CONTRACTS["ingest_pipeline"]),
                "recorded_task_ids": ["validate_inputs", "inspect_source"],
                "not_recorded_task_ids": [
                    "virus_scan",
                    "validate_media",
                    "transcode",
                    "verify_outputs",
                    "mark_complete",
                    "verify_provenance",
                ],
                "unexpected_task_ids": [],
            },
        )
        self.assertEqual(run["statuses_observed"], ["FAILED", "RETRYING", "SUCCEEDED"])

    def test_complete_task_coverage_includes_the_final_gate(self):
        records = [
            sample_record(task_id=task_id, recorded_at=f"2026-09-15T08:{minute:02d}:00Z")
            for minute, task_id in enumerate(
                provenance.PIPELINE_TASK_CONTRACTS["ingest_pipeline"]
            )
        ]

        coverage = inspector.build_view("interview-042", records)["runs"][0]["task_coverage"]

        self.assertEqual(coverage["recorded_task_ids"], coverage["expected_task_ids"])
        self.assertEqual(coverage["not_recorded_task_ids"], [])
        self.assertEqual(coverage["unexpected_task_ids"], [])

    def test_unknown_dag_reports_unknown_contract_and_preserves_records(self):
        record = sample_record(task_id="custom_stage", dag_id="historical_ingest")

        run = inspector.build_view("interview-042", [record])["runs"][0]

        self.assertEqual(
            run["task_coverage"],
            {
                "contract_known": False,
                "contract_source": "UNKNOWN",
                "contract_sha256": None,
                "contract_evidence_status": "UNKNOWN",
                "records_with_embedded_contract": 0,
                "record_count": 1,
                "expected_task_ids": [],
                "recorded_task_ids": ["custom_stage"],
                "not_recorded_task_ids": [],
                "unexpected_task_ids": [],
            },
        )
        self.assertIn(
            "Task coverage: 1/unknown recorded",
            inspector.render_text(inspector.build_view("interview-042", [record])),
        )

    def test_one_run_id_cannot_mix_dag_identities(self):
        records = [
            sample_record(task_id="validate_inputs"),
            sample_record(task_id="validate_inputs", dag_id="ingest_pipeline_local"),
        ]

        with self.assertRaisesRegex(ValueError, "records from multiple DAGs"):
            inspector.build_view("interview-042", records)

    def test_embedded_contract_preserves_historical_topology_after_registry_drift(self):
        historical_contract = {
            "schema_version": provenance.PIPELINE_TASK_CONTRACT_VERSION,
            "dag_id": "ingest_pipeline",
            "task_ids": ["legacy_stage", "verify_provenance"],
        }
        historical_contract["sha256"] = provenance._pipeline_task_contract_sha256(
            historical_contract
        )
        record = sample_record(
            task_id="legacy_stage",
            parameters={"pipeline_task_contract": historical_contract},
        )

        coverage = inspector.build_view("interview-042", [record])["runs"][0]["task_coverage"]

        self.assertEqual(coverage["contract_source"], "MANIFEST_EMBEDDED")
        self.assertEqual(coverage["contract_evidence_status"], "COMPLETE")
        self.assertEqual(coverage["contract_sha256"], historical_contract["sha256"])
        self.assertEqual(coverage["expected_task_ids"], ["legacy_stage", "verify_provenance"])
        self.assertEqual(coverage["not_recorded_task_ids"], ["verify_provenance"])

    def test_partially_embedded_contract_is_explicit(self):
        contract = provenance.pipeline_task_contract("ingest_pipeline")
        records = [
            sample_record(
                task_id="validate_inputs",
                parameters={"pipeline_task_contract": contract},
            ),
            sample_record(task_id="inspect_source", recorded_at="2026-09-15T08:01:00Z"),
        ]

        coverage = inspector.build_view("interview-042", records)["runs"][0]["task_coverage"]

        self.assertEqual(coverage["contract_source"], "MANIFEST_EMBEDDED")
        self.assertEqual(coverage["contract_evidence_status"], "PARTIAL")
        self.assertEqual(coverage["records_with_embedded_contract"], 1)
        self.assertEqual(coverage["record_count"], 2)

    def test_s3_reader_validates_and_sorts_records(self):
        later = sample_record(task_id="transcode", recorded_at="2026-09-15T08:01:00Z")
        earlier = sample_record(recorded_at="2026-09-15T08:00:00Z")
        objects = {
            "provenance/interview-042/manual__run-42/transcode/1-succeeded.json": later,
            "provenance/interview-042/manual__run-42/validate_media/1-succeeded.json": earlier,
        }

        class Paginator:
            @staticmethod
            def paginate(**_kwargs):
                return [{"Contents": [{"Key": key} for key in reversed(list(objects))]}]

        class Client:
            @staticmethod
            def get_paginator(_name):
                return Paginator()

            @staticmethod
            def get_object(*, Key, **_kwargs):
                return {"Body": io.BytesIO(json.dumps(objects[Key]).encode())}

        with mock.patch.object(inspector, "_s3_client", return_value=Client()):
            records = inspector.read_records(object_id="interview-042", run_id="manual__run-42")

        self.assertEqual([record["run"]["task_id"] for record in records], ["validate_media", "transcode"])

    def test_media_view_joins_delivered_and_pending_openlineage_evidence(self):
        client = MemoryS3()
        delivered_record = sample_record(task_id="validate_media")
        pending_record = sample_record(task_id="transcode", recorded_at="2026-09-15T08:01:00Z")
        delivered_event = provenance.build_openlineage_event(delivered_record)
        delivered_event["job"]["namespace"] = "babelapha-production"
        pending_event = provenance.build_openlineage_event(pending_record)
        pending_event["job"]["namespace"] = "babelapha-production"
        delivered_outbox = provenance.persist_openlineage_event(delivered_event, client=client)
        provenance.persist_openlineage_event(pending_event, client=client)
        provenance.persist_openlineage_receipt(
            delivered_event,
            outbox_uri=delivered_outbox,
            openlineage_target="http://marquez:5000/api/v1/lineage",
            http_status=201,
            client=client,
        )

        with mock.patch.object(inspector, "_s3_client", return_value=client):
            evidence = inspector.read_openlineage_delivery_evidence(
                object_id="interview-042",
                records=[delivered_record, pending_record],
            )
        view = inspector.build_view("interview-042", [delivered_record, pending_record], evidence)
        rendered = inspector.render_text(view)

        self.assertEqual(
            evidence["states"][delivered_record["manifest_id"]]["state"],
            "DELIVERED",
        )
        self.assertEqual(evidence["states"][pending_record["manifest_id"]]["state"], "PENDING")
        self.assertEqual(view["openlineage_delivery"]["state_counts"], {"DELIVERED": 1, "PENDING": 1})
        self.assertIn("OpenLineage: DELIVERED=1, PENDING=1", rendered)
        self.assertIn("state=DELIVERED integrity=VERIFIED", rendered)
        self.assertIn("state=PENDING integrity=VERIFIED", rendered)
        self.assertIn("event_sha256=", rendered)
        self.assertIn("http=201", rendered)

    def test_media_view_surfaces_outbox_manifest_mismatch_as_integrity_error(self):
        client = MemoryS3()
        record = sample_record()
        event = provenance.build_openlineage_event(record)
        event["run"]["facets"]["babelapha_execution"]["decisionMessage"] = "tampered"
        provenance.persist_openlineage_event(event, client=client)

        with mock.patch.object(inspector, "_s3_client", return_value=client):
            evidence = inspector.read_openlineage_delivery_evidence(
                object_id="interview-042",
                records=[record],
            )
        view = inspector.build_view("interview-042", [record], evidence)

        state = view["openlineage_delivery"]["by_manifest_id"][record["manifest_id"]]
        self.assertEqual(state["state"], "INTEGRITY_ERROR")
        self.assertEqual(state["integrity"], "FAILED")
        self.assertIn("facts differ from the canonical manifest", state["error"])

    def test_media_view_distinguishes_missing_outbox_and_orphaned_receipt(self):
        record = sample_record()
        missing_view = inspector.build_view(
            "interview-042",
            [record],
            {"states": {}, "errors": []},
        )
        self.assertEqual(
            missing_view["openlineage_delivery"]["by_manifest_id"][record["manifest_id"]]["state"],
            "MISSING_OUTBOX",
        )

        client = MemoryS3()
        event = provenance.build_openlineage_event(record)
        outbox_uri = provenance.persist_openlineage_event(event, client=client)
        provenance.persist_openlineage_receipt(
            event,
            outbox_uri=outbox_uri,
            openlineage_target="http://marquez:5000/api/v1/lineage",
            http_status=201,
            client=client,
        )
        del client.objects[provenance.openlineage_event_key(event, "outbox")]
        with mock.patch.object(inspector, "_s3_client", return_value=client):
            evidence = inspector.read_openlineage_delivery_evidence(
                object_id="interview-042",
                records=[record],
            )

        self.assertEqual(evidence["states"][record["manifest_id"]]["state"], "ORPHANED_RECEIPT")
        self.assertEqual(evidence["errors"][0]["state"], "ORPHANED_RECEIPT")
        orphaned_view = inspector.build_view("interview-042", [record], evidence)
        self.assertEqual(inspector.delivery_exit_code(missing_view), 3)
        self.assertEqual(inspector.delivery_exit_code(orphaned_view), 3)

    def test_pending_delivery_can_be_optionally_enforced(self):
        record = sample_record()
        pending = {
            "state": "PENDING",
            "integrity": "VERIFIED",
            "outbox_uri": "s3://pachyderm/openlineage/outbox/pending.json",
            "event_sha256": "a" * 64,
            "receipt_uri": None,
            "endpoint": None,
            "http_status": None,
            "delivered_at": None,
            "error": None,
        }
        view = inspector.build_view(
            "interview-042",
            [record],
            {"states": {record["manifest_id"]: pending}, "errors": []},
        )
        self.assertEqual(inspector.delivery_exit_code(view), 0)
        self.assertEqual(inspector.delivery_exit_code(view, require_delivered=True), 4)


if __name__ == "__main__":
    unittest.main()
