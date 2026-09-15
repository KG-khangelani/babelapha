from pathlib import Path
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
AIRFLOW_DIR = ROOT / "pipelines" / "airflow"
sys.path.insert(0, str(AIRFLOW_DIR))

import webhook_listener_airflow3
import webhook_payload


class WebhookPayloadContractTests(unittest.TestCase):
    def test_nested_path_and_commit_are_preserved_exactly(self):
        conf = webhook_payload.build_dag_conf(
            {
                "action": "put_file",
                "path": "/incoming/interview-42/source/camera-a.mp4",
                "commit": {"branch": {"name": "master"}, "id": "a1b2c3d4"},
            }
        )
        self.assertEqual(
            conf,
            {
                "id": "interview-42",
                "filename": "source/camera-a.mp4",
                "pachyderm_commit": "a1b2c3d4",
            },
        )

    def test_supported_flat_and_protobuf_commit_shapes(self):
        base = {"id": "interview-42", "filename": "source.mp4"}
        shapes = (
            {"pachyderm_commit": "commit-1"},
            {"commit_id": "commit-1"},
            {"commitId": "commit-1"},
            {"commit": "commit-1"},
            {"commit_info": {"commit": {"id": "commit-1"}}},
        )
        for shape in shapes:
            with self.subTest(shape=shape):
                self.assertEqual(
                    webhook_payload.build_dag_conf({**base, **shape})["pachyderm_commit"],
                    "commit-1",
                )

    def test_missing_commit_and_unsafe_identity_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact Pachyderm commit"):
            webhook_payload.build_dag_conf({"id": "interview-42", "filename": "source.mp4"})
        with self.assertRaisesRegex(ValueError, "unsafe"):
            webhook_payload.build_dag_conf(
                {"id": "../interview-42", "filename": "source.mp4", "commit_id": "commit-1"}
            )
        with self.assertRaisesRegex(ValueError, "unsafe"):
            webhook_payload.build_dag_conf(
                {"id": "interview-42", "filename": "../source.mp4", "commit_id": "commit-1"}
            )
        with self.assertRaisesRegex(ValueError, "unsupported characters"):
            webhook_payload.build_dag_conf(
                {"id": "interview-42", "filename": "source.mp4", "commit_id": "commit 1"}
            )

    def test_conflicting_identity_facts_and_non_put_actions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "conflicting Pachyderm commit"):
            webhook_payload.build_dag_conf(
                {
                    "path": "/incoming/interview-42/source.mp4",
                    "commit_id": "commit-1",
                    "commit": {"id": "commit-2"},
                }
            )
        with self.assertRaisesRegex(ValueError, "conflicting object IDs"):
            webhook_payload.build_dag_conf(
                {
                    "id": "interview-99",
                    "filename": "source.mp4",
                    "path": "/incoming/interview-42/source.mp4",
                    "commit_id": "commit-1",
                }
            )
        with self.assertRaisesRegex(ValueError, "Unsupported Pachyderm action"):
            webhook_payload.build_dag_conf(
                {
                    "action": "delete_file",
                    "path": "/incoming/interview-42/source.mp4",
                    "commit_id": "commit-1",
                }
            )

    def test_deterministic_run_id_is_per_commit_and_object(self):
        conf = {"id": "interview-42", "filename": "source.mp4", "pachyderm_commit": "commit-1"}
        run_id = webhook_payload.dag_run_id(conf)
        self.assertEqual(run_id, webhook_payload.dag_run_id(conf))
        self.assertTrue(run_id.startswith("pachyderm__commit-1__"))
        self.assertNotEqual(
            run_id,
            webhook_payload.dag_run_id({**conf, "filename": "other.mp4"}),
        )

    def test_airflow3_trigger_passes_commit_and_deterministic_run_id(self):
        calls = []

        def post_json(url, payload, headers=None):
            calls.append((url, payload, headers))
            return {"access_token": "test-token"} if len(calls) == 1 else {"dag_run_id": payload["dag_run_id"]}

        event = {
            "action": "put_file",
            "path": "/incoming/interview-42/source.mp4",
            "commit": {"id": "commit-1"},
        }
        with mock.patch.object(webhook_listener_airflow3, "post_json", side_effect=post_json):
            response = webhook_listener_airflow3.trigger_dag(event)

        request = calls[1][1]
        self.assertEqual(request["conf"]["pachyderm_commit"], "commit-1")
        self.assertEqual(request["dag_run_id"], webhook_payload.dag_run_id(request["conf"]))
        self.assertEqual(response["dag_run_id"], request["dag_run_id"])

    def test_airflow3_duplicate_delivery_reuses_the_same_run(self):
        expected_conf = webhook_payload.build_dag_conf(
            {"path": "/incoming/interview-42/source.mp4", "commit": {"id": "commit-1"}}
        )
        expected_run_id = webhook_payload.dag_run_id(expected_conf)
        calls = 0

        def post_json(_url, _payload, _headers=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"access_token": "test-token"}
            raise webhook_listener_airflow3.AirflowAPIError(409, "already exists")

        with mock.patch.object(webhook_listener_airflow3, "post_json", side_effect=post_json):
            response = webhook_listener_airflow3.trigger_dag(
                {"path": "/incoming/interview-42/source.mp4", "commit": {"id": "commit-1"}}
            )
        self.assertEqual(response, {"dag_run_id": expected_run_id, "duplicate": True})


if __name__ == "__main__":
    unittest.main()
