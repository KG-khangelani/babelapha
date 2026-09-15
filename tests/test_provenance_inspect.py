import importlib.util
import copy
import hashlib
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
            "Run identity: consistency=VERIFIED",
            "pachyderm_commit=pachyderm-commit-42",
            "Stage evidence:",
            "position=5 task=transcode membership=EXPECTED evidence=RECORDED attempts=1:FAILED:TASK_FAILED",
            "Artifact evidence: 1",
            "occurrences=validate_media:1:INPUT, validate_media:1:OUTPUT, transcode:1:INPUT",
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
            "Evidence set: sha256=",
            "manifest="
            + records[0]["links"]["manifest"]
            + " sha256="
            + hashlib.sha256(provenance.canonical_json_bytes(records[0])).hexdigest(),
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
        self.assertEqual(
            run["run_identity"],
            {
                "consistency": "VERIFIED",
                "completeness": "COMPLETE",
                "missing_fields": [],
                "object_filename": "interview.mp4",
                "pachyderm_commit": "pachyderm-commit-42",
                "git": {
                    "repository": "https://github.com/KG-khangelani/babelapha",
                    "commit": "b" * 40,
                    "identity_status": "VERIFIED_BUNDLE_ATTESTATION",
                },
                "code": {
                    "path": "/opt/airflow/dags/ingest_pipeline.py",
                    "sha256": "c" * 64,
                    "bundle_sha256": "e" * 64,
                },
                "orchestrator": {"name": "airflow", "version": "3.3.1"},
            },
        )
        stages = run["stage_evidence"]
        self.assertEqual(
            [stage["task_id"] for stage in stages],
            list(provenance.PIPELINE_TASK_CONTRACTS["ingest_pipeline"]),
        )
        self.assertEqual(stages[0]["contract_position"], 1)
        self.assertEqual(stages[0]["contract_membership"], "EXPECTED")
        self.assertEqual(stages[0]["evidence_state"], "RECORDED")
        self.assertEqual(
            [attempt["status"] for attempt in stages[1]["attempts"]],
            ["RETRYING", "FAILED"],
        )
        self.assertEqual(stages[2]["evidence_state"], "NO_IMMUTABLE_RECORD")
        self.assertEqual(stages[2]["attempts"], [])
        artifacts = run["artifact_evidence"]
        self.assertEqual(len(artifacts), 1)
        self.assertEqual(artifacts[0]["uri"], records[0]["inputs"][0]["uri"])
        self.assertEqual(artifacts[0]["sha256"], "a" * 64)
        self.assertEqual(artifacts[0]["size_bytes"], 42)
        self.assertEqual(artifacts[0]["integrity"], "VERIFIED")
        self.assertEqual(artifacts[0]["observation_count"], 4)
        self.assertEqual(
            [occurrence["direction"] for occurrence in artifacts[0]["occurrences"]],
            ["INPUT", "OUTPUT", "INPUT", "INPUT"],
        )

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

    def test_stage_ledger_appends_observed_tasks_outside_the_contract(self):
        record = sample_record(task_id="legacy_side_task")

        stage = inspector.build_view("interview-042", [record])["runs"][0][
            "stage_evidence"
        ][-1]

        self.assertEqual(stage["task_id"], "legacy_side_task")
        self.assertIsNone(stage["contract_position"])
        self.assertEqual(stage["contract_membership"], "UNEXPECTED")
        self.assertEqual(stage["evidence_state"], "RECORDED")
        self.assertEqual(stage["attempts"][0]["manifest_id"], record["manifest_id"])

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
        self.assertEqual(
            run["stage_evidence"],
            [
                {
                    "task_id": "custom_stage",
                    "contract_position": None,
                    "contract_membership": "UNKNOWN",
                    "evidence_state": "RECORDED",
                    "attempts": [
                        inspector._stage_attempt(
                            record,
                            {
                                "state": "NOT_CHECKED",
                                "integrity": "NOT_CHECKED",
                                "outbox_uri": None,
                                "event_sha256": None,
                                "receipt_uri": None,
                                "receipt_sha256": None,
                                "endpoint": None,
                                "http_status": None,
                                "delivered_at": None,
                                "error": None,
                            },
                        )
                    ],
                }
            ],
        )

    def test_one_run_id_cannot_mix_dag_identities(self):
        records = [
            sample_record(task_id="validate_inputs"),
            sample_record(task_id="validate_inputs", dag_id="ingest_pipeline_local"),
        ]

        with self.assertRaisesRegex(ValueError, "records from multiple DAGs"):
            inspector.build_view("interview-042", records)

    def test_one_run_id_rejects_conflicting_invariant_execution_facts(self):
        mutations = (
            ("object filenames", ("object", "filename"), "another.mp4"),
            ("Git repositories", ("execution", "git", "repository"), "https://example.test/other"),
            ("Git commits", ("execution", "git", "commit"), "f" * 40),
            (
                "Git identity statuses",
                ("execution", "parameters", "git_identity_status"),
                "VERIFIED_CLEAN_GIT_WORKTREE",
            ),
            ("DAG code paths", ("execution", "code", "path"), "/dags/other.py"),
            ("DAG code SHA-256 values", ("execution", "code", "sha256"), "f" * 64),
            (
                "DAG bundle SHA-256 values",
                ("execution", "parameters", "dag_code_bundle_sha256"),
                "f" * 64,
            ),
            ("orchestrator versions", ("orchestrator", "version"), "3.4.0"),
        )

        for label, path, value in mutations:
            with self.subTest(label=label):
                first = sample_record(task_id="validate_inputs")
                second = copy.deepcopy(
                    sample_record(task_id="transcode", recorded_at="2026-09-15T08:01:00Z")
                )
                target = second
                for segment in path[:-1]:
                    target = target[segment]
                target[path[-1]] = value

                with self.assertRaisesRegex(ValueError, f"conflicting {label}"):
                    inspector.build_view("interview-042", [first, second])

        first = sample_record(task_id="validate_inputs")
        second = copy.deepcopy(
            sample_record(task_id="transcode", recorded_at="2026-09-15T08:01:00Z")
        )
        second["execution"]["parameters"]["pachyderm_commit"] = "pach-2"
        for item in [*second["inputs"], *second["outputs"]]:
            item["version"]["pachyderm_commit"] = "pach-2"
        with self.assertRaisesRegex(ValueError, "conflicting Pachyderm commits"):
            inspector.build_view("interview-042", [first, second])

    def test_run_identity_marks_unknown_to_known_legacy_evidence_as_partial(self):
        complete = sample_record(task_id="validate_inputs")
        incomplete = copy.deepcopy(
            sample_record(task_id="transcode", recorded_at="2026-09-15T08:01:00Z")
        )
        incomplete["inputs"] = []
        incomplete["outputs"] = []
        incomplete["execution"]["git"]["commit"] = None
        incomplete["execution"]["code"]["sha256"] = None
        incomplete["execution"]["parameters"] = {}

        identity = inspector.build_view("interview-042", [complete, incomplete])["runs"][0][
            "run_identity"
        ]

        self.assertEqual(identity["consistency"], "VERIFIED")
        self.assertEqual(identity["completeness"], "PARTIAL")
        self.assertEqual(
            identity["missing_fields"],
            [
                "pachyderm_commit",
                "git.commit",
                "git.identity_status",
                "code.sha256",
                "code.bundle_sha256",
            ],
        )
        self.assertEqual(identity["pachyderm_commit"], "pachyderm-commit-42")
        self.assertEqual(identity["git"]["commit"], "b" * 40)
        self.assertEqual(identity["code"]["sha256"], "c" * 64)

    def test_artifact_ledger_rejects_competing_identities_for_one_uri(self):
        mutations = (
            ("kinds", ("kind",), "PREFIX"),
            ("SHA-256 values", ("sha256",), "f" * 64),
            ("sizes", ("size_bytes",), 99),
            ("s3_version_id values", ("version", "s3_version_id"), "version-99"),
            ("etag values", ("version", "etag"), "etag-99"),
        )

        for label, path, value in mutations:
            with self.subTest(label=label):
                first = sample_record(task_id="validate_inputs")
                second = copy.deepcopy(
                    sample_record(task_id="transcode", recorded_at="2026-09-15T08:01:00Z")
                )
                for item in [*second["inputs"], *second["outputs"]]:
                    target = item
                    for segment in path[:-1]:
                        target = target[segment]
                    target[path[-1]] = value

                with self.assertRaisesRegex(ValueError, f"conflicting {label}"):
                    inspector.build_view("interview-042", [first, second])

    def test_artifact_ledger_enriches_unknown_identity_without_inventing_conflict(self):
        unverified = copy.deepcopy(sample_record(task_id="validate_inputs"))
        for item in [*unverified["inputs"], *unverified["outputs"]]:
            item["sha256"] = None
            item["size_bytes"] = None
            item["media_type"] = None
            item["integrity"] = "UNVERIFIED"
            item["version"]["s3_version_id"] = None
            item["version"]["etag"] = None
        verified = sample_record(task_id="transcode", recorded_at="2026-09-15T08:01:00Z")

        artifact = inspector.build_view("interview-042", [unverified, verified])["runs"][0][
            "artifact_evidence"
        ][0]

        self.assertEqual(artifact["integrity"], "VERIFIED")
        self.assertEqual(artifact["sha256"], "a" * 64)
        self.assertEqual(artifact["size_bytes"], 42)
        self.assertEqual(artifact["media_types_observed"], ["video/mp4"])
        self.assertEqual(artifact["version"]["s3_version_id"], "version-42")
        self.assertEqual(artifact["version"]["etag"], "etag-42")

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
            parameters={
                "dag_code_bundle_sha256": "e" * 64,
                "git_identity_status": "VERIFIED_BUNDLE_ATTESTATION",
                "pipeline_task_contract": historical_contract,
            },
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
                parameters={
                    "dag_code_bundle_sha256": "e" * 64,
                    "git_identity_status": "VERIFIED_BUNDLE_ATTESTATION",
                    "pipeline_task_contract": contract,
                },
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
                return {"Body": io.BytesIO(provenance.canonical_json_bytes(objects[Key]))}

        with mock.patch.object(inspector, "_s3_client", return_value=Client()):
            records = inspector.read_records(object_id="interview-042", run_id="manual__run-42")

        self.assertEqual([record["run"]["task_id"] for record in records], ["validate_media", "transcode"])

    def test_s3_reader_binds_manifest_bytes_identity_and_link_to_the_object_key(self):
        record = sample_record()
        canonical_key = provenance.manifest_key(record)
        cases = (
            (
                "noncanonical bytes",
                canonical_key,
                json.dumps(record).encode(),
                "bytes are not canonical",
            ),
            (
                "misplaced identity",
                canonical_key.replace("validate_media", "different_task"),
                provenance.canonical_json_bytes(record),
                "identity does not match",
            ),
            (
                "false self-link",
                canonical_key,
                None,
                "link does not match",
            ),
        )
        for label, key, body, error in cases:
            with self.subTest(label=label):
                candidate = copy.deepcopy(record)
                if label == "false self-link":
                    candidate["links"]["manifest"] = "s3://pachyderm/provenance/elsewhere.json"
                    body = provenance.canonical_json_bytes(candidate)
                client = MemoryS3()
                client.objects[key] = body
                with (
                    mock.patch.object(inspector, "_s3_client", return_value=client),
                    self.assertRaisesRegex(ValueError, error),
                ):
                    inspector.read_records(object_id="interview-042")

    def test_stage_attempt_exposes_exact_manifest_and_lineage_evidence(self):
        record = sample_record()
        delivery = {
            "state": "DELIVERED",
            "integrity": "VERIFIED",
            "outbox_uri": "s3://pachyderm/openlineage/outbox/event.json",
            "event_sha256": "f" * 64,
            "receipt_uri": "s3://pachyderm/openlineage/delivered/event.json",
            "receipt_sha256": "e" * 64,
            "endpoint": "http://marquez:5000/api/v1/lineage",
            "http_status": 201,
            "delivered_at": "2026-09-15T08:00:01Z",
            "error": None,
        }

        attempt = inspector._stage_attempt(record, delivery)

        self.assertEqual(
            attempt["manifest_sha256"],
            hashlib.sha256(provenance.canonical_json_bytes(record)).hexdigest(),
        )
        self.assertEqual(attempt["manifest_uri"], record["links"]["manifest"])
        self.assertEqual(attempt["openlineage"], delivery)
        self.assertIsNot(attempt["openlineage"], delivery)

    def test_manifest_id_reuse_cannot_collapse_distinct_stage_evidence(self):
        first = sample_record()
        second = sample_record(
            task_id="transcode",
            status="FAILED",
            recorded_at="2026-09-15T08:01:00Z",
        )
        second["manifest_id"] = first["manifest_id"]
        client = MemoryS3()
        client.objects = {
            provenance.manifest_key(record): provenance.canonical_json_bytes(record)
            for record in (first, second)
        }

        with mock.patch.object(inspector, "_s3_client", return_value=client):
            with self.assertRaisesRegex(
                ValueError,
                "Manifest ID .* is reused by evidence identities",
            ):
                inspector.read_records(object_id="interview-042")

        for operation in (
            lambda: inspector.build_view("interview-042", [first, second]),
            lambda: inspector.read_openlineage_delivery_evidence(
                object_id="interview-042",
                records=[first, second],
            ),
        ):
            with self.subTest(operation=operation.__code__.co_firstlineno):
                with self.assertRaisesRegex(
                    ValueError,
                    "Manifest ID .* is reused by evidence identities",
                ):
                    operation()

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
        receipt_key = provenance.openlineage_event_key(delivered_event, "delivered")
        self.assertEqual(
            evidence["states"][delivered_record["manifest_id"]]["receipt_sha256"],
            hashlib.sha256(client.objects[receipt_key]).hexdigest(),
        )
        self.assertEqual(view["openlineage_delivery"]["state_counts"], {"DELIVERED": 1, "PENDING": 1})
        self.assertEqual(view["evidence_set"]["manifest_count"], 2)
        self.assertEqual(view["evidence_set"]["openlineage_event_count"], 2)
        self.assertEqual(view["evidence_set"]["delivery_receipt_count"], 1)
        reordered = inspector.build_view(
            "interview-042",
            [pending_record, delivered_record],
            evidence,
        )
        self.assertEqual(reordered["evidence_set"], view["evidence_set"])
        changed_delivery = copy.deepcopy(evidence)
        changed_delivery["states"][delivered_record["manifest_id"]][
            "delivered_at"
        ] = "2026-09-15T08:00:02Z"
        changed = inspector.build_view(
            "interview-042",
            [delivered_record, pending_record],
            changed_delivery,
        )
        self.assertNotEqual(
            changed["evidence_set"]["sha256"],
            view["evidence_set"]["sha256"],
        )
        stages = {stage["task_id"]: stage for stage in view["runs"][0]["stage_evidence"]}
        self.assertEqual(stages["validate_media"]["attempts"][0]["openlineage"]["state"], "DELIVERED")
        self.assertEqual(stages["transcode"]["attempts"][0]["openlineage"]["state"], "PENDING")
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

    def test_media_view_rejects_noncanonical_delivery_receipt_bytes(self):
        client = MemoryS3()
        record = sample_record()
        event = provenance.build_openlineage_event(record)
        outbox_uri = provenance.persist_openlineage_event(event, client=client)
        provenance.persist_openlineage_receipt(
            event,
            outbox_uri=outbox_uri,
            openlineage_target="http://marquez:5000/api/v1/lineage",
            http_status=201,
            client=client,
        )
        receipt_key = provenance.openlineage_event_key(event, "delivered")
        receipt = json.loads(client.objects[receipt_key])
        client.objects[receipt_key] = json.dumps(receipt).encode()

        with mock.patch.object(inspector, "_s3_client", return_value=client):
            evidence = inspector.read_openlineage_delivery_evidence(
                object_id="interview-042",
                records=[record],
            )

        state = evidence["states"][record["manifest_id"]]
        self.assertEqual(state["state"], "INTEGRITY_ERROR")
        self.assertEqual(
            state["receipt_sha256"],
            hashlib.sha256(client.objects[receipt_key]).hexdigest(),
        )
        self.assertIn("receipt bytes are not canonical", state["error"])

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
        self.assertEqual(orphaned_view["evidence_set"]["openlineage_event_count"], 0)
        self.assertEqual(orphaned_view["evidence_set"]["delivery_receipt_count"], 1)
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
            "receipt_sha256": None,
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
