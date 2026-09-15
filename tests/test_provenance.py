import copy
from datetime import datetime, timezone
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
        class PreconditionFailed(Exception):
            response = {
                "Error": {"Code": "PreconditionFailed"},
                "ResponseMetadata": {"HTTPStatusCode": 412},
            }

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
        )
        record = self.sample_manifest(outputs=[item])
        event = provenance.build_openlineage_event(record)
        self.assertEqual(event["run"]["runId"], record["manifest_id"])
        self.assertEqual(
            event["run"]["facets"]["babelapha_execution"]["manifestUri"],
            record["links"]["manifest"],
        )
        self.assertEqual(event["outputs"][0]["namespace"], "s3://pachyderm")

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
            (ROOT / "contracts" / "openlineage-babelapha-execution-run-facet-v1.schema.json").read_text()
        )
        facet = provenance.build_openlineage_event(self.sample_manifest())["run"]["facets"][
            "babelapha_execution"
        ]
        validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
        validator.validate(facet)


if __name__ == "__main__":
    unittest.main()
