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


def sample_record(*, task_id="validate_media", status="SUCCEEDED", recorded_at="2026-09-15T08:00:00Z"):
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
        dag_id="ingest_pipeline",
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
        airflow_version="3.3.1",
    )


class ProvenanceInspectorTests(unittest.TestCase):
    def test_text_view_exposes_required_milestone_evidence(self):
        records = [
            sample_record(),
            sample_record(task_id="transcode", status="FAILED", recorded_at="2026-09-15T08:01:00Z"),
        ]
        rendered = inspector.render_text(inspector.build_view("interview-042", records))

        for expected in (
            "Run: manual__run-42",
            "[FAILED] stage=transcode task=transcode attempt=1",
            "decision=TASK_FAILED",
            "sha256=" + "a" * 64,
            "pachyderm_commit=pachyderm-commit-42",
            "s3_version=version-42",
            "git=https://github.com/KG-khangelani/babelapha@" + "b" * 40,
            "code=/opt/airflow/dags/ingest_pipeline.py sha256=" + "c" * 64,
            "container=registry/validate digest=sha256:" + "d" * 64,
        ):
            self.assertIn(expected, rendered)

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


if __name__ == "__main__":
    unittest.main()
