import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "pipelines" / "airflow" / "replay_openlineage.py"
SPEC = importlib.util.spec_from_file_location("babelapha_openlineage_replay", MODULE_PATH)
replay = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(replay)
provenance = replay.sys.modules["provenance"]


class PreconditionFailed(Exception):
    response = {
        "Error": {"Code": "PreconditionFailed"},
        "ResponseMetadata": {"HTTPStatusCode": 412},
    }


class MemoryS3:
    def __init__(self):
        self.objects = {}

    def put_object(self, **kwargs):
        key = kwargs["Key"]
        if key in self.objects:
            raise PreconditionFailed()
        self.objects[key] = kwargs["Body"]

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


def sample_event(*, run_id: str, task_id: str) -> dict:
    item = provenance.artifact(
        f"s3://pachyderm/incoming/media-42/{run_id}.mp4",
        sha256="a" * 64,
        size_bytes=42,
        pachyderm_commit=f"pach-{run_id}",
        s3_version_id=f"version-{run_id}",
    )
    record = provenance.build_manifest(
        object_id="media-42",
        filename="media.mp4",
        run_id=run_id,
        dag_id="ingest_pipeline",
        task_id=task_id,
        stage=task_id,
        attempt=1,
        status="SUCCEEDED",
        decision={
            "outcome": "accepted",
            "reason_code": "STAGE_COMPLETED",
            "message": "Stage completed.",
        },
        inputs=[item],
        outputs=[item],
        git_commit="b" * 40,
        container_image="registry/runtime",
        container_digest="sha256:" + "c" * 64,
    )
    return provenance.build_openlineage_event(record)


class OpenLineageReplayTests(unittest.TestCase):
    def test_replay_skips_valid_receipt_and_delivers_only_pending_event(self):
        client = MemoryS3()
        delivered = sample_event(run_id="run-delivered", task_id="inspect_source")
        pending = sample_event(run_id="run-pending", task_id="validate_media")
        delivered_outbox = provenance.persist_openlineage_event(delivered, client=client)
        provenance.persist_openlineage_event(pending, client=client)
        provenance.persist_openlineage_receipt(
            delivered,
            outbox_uri=delivered_outbox,
            openlineage_target="http://marquez:5000/api/v1/lineage",
            http_status=201,
            client=client,
        )

        with mock.patch.object(replay, "emit_openlineage_event", return_value=201) as emit:
            result = replay.replay_pending(
                client=client,
                bucket="pachyderm",
                object_id="media-42",
                openlineage_url="http://marquez:5000",
            )

        self.assertEqual(result["queued_selected"], 2)
        self.assertEqual(result["already_delivered"], 1)
        self.assertEqual(result["pending_found"], 1)
        self.assertEqual(result["pending_remaining"], 0)
        self.assertEqual(result["replayed"], 1)
        self.assertEqual(result["failed"], 0)
        emit.assert_called_once()
        self.assertEqual(emit.call_args.args[0], pending)
        receipt_key = provenance.openlineage_event_key(pending, "delivered")
        self.assertIn(receipt_key, client.objects)

    def test_dry_run_reports_pending_event_without_delivery_or_receipt(self):
        client = MemoryS3()
        event = sample_event(run_id="run-dry", task_id="virus_scan")
        provenance.persist_openlineage_event(event, client=client)

        with mock.patch.object(replay, "emit_openlineage_event") as emit:
            result = replay.replay_pending(
                client=client,
                bucket="pachyderm",
                object_id="media-42",
                dry_run=True,
            )

        self.assertEqual(result["pending_found"], 1)
        self.assertEqual(result["pending_remaining"], 1)
        self.assertEqual(result["events"][0]["action"], "would_replay")
        self.assertNotIn(provenance.openlineage_event_key(event, "delivered"), client.objects)
        emit.assert_not_called()

    def test_invalid_existing_receipt_is_not_treated_as_delivered(self):
        client = MemoryS3()
        event = sample_event(run_id="run-invalid", task_id="transcode")
        provenance.persist_openlineage_event(event, client=client)
        receipt_key = provenance.openlineage_event_key(event, "delivered")
        client.objects[receipt_key] = json.dumps({"manifest_id": "wrong"}).encode()

        result = replay.replay_pending(
            client=client,
            bucket="pachyderm",
            object_id="media-42",
            dry_run=True,
        )

        self.assertEqual(result["already_delivered"], 0)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["events"][0]["action"], "invalid_receipt")


if __name__ == "__main__":
    unittest.main()
