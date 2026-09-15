import copy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

try:
    import jsonschema
except ModuleNotFoundError:
    jsonschema = None


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "pipelines" / "airflow"
MODULE_PATH = API_DIR / "provenance_api.py"
sys.path.insert(0, str(API_DIR))
SPEC = importlib.util.spec_from_file_location("babelapha_provenance_api", MODULE_PATH)
api = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(api)
inspector = sys.modules["inspect_provenance"]
provenance = sys.modules["provenance"]


AVAILABLE_SUMMARY = {
    "read_state": "AVAILABLE",
    "object_filenames": ["interview.mp4"],
    "run_count": 1,
    "record_count": 2,
    "latest_recorded_at": "2026-09-15T10:00:00Z",
    "statuses_observed": ["FAILED", "RETRYING"],
    "run_identity_completeness": "COMPLETE",
    "artifact_node_count": 3,
    "openlineage_state_counts": {"DELIVERED": 2},
    "error": None,
}


class ProvenanceAPITests(unittest.TestCase):
    def test_openapi_contract_is_versioned_read_only_and_matches_routes(self):
        contract = api.read_openapi_contract()
        expected_paths = {
            "/health",
            "/ready",
            "/api/v1/openapi.json",
            "/api/v1/media",
            "/api/v1/media/{object_id}",
        }

        self.assertEqual(contract["openapi"], "3.1.0")
        self.assertEqual(contract["info"]["version"], api.API_VERSION)
        self.assertEqual(set(contract["paths"]), expected_paths)
        self.assertEqual(contract["security"], [])
        for path, definition in contract["paths"].items():
            with self.subTest(path=path):
                self.assertEqual(set(definition), {"get"})
        manifest_ref = contract["components"]["schemas"]["RunView"]["properties"][
            "records"
        ]["items"]["$ref"]
        self.assertIn("089e23c53303b0c4b5298b12fdda11f646e3ff2b", manifest_ref)
        self.assertNotIn("/main/", manifest_ref)
        self.assertIn(
            "409",
            contract["paths"]["/api/v1/media/{object_id}"]["get"]["responses"],
        )

        status, served = api.route_get("/api/v1/openapi.json")
        self.assertEqual(status, 200)
        self.assertEqual(served, contract)

    @unittest.skipIf(jsonschema is None, "jsonschema is not installed in the lightweight host")
    def test_actual_catalog_and_detail_payloads_conform_to_openapi_schemas(self):
        contract = api.read_openapi_contract()
        catalog_data = {
            "items": [{"object_id": "interview/002"}],
            "item_count": 1,
            "next_cursor": None,
        }
        with (
            mock.patch.object(api, "list_media_items", return_value=catalog_data),
            mock.patch.object(
                api,
                "_media_evidence_summary",
                return_value=AVAILABLE_SUMMARY,
            ),
        ):
            _, catalog = api.route_get("/api/v1/media?include=evidence-summary")

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
        detail = {
            "api_version": api.API_VERSION,
            "data": inspector.build_view("interview/002", [record]),
        }

        schemas = copy.deepcopy(contract["components"]["schemas"])
        manifest_schema = json.loads(
            (ROOT / "contracts" / "provenance-manifest-v1.schema.json").read_text(
                encoding="utf-8"
            )
        )
        manifest_schema.pop("$id", None)
        schemas["RunView"]["properties"]["records"]["items"] = manifest_schema
        for name, payload in (("CatalogEnvelope", catalog), ("ProvenanceEnvelope", detail)):
            with self.subTest(schema=name):
                schema = {
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "components": {"schemas": schemas},
                    "$ref": f"#/components/schemas/{name}",
                }
                jsonschema.Draft202012Validator(
                    schema,
                    format_checker=jsonschema.FormatChecker(),
                ).validate(payload)

    def test_health_is_versioned_and_storage_independent(self):
        status, payload = api.route_get("/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["api_version"], "1.5.1")
        self.assertEqual(payload["status"], "ok")

    def test_catalog_is_paginated_and_adds_canonical_detail_links(self):
        catalog = {
            "items": [{"object_id": "interview/002"}, {"object_id": "third item"}],
            "item_count": 2,
            "next_cursor": "next+/=token",
        }
        with mock.patch.object(api, "list_media_items", return_value=catalog) as listing:
            status, payload = api.route_get("/api/v1/media?limit=2&cursor=current-token")

        self.assertEqual(status, 200)
        listing.assert_called_once_with(
            endpoint_url=api.PROVENANCE_ENDPOINT,
            bucket=api.PROVENANCE_BUCKET,
            cursor="current-token",
            limit=2,
        )
        self.assertEqual(
            [item["href"] for item in payload["data"]["items"]],
            ["/api/v1/media/interview%2F002", "/api/v1/media/third%20item"],
        )
        self.assertEqual(
            payload["data"]["next_href"],
            "/api/v1/media?limit=2&cursor=next%2B%2F%3Dtoken",
        )
        self.assertTrue(
            all("evidence_summary" not in item for item in payload["data"]["items"])
        )

    def test_catalog_optionally_includes_canonical_evidence_summaries(self):
        catalog = {
            "items": [{"object_id": "interview/002"}, {"object_id": "tampered"}],
            "item_count": 2,
            "next_cursor": "next+/=token",
        }
        integrity_summary = api._unavailable_media_summary(
            state="INTEGRITY_FAILED",
            code="EVIDENCE_INTEGRITY_FAILED",
            message="conflicting SHA-256 values",
        )
        with (
            mock.patch.object(api, "list_media_items", return_value=catalog),
            mock.patch.object(
                api,
                "_media_evidence_summary",
                side_effect=[AVAILABLE_SUMMARY, integrity_summary],
            ) as summarize,
        ):
            status, payload = api.route_get(
                "/api/v1/media?limit=2&cursor=current-token&include=evidence-summary"
            )

        self.assertEqual(status, 200)
        self.assertEqual(
            [item["evidence_summary"] for item in payload["data"]["items"]],
            [AVAILABLE_SUMMARY, integrity_summary],
        )
        self.assertEqual(
            [call.args[0] for call in summarize.call_args_list],
            ["interview/002", "tampered"],
        )
        self.assertEqual(
            payload["data"]["next_href"],
            "/api/v1/media?limit=2&cursor=next%2B%2F%3Dtoken&include=evidence-summary",
        )

    def test_catalog_summary_is_derived_from_the_strict_detail_view(self):
        records = [{"manifest_id": "manifest-1"}, {"manifest_id": "manifest-2"}]
        delivery = {"states": {}, "errors": []}
        view = {
            "run_count": 2,
            "record_count": 2,
            "openlineage_delivery": {"state_counts": {"DELIVERED": 1, "PENDING": 1}},
            "runs": [
                {
                    "last_recorded_at": "2026-09-15T09:00:00Z",
                    "statuses_observed": ["SUCCEEDED"],
                    "run_identity": {
                        "object_filename": "interview.mp4",
                        "completeness": "COMPLETE",
                    },
                    "artifact_evidence": [{"uri": "s3://input"}],
                },
                {
                    "last_recorded_at": "2026-09-15T10:00:00Z",
                    "statuses_observed": ["FAILED", "RETRYING"],
                    "run_identity": {
                        "object_filename": "interview-v2.mp4",
                        "completeness": "PARTIAL",
                    },
                    "artifact_evidence": [
                        {"uri": "s3://output/one"},
                        {"uri": "s3://output/two"},
                    ],
                },
            ],
        }
        with (
            mock.patch.object(api, "read_records", return_value=records) as read,
            mock.patch.object(
                api,
                "read_openlineage_delivery_evidence",
                return_value=delivery,
            ) as lineage,
            mock.patch.object(api, "build_view", return_value=view) as build,
        ):
            summary = api._media_evidence_summary("interview/002")

        self.assertEqual(
            summary,
            {
                "read_state": "AVAILABLE",
                "object_filenames": ["interview-v2.mp4", "interview.mp4"],
                "run_count": 2,
                "record_count": 2,
                "latest_recorded_at": "2026-09-15T10:00:00Z",
                "statuses_observed": ["FAILED", "RETRYING", "SUCCEEDED"],
                "run_identity_completeness": "PARTIAL",
                "artifact_node_count": 3,
                "openlineage_state_counts": {"DELIVERED": 1, "PENDING": 1},
                "error": None,
            },
        )
        read.assert_called_once_with(
            object_id="interview/002",
            endpoint_url=api.PROVENANCE_ENDPOINT,
            bucket=api.PROVENANCE_BUCKET,
        )
        lineage.assert_called_once_with(
            object_id="interview/002",
            records=records,
            endpoint_url=api.PROVENANCE_ENDPOINT,
            bucket=api.PROVENANCE_BUCKET,
        )
        build.assert_called_once_with("interview/002", records, delivery)

    def test_catalog_summary_distinguishes_missing_from_untrusted_evidence(self):
        cases = (
            (
                [],
                "EVIDENCE_NOT_FOUND",
                0,
                "EVIDENCE_NOT_FOUND",
            ),
            (
                ValueError("conflicting SHA-256 values"),
                "INTEGRITY_FAILED",
                None,
                "EVIDENCE_INTEGRITY_FAILED",
            ),
        )
        for result, state, count, code in cases:
            with self.subTest(state=state):
                behavior = (
                    {"side_effect": result}
                    if isinstance(result, Exception)
                    else {"return_value": result}
                )
                with mock.patch.object(api, "read_records", **behavior):
                    summary = api._media_evidence_summary("problem")
                self.assertEqual(summary["read_state"], state)
                self.assertEqual(summary["run_count"], count)
                self.assertEqual(summary["record_count"], count)
                self.assertEqual(summary["artifact_node_count"], count)
                self.assertEqual(summary["error"]["code"], code)

    def test_detail_reuses_strict_manifest_and_delivery_view(self):
        records = [{"manifest_id": "manifest-1"}]
        delivery = {"states": {}, "errors": []}
        view = {"object_id": "interview/002", "run_count": 1}
        with (
            mock.patch.object(api, "read_records", return_value=records) as read,
            mock.patch.object(
                api,
                "read_openlineage_delivery_evidence",
                return_value=delivery,
            ) as lineage,
            mock.patch.object(api, "build_view", return_value=view) as build,
        ):
            status, payload = api.route_get(
                "/api/v1/media/interview%2F002?run_id=manual__run%2042"
            )

        self.assertEqual(status, 200)
        self.assertEqual(payload, {"api_version": "1.5.1", "data": view})
        read.assert_called_once_with(
            object_id="interview/002",
            run_id="manual__run 42",
            endpoint_url=api.PROVENANCE_ENDPOINT,
            bucket=api.PROVENANCE_BUCKET,
        )
        lineage.assert_called_once_with(
            object_id="interview/002",
            records=records,
            run_id="manual__run 42",
            endpoint_url=api.PROVENANCE_ENDPOINT,
            bucket=api.PROVENANCE_BUCKET,
        )
        build.assert_called_once_with("interview/002", records, delivery)

    def test_request_validation_rejects_ambiguous_or_noncanonical_inputs(self):
        cases = (
            ("/api/v1/media?limit=1&limit=2", "INVALID_QUERY"),
            ("/api/v1/media?unknown=1", "INVALID_QUERY"),
            ("/api/v1/media?include=everything", "INVALID_INCLUDE"),
            ("/api/v1/media?limit=0", "INVALID_LIMIT"),
            ("/api/v1/media/interview%2f002", "INVALID_OBJECT_ID"),
            ("/api/v1/media/interview-002?run_id=", "INVALID_RUN_ID"),
        )
        for target, code in cases:
            with self.subTest(target=target):
                with self.assertRaises(api.APIError) as raised:
                    api.route_get(target)
                self.assertEqual(raised.exception.code, code)

    def test_missing_canonical_evidence_is_404(self):
        with mock.patch.object(api, "read_records", return_value=[]):
            with self.assertRaises(api.APIError) as raised:
                api.route_get("/api/v1/media/missing")

        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(raised.exception.code, "EVIDENCE_NOT_FOUND")

    def test_invalid_stored_evidence_is_a_visible_integrity_conflict(self):
        with mock.patch.object(
            api,
            "read_records",
            side_effect=ValueError("conflicting SHA-256 values"),
        ):
            with self.assertRaises(api.APIError) as raised:
                api.route_get("/api/v1/media/tampered")

        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(raised.exception.code, "EVIDENCE_INTEGRITY_FAILED")
        self.assertIn("conflicting SHA-256 values", str(raised.exception))

    def test_http_boundary_is_get_only_and_cors_is_allowlisted(self):
        server = api.ThreadingHTTPServer(("127.0.0.1", 0), api.ProvenanceAPIHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with mock.patch.object(api, "ALLOWED_ORIGINS", {"https://explorer.example"}):
                request = urllib.request.Request(
                    base + "/health",
                    headers={"Origin": "https://explorer.example"},
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read())
                    self.assertEqual(response.headers["Access-Control-Allow-Origin"], request.headers["Origin"])
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(payload["status"], "ok")

                post = urllib.request.Request(base + "/api/v1/media", data=b"{}", method="POST")
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(post, timeout=5)
                self.assertEqual(raised.exception.code, 405)
                self.assertEqual(raised.exception.headers["Allow"], "GET")
                raised.exception.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
