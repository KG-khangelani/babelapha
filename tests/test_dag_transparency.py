from pathlib import Path
from types import SimpleNamespace
import re
import sys
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
DAGS_DIR = ROOT / "pipelines" / "airflow" / "dags"
sys.path.insert(0, str(DAGS_DIR))

from provenance import PIPELINE_TASK_CONTRACTS, required_upstream_task_ids

try:
    from airflow.dag_processing.dagbag import DagBag
except ModuleNotFoundError:  # Lightweight host runs may omit Airflow.
    DagBag = None


@unittest.skipIf(DagBag is None, "Airflow is not installed")
class DagTransparencyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bag = DagBag(dag_folder=str(DAGS_DIR), safe_mode=False)
        if cls.bag.import_errors:
            raise AssertionError(cls.bag.import_errors)

    def test_every_shipped_dag_ends_behind_the_provenance_gate(self):
        self.assertEqual(set(self.bag.dags), set(PIPELINE_TASK_CONTRACTS))
        for dag_id, contracted_tasks in PIPELINE_TASK_CONTRACTS.items():
            with self.subTest(dag_id=dag_id):
                dag = self.bag.dags[dag_id]
                gate = dag.task_dict["verify_provenance"]
                ancestors = {task.task_id for task in gate.get_flat_relatives(upstream=True)}
                self.assertEqual(ancestors, set(dag.task_ids) - {"verify_provenance"})
                self.assertEqual(gate.downstream_task_ids, set())
                self.assertEqual(set(dag.task_ids), set(contracted_tasks))
                self.assertEqual(required_upstream_task_ids(dag_id), list(contracted_tasks[:-1]))

    def test_every_shipped_task_emits_success_failure_and_retry_evidence(self):
        callbacks = {
            "on_success_callback": "provenance_success_callback",
            "on_failure_callback": "provenance_failure_callback",
            "on_retry_callback": "provenance_retry_callback",
        }
        for dag_id in PIPELINE_TASK_CONTRACTS:
            for task in self.bag.dags[dag_id].tasks:
                for attribute, expected_name in callbacks.items():
                    with self.subTest(dag=dag_id, task=task.task_id, callback=attribute):
                        configured = getattr(task, attribute)
                        self.assertEqual(
                            [callback.__name__ for callback in configured],
                            [expected_name],
                        )

    def test_v2_rejects_missing_identity_and_marks_source_unverified(self):
        validate = self.bag.dags["ingest_pipeline_v2"].task_dict["validate_inputs"].python_callable
        with mock.patch.dict(
            validate.__globals__,
            {"get_current_context": lambda: {"dag_run": SimpleNamespace(conf={})}},
        ):
            with self.assertRaisesRegex(ValueError, "Missing required parameters"):
                validate()

        context = {
            "dag_run": SimpleNamespace(
                conf={"id": "  item-17 ", "filename": " clip.mp4 ", "pachyderm_commit": "pach-42"}
            )
        }
        with mock.patch.dict(validate.__globals__, {"get_current_context": lambda: context}):
            payload = validate()
        self.assertEqual(payload["object_id"], "item-17")
        self.assertEqual(payload["filename"], "clip.mp4")
        self.assertEqual(payload["provenance_outputs"], [])
        self.assertEqual(payload["provenance_decision"]["reason_code"], "DIAGNOSTIC_PARAMETERS_ACCEPTED")
        source = payload["provenance_inputs"][0]
        self.assertEqual(source["integrity"], "UNVERIFIED")
        self.assertIsNone(source["sha256"])
        self.assertEqual(source["version"]["pachyderm_commit"], "pach-42")

    def test_production_dag_refuses_mutable_processing_images(self):
        validate = self.bag.dags["ingest_pipeline"].task_dict["validate_inputs"].python_callable
        context = {
            "dag_run": SimpleNamespace(
                conf={"id": "item-17", "filename": "clip.mp4", "pachyderm_commit": "pach-42"}
            )
        }
        base_globals = {
            "get_current_context": lambda: context,
            "MINIO_ACCESS_KEY": "access",
            "MINIO_SECRET_KEY": "secret",
        }
        with mock.patch.dict(
            validate.__globals__,
            {
                **base_globals,
                "SCAN_IMAGE": "registry/scan:latest",
                "VALIDATE_IMAGE": "registry/validate@sha256:" + "a" * 64,
                "TRANSCODE_IMAGE": "registry/transcode@sha256:" + "b" * 64,
            },
        ):
            with self.assertRaisesRegex(RuntimeError, "BABELAPHA_SCAN_IMAGE"):
                validate()

        with mock.patch.dict(
            validate.__globals__,
            {
                **base_globals,
                "SCAN_IMAGE": "registry/scan@sha256:" + "c" * 64,
                "VALIDATE_IMAGE": "registry/validate@sha256:" + "a" * 64,
                "TRANSCODE_IMAGE": "registry/transcode@sha256:" + "b" * 64,
            },
        ):
            payload = validate()
        self.assertEqual(payload["object_id"], "item-17")
        self.assertEqual(payload["pachyderm_commit"], "pach-42")

    def test_v2_gate_validates_every_exact_upstream_pair(self):
        dag = self.bag.dags["ingest_pipeline_v2"]
        gate = dag.task_dict["verify_provenance"].python_callable
        expected_tasks = required_upstream_task_ids("ingest_pipeline_v2")
        call = {}

        def validate_pairs(**kwargs):
            call.update(kwargs)
            return [f"manifest-{number}" for number in range(len(expected_tasks))]

        with mock.patch.dict(
            gate.__globals__,
            {
                "get_current_context": lambda: {"dag_run": SimpleNamespace(run_id="manual__diagnostic")},
                "assert_success_manifests": validate_pairs,
            },
        ):
            result = gate({"object_id": "item-17", "filename": "clip.mp4"})

        self.assertEqual(call["object_id"], "item-17")
        self.assertEqual(call["run_id"], "manual__diagnostic")
        self.assertEqual(call["task_ids"], expected_tasks)
        self.assertEqual(result["provenance_outputs"], [])
        self.assertEqual(
            result["provenance_decision"]["message"],
            "Verified 11 immutable manifest/OpenLineage pairs.",
        )

    def test_v2_pods_return_own_honest_payload_from_a_pinned_image(self):
        dag = self.bag.dags["ingest_pipeline_v2"]
        for task_id in ("run_virus_scan", "run_media_validation", "run_transcode"):
            task = dag.task_dict[task_id]
            with self.subTest(task=task_id):
                self.assertRegex(task.image, re.compile(r"@sha256:[0-9a-f]{64}$"))
                self.assertTrue(task.do_xcom_push)
                script = task.arguments[0]
                compile(script, f"{task_id}-diagnostic.py", "exec")
                self.assertIn('"outcome": "diagnostic_only"', script)
                self.assertIn('"provenance_outputs": []', script)
                self.assertNotIn("No threats detected", script)
                self.assertNotIn("Format OK", script)
                self.assertNotIn("HLS+DASH generated", script)


if __name__ == "__main__":
    unittest.main()
