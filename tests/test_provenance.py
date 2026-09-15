import copy
from datetime import datetime, timezone
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

try:
    import jsonschema
except ModuleNotFoundError:  # The Airflow validation image always provides it.
    jsonschema = None


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "pipelines" / "airflow" / "dags" / "provenance.py"
SPEC = importlib.util.spec_from_file_location("babelapha_provenance", MODULE_PATH)
provenance = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(provenance)


class PreconditionFailed(Exception):
    response = {
        "Error": {"Code": "PreconditionFailed"},
        "ResponseMetadata": {"HTTPStatusCode": 412},
    }


class MemoryS3:
    def __init__(self):
        self.objects = {}
        self.puts = []

    def put_object(self, **kwargs):
        self.puts.append(kwargs)
        key = kwargs["Key"]
        if key in self.objects:
            raise PreconditionFailed()
        self.objects[key] = kwargs["Body"]

    def get_object(self, *, Key, **_kwargs):
        return {"Body": io.BytesIO(self.objects[Key])}


class ProvenanceContractTests(unittest.TestCase):
    def sample_manifest(self, **overrides):
        values = {
            "object_id": "interview-042",
            "filename": "interview.mp4",
            "run_id": "manual__2026-09-15T08:00:00+00:00",
            "dag_id": "ingest_pipeline_local",
            "task_id": "transcode",
            "stage": "transcoded",
            "attempt": 1,
            "status": "SUCCEEDED",
            "decision": {
                "outcome": "accepted",
                "reason_code": "HLS_AND_DASH_CREATED",
                "message": "HLS and DASH renditions were created.",
            },
            "container_image": "example/transcode:1.0",
            "container_digest": "sha256:" + "a" * 64,
            "git_commit": "0123456789abcdef0123456789abcdef01234567",
        }
        values.update(overrides)
        return provenance.build_manifest(**values)

    def test_manifest_is_versioned_and_append_only_key_contains_attempt(self):
        record = self.sample_manifest()
        self.assertEqual(record["schema_version"], "1.0.0")
        self.assertEqual(
            provenance.manifest_key(record),
            "provenance/interview-042/manual__2026-09-15T08%3A00%3A00%2B00%3A00/transcode/1-succeeded.json",
        )
        self.assertEqual(record["execution"]["container"]["identity_status"], "VERIFIED_DIGEST")

    def test_file_artifact_has_exact_sha256_and_size(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "interview.mp4"
            path.write_bytes(b"babelapha")
            item = provenance.artifact_from_file(path, uri="s3://pachyderm/incoming/test.mp4")
        self.assertEqual(item["sha256"], "145ee26773a9328246dc4acb01b3ee2be2f7a2468ee86a9c8cbaa8037925bb20")
        self.assertEqual(item["size_bytes"], 9)
        self.assertEqual(item["integrity"], "VERIFIED")

    def test_unknown_digest_is_never_claimed_as_verified(self):
        record = self.sample_manifest(container_digest=None)
        self.assertIsNone(record["execution"]["container"]["digest"])
        self.assertEqual(record["execution"]["container"]["identity_status"], "CONFIGURED_REF_ONLY")

    def test_pipeline_media_types_override_ambiguous_platform_defaults(self):
        self.assertEqual(provenance.artifact("s3://pachyderm/output/video.ts")["media_type"], "video/mp2t")
        self.assertEqual(
            provenance.artifact("s3://pachyderm/output/video.ts", media_type="text/plain")["media_type"],
            "video/mp2t",
        )
        self.assertEqual(
            provenance.artifact("s3://pachyderm/output/manifest.mpd")["media_type"],
            "application/dash+xml",
        )

    def test_short_or_symbolic_git_refs_are_not_accepted_as_exact_commits(self):
        with self.assertRaises(provenance.ManifestValidationError):
            self.sample_manifest(git_commit="local-working-tree")

    def test_deployed_git_identity_file_preserves_exact_synced_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            identity_file = Path(directory) / ".babelapha-git-sha"
            identity_file.write_text("A" * 40 + "\n", encoding="utf-8")
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertEqual(provenance._git_commit(identity_file), "a" * 40)

    def test_persistence_is_atomically_append_only_and_idempotent(self):
        class FakeS3:
            def __init__(self):
                self.body = None
                self.last_put = None

            def put_object(self, **kwargs):
                self.last_put = kwargs
                if self.body is not None:
                    raise PreconditionFailed()
                self.body = kwargs["Body"]

            def get_object(self, **_kwargs):
                return {"Body": io.BytesIO(self.body)}

        client = FakeS3()
        record = self.sample_manifest()
        with mock.patch.object(provenance, "_s3_client", return_value=client):
            first = provenance.persist_manifest(record)
            self.assertEqual(first, provenance.persist_manifest(record))
            conflict = copy.deepcopy(record)
            conflict["decision"]["message"] = "different bytes"
            with self.assertRaises(FileExistsError):
                provenance.persist_manifest(conflict)
        self.assertEqual(client.last_put["IfNoneMatch"], "*")

    def test_failed_stage_uses_upstream_evidence_without_claiming_outputs(self):
        source = provenance.artifact(
            "s3://pachyderm/incoming/interview-042/interview.mp4",
            sha256="c" * 64,
            size_bytes=42,
            pachyderm_commit="pachyderm-commit-42",
        )
        upstream = {
            "object_id": "interview-042",
            "filename": "interview.mp4",
            "provenance_stage": "uploaded",
            "provenance_inputs": [source],
            "provenance_outputs": [source],
        }

        class TaskInstance:
            task_id = "virus_scan"
            dag_id = "ingest_pipeline"
            try_number = 2
            start_date = datetime(2026, 9, 15, tzinfo=timezone.utc)
            end_date = datetime(2026, 9, 15, 0, 0, 1, tzinfo=timezone.utc)
            log_url = "http://airflow.example/log"

            @staticmethod
            def xcom_pull(task_ids):
                return upstream if task_ids == "inspect_source" else None

        context = {
            "task_instance": TaskInstance(),
            "task": SimpleNamespace(task_id="virus_scan", dag_id="ingest_pipeline", image="scan@sha256:" + "d" * 64),
            "dag_run": SimpleNamespace(
                run_id="manual__failure",
                conf={"id": "interview-042", "filename": "interview.mp4"},
            ),
            "exception": RuntimeError("malware detected"),
        }
        with mock.patch.dict("os.environ", {"BABELAPHA_GIT_SHA": "e" * 40}, clear=False):
            record = provenance.build_airflow_manifest(context, "FAILED")

        self.assertEqual(record["run"]["stage"], "virus_scan")
        self.assertEqual(record["run"]["attempt"], 2)
        self.assertEqual(record["inputs"], [source])
        self.assertEqual(record["outputs"], [])
        self.assertEqual(record["decision"]["reason_code"], "TASK_FAILED")

    def test_openlineage_event_reuses_manifest_identity_and_artifacts(self):
        item = provenance.artifact(
            "s3://pachyderm/output/interview-042/hls/playlist.m3u8",
            sha256="b" * 64,
            size_bytes=12,
            media_type="application/vnd.apple.mpegurl",
            pachyderm_commit="pach-42",
            s3_version_id="version-42",
            etag="etag-42",
        )
        record = self.sample_manifest(
            inputs=[item],
            outputs=[item],
            code_path="/opt/airflow/dags/ingest_pipeline.py",
            code_sha256="c" * 64,
            airflow_version="3.3.1",
            airflow_log_url="https://airflow.example/log/42",
        )
        event = provenance.build_openlineage_event(record)
        execution_facet = event["run"]["facets"]["babelapha_execution"]
        artifact_facet = event["outputs"][0]["outputFacets"]["babelapha_artifact"]
        input_artifact_facet = event["inputs"][0]["inputFacets"]["babelapha_artifact"]
        self.assertEqual(event["run"]["runId"], record["manifest_id"])
        expected_execution = {
            "schemaVersion": record["schema_version"],
            "manifestId": record["manifest_id"],
            "manifestUri": record["links"]["manifest"],
            "recordedAt": record["recorded_at"],
            "objectId": record["object"]["id"],
            "objectFilename": record["object"]["filename"],
            "airflowRunId": record["run"]["id"],
            "dagId": record["run"]["dag_id"],
            "taskId": record["run"]["task_id"],
            "stage": record["run"]["stage"],
            "attempt": record["run"]["attempt"],
            "status": record["run"]["status"],
            "startedAt": record["run"]["started_at"],
            "completedAt": record["run"]["completed_at"],
            "durationMs": record["run"]["duration_ms"],
            "decisionOutcome": record["decision"]["outcome"],
            "decisionReasonCode": record["decision"]["reason_code"],
            "decisionMessage": record["decision"]["message"],
            "gitRepository": record["execution"]["git"]["repository"],
            "gitCommit": record["execution"]["git"]["commit"],
            "codePath": record["execution"]["code"]["path"],
            "codeSha256": record["execution"]["code"]["sha256"],
            "containerImage": record["execution"]["container"]["image"],
            "containerDigest": record["execution"]["container"]["digest"],
            "containerIdentityStatus": record["execution"]["container"]["identity_status"],
            "parameters": record["execution"]["parameters"],
            "orchestratorName": record["orchestrator"]["name"],
            "orchestratorVersion": record["orchestrator"]["version"],
            "airflowLogUrl": record["links"]["airflow_log"],
        }
        for field, expected in expected_execution.items():
            self.assertEqual(execution_facet[field], expected, field)

        expected_artifact = {
            "uri": item["uri"],
            "kind": item["kind"],
            "sha256": item["sha256"],
            "sizeBytes": item["size_bytes"],
            "mediaType": item["media_type"],
            "integrity": item["integrity"],
            "pachydermCommit": item["version"]["pachyderm_commit"],
            "s3VersionId": item["version"]["s3_version_id"],
            "etag": item["version"]["etag"],
        }
        for field, expected in expected_artifact.items():
            self.assertEqual(artifact_facet[field], expected, field)
            self.assertEqual(input_artifact_facet[field], expected, field)
        self.assertEqual(event["outputs"][0]["namespace"], "s3://pachyderm")
        self.assertIn(provenance.CONTRACTS_COMMIT, execution_facet["_schemaURL"])
        self.assertIn(provenance.CONTRACTS_COMMIT, artifact_facet["_schemaURL"])
        self.assertNotIn("/main/", record["$schema"])

    def test_openlineage_event_types_preserve_each_terminal_and_attempt_state(self):
        cases = {
            "SUCCEEDED": ("COMPLETE", "accepted", "STAGE_COMPLETED"),
            "FAILED": ("FAIL", "failed", "TASK_FAILED"),
            "RETRYING": ("FAIL", "retrying", "TASK_RETRYING"),
            "SKIPPED": ("ABORT", "skipped", "TASK_SKIPPED"),
        }
        for status, (event_type, outcome, reason_code) in cases.items():
            with self.subTest(status=status):
                record = self.sample_manifest(
                    status=status,
                    attempt=3,
                    decision={
                        "outcome": outcome,
                        "reason_code": reason_code,
                        "message": f"Task is {status.lower()}.",
                    },
                )
                event = provenance.build_openlineage_event(record)
                execution_facet = event["run"]["facets"]["babelapha_execution"]
                self.assertEqual(event["eventType"], event_type)
                self.assertEqual(execution_facet["status"], status)
                self.assertEqual(execution_facet["attempt"], 3)
                self.assertEqual(execution_facet["decisionOutcome"], outcome)
                self.assertEqual(execution_facet["decisionReasonCode"], reason_code)

    def test_openlineage_outbox_preserves_exact_event_bytes_and_rejects_conflicts(self):
        client = MemoryS3()
        record = self.sample_manifest()
        event = provenance.build_openlineage_event(record)
        location = provenance.persist_openlineage_outbox(record, client=client)
        key = provenance.openlineage_event_key(event, "outbox")

        self.assertEqual(location, f"s3://pachyderm/{key}")
        self.assertEqual(client.objects[key], provenance.canonical_json_bytes(event))
        self.assertEqual(
            client.puts[0]["Metadata"]["event-sha256"],
            hashlib.sha256(provenance.canonical_json_bytes(event)).hexdigest(),
        )
        self.assertEqual(location, provenance.persist_openlineage_event(event, client=client))

        conflicting = copy.deepcopy(event)
        conflicting["run"]["facets"]["babelapha_execution"]["decisionMessage"] = "different bytes"
        with self.assertRaises(FileExistsError):
            provenance.persist_openlineage_event(conflicting, client=client)

    def test_openlineage_delivery_receipt_is_schema_pinned_and_idempotent(self):
        client = MemoryS3()
        event = provenance.build_openlineage_event(self.sample_manifest())
        outbox_uri = provenance.persist_openlineage_event(event, client=client)
        target = "http://marquez:5000/api/v1/lineage"
        with mock.patch.object(
            provenance,
            "utc_iso",
            side_effect=("2026-09-15T09:00:00Z", "2026-09-15T09:01:00Z"),
        ):
            first = provenance.persist_openlineage_receipt(
                event,
                outbox_uri=outbox_uri,
                openlineage_target=target,
                http_status=201,
                client=client,
            )
            second = provenance.persist_openlineage_receipt(
                event,
                outbox_uri=outbox_uri,
                openlineage_target=target,
                http_status=201,
                client=client,
            )

        self.assertEqual(first, second)
        receipt_key = provenance.openlineage_event_key(event, "delivered")
        receipt = json.loads(client.objects[receipt_key])
        provenance.validate_openlineage_receipt(receipt, event, outbox_uri=outbox_uri)
        self.assertIn(provenance.DELIVERY_CONTRACTS_COMMIT, receipt["$schema"])
        self.assertEqual(receipt["delivered_at"], "2026-09-15T09:00:00Z")

    def test_airflow_callback_leaves_queued_event_pending_after_delivery_error(self):
        record = self.sample_manifest()
        output = io.StringIO()
        with (
            mock.patch.object(provenance, "build_airflow_manifest", return_value=record),
            mock.patch.object(provenance, "persist_manifest", return_value=record["links"]["manifest"]),
            mock.patch.object(
                provenance,
                "persist_openlineage_event",
                return_value="s3://pachyderm/openlineage/outbox/queued.json",
            ) as persist_event,
            mock.patch.object(
                provenance,
                "_openlineage_target",
                return_value="http://marquez:5000/api/v1/lineage",
            ),
            mock.patch.object(provenance, "emit_openlineage_event", side_effect=OSError("offline")),
            mock.patch("sys.stdout", output),
        ):
            provenance.emit_airflow_manifest({}, "FAILED")

        persist_event.assert_called_once()
        self.assertIn("Queued immutable OpenLineage event", output.getvalue())
        self.assertIn("pending after delivery error: OSError: offline", output.getvalue())

    def test_airflow_callback_receipts_successful_delivery_of_the_queued_event(self):
        record = self.sample_manifest()
        outbox_uri = "s3://pachyderm/openlineage/outbox/queued.json"
        target = "http://marquez:5000/api/v1/lineage"
        with (
            mock.patch.object(provenance, "build_airflow_manifest", return_value=record),
            mock.patch.object(provenance, "persist_manifest", return_value=record["links"]["manifest"]),
            mock.patch.object(provenance, "persist_openlineage_event", return_value=outbox_uri),
            mock.patch.object(provenance, "_openlineage_target", return_value=target),
            mock.patch.object(provenance, "emit_openlineage_event", return_value=201) as emit,
            mock.patch.object(
                provenance,
                "persist_openlineage_receipt",
                return_value="s3://pachyderm/openlineage/delivered/receipt.json",
            ) as persist_receipt,
            mock.patch("sys.stdout", io.StringIO()),
        ):
            provenance.emit_airflow_manifest({}, "SUCCEEDED")

        queued_event = emit.call_args.args[0]
        persist_receipt.assert_called_once_with(
            queued_event,
            outbox_uri=outbox_uri,
            openlineage_target=target,
            http_status=201,
        )

    def test_openlineage_skip_is_reported_instead_of_claimed_as_emitted(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(provenance.emit_openlineage(self.sample_manifest()))

    def test_contract_schema_is_valid_json_and_matches_runtime_version(self):
        schema = json.loads((ROOT / "contracts" / "provenance-manifest-v1.schema.json").read_text())
        self.assertEqual(schema["properties"]["schema_version"]["const"], provenance.SCHEMA_VERSION)

    @unittest.skipIf(jsonschema is None, "jsonschema is not installed in the lightweight host environment")
    def test_generated_manifest_conforms_to_published_json_schema(self):
        schema = json.loads((ROOT / "contracts" / "provenance-manifest-v1.schema.json").read_text())
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        validator.validate(self.sample_manifest())

    @unittest.skipIf(jsonschema is None, "jsonschema is not installed in the lightweight host environment")
    def test_openlineage_custom_facet_conforms_to_its_json_schema(self):
        schema = json.loads(
            (ROOT / "contracts" / "openlineage-babelapha-execution-run-facet-v2.schema.json").read_text()
        )
        item = provenance.artifact(
            "s3://pachyderm/output/interview-042/playlist.m3u8",
            sha256="f" * 64,
            size_bytes=12,
        )
        event = provenance.build_openlineage_event(self.sample_manifest(outputs=[item]))
        facet = event["run"]["facets"]["babelapha_execution"]
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        validator.validate(facet)

        artifact_schema = json.loads(
            (ROOT / "contracts" / "openlineage-babelapha-artifact-dataset-facet-v1.schema.json").read_text()
        )
        artifact_validator = jsonschema.Draft202012Validator(
            artifact_schema,
            format_checker=jsonschema.FormatChecker(),
        )
        artifact_validator.validate(event["outputs"][0]["outputFacets"]["babelapha_artifact"])

        delivery_schema = json.loads(
            (ROOT / "contracts" / "openlineage-delivery-receipt-v1.schema.json").read_text()
        )
        client = MemoryS3()
        outbox_uri = provenance.persist_openlineage_event(event, client=client)
        provenance.persist_openlineage_receipt(
            event,
            outbox_uri=outbox_uri,
            openlineage_target="http://marquez:5000/api/v1/lineage",
            http_status=201,
            client=client,
        )
        receipt = json.loads(client.objects[provenance.openlineage_event_key(event, "delivered")])
        jsonschema.Draft202012Validator(
            delivery_schema,
            format_checker=jsonschema.FormatChecker(),
        ).validate(receipt)


if __name__ == "__main__":
    unittest.main()
