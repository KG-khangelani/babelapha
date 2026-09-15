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
        with mock.patch.object(api, "list_media_items", return_value=catalog_data):
            _, catalog = api.route_get("/api/v1/media")

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
        self.assertEqual(payload["api_version"], "1.1.0")
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
        self.assertEqual(payload, {"api_version": "1.1.0", "data": view})
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
