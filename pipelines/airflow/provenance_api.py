#!/usr/bin/env python3
"""Read-only HTTP boundary over canonical Babelapha provenance evidence."""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.parse

from inspect_provenance import (
    build_view,
    list_media_items,
    read_openlineage_delivery_evidence,
    read_records,
)


API_VERSION = "1.2.0"
API_PORT = int(os.environ.get("PROVENANCE_API_PORT", "8010"))
PROVENANCE_BUCKET = os.environ.get("PROVENANCE_S3_BUCKET") or os.environ.get(
    "S3_BUCKET", "pachyderm"
)
PROVENANCE_ENDPOINT = os.environ.get("PROVENANCE_S3_ENDPOINT") or os.environ.get(
    "MINIO_ENDPOINT"
)
MODULE_DIR = Path(__file__).resolve().parent
PACKAGED_OPENAPI_PATH = MODULE_DIR / "contracts" / "provenance-read-api-v1.openapi.json"
REPOSITORY_OPENAPI_PATH = MODULE_DIR.parent.parent / "contracts" / "provenance-read-api-v1.openapi.json"
OPENAPI_PATH = Path(
    os.environ.get(
        "PROVENANCE_API_OPENAPI_PATH",
        str(PACKAGED_OPENAPI_PATH if PACKAGED_OPENAPI_PATH.exists() else REPOSITORY_OPENAPI_PATH),
    )
)
ALLOWED_ORIGINS = {
    origin.strip()
    for origin in os.environ.get("PROVENANCE_API_ALLOWED_ORIGINS", "").split(",")
    if origin.strip()
}


class APIError(ValueError):
    """Expected request error with a stable HTTP representation."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code


def read_openapi_contract() -> dict:
    """Read and minimally bind the published contract to this implementation."""
    contract = json.loads(OPENAPI_PATH.read_text(encoding="utf-8"))
    if contract.get("openapi") != "3.1.0" or contract.get("info", {}).get("version") != API_VERSION:
        raise ValueError("OpenAPI contract version differs from the running API")
    return contract


def _validate_query(query: dict[str, list[str]], allowed: set[str]) -> None:
    unexpected = sorted(set(query) - allowed)
    if unexpected:
        raise APIError(400, "INVALID_QUERY", f"Unsupported query parameters: {unexpected}")
    repeated = sorted(key for key, values in query.items() if len(values) != 1)
    if repeated:
        raise APIError(400, "INVALID_QUERY", f"Repeated query parameters: {repeated}")


def _decode_object_id(encoded: str) -> str:
    if not encoded or "/" in encoded:
        raise APIError(404, "NOT_FOUND", "Resource not found")
    try:
        object_id = urllib.parse.unquote_to_bytes(encoded).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise APIError(400, "INVALID_OBJECT_ID", "Object ID is not valid UTF-8") from exc
    if urllib.parse.quote(object_id, safe="") != encoded:
        raise APIError(400, "INVALID_OBJECT_ID", "Object ID path encoding is not canonical")
    return object_id


def _media_href(object_id: str) -> str:
    return f"/api/v1/media/{urllib.parse.quote(object_id, safe='')}"


def route_get(target: str) -> tuple[int, dict]:
    """Resolve one GET target without creating any independent status state."""
    parsed = urllib.parse.urlsplit(target)
    try:
        query = urllib.parse.parse_qs(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as exc:
        raise APIError(400, "INVALID_QUERY", "Query string is malformed") from exc

    if parsed.path == "/health":
        _validate_query(query, set())
        return 200, {
            "api_version": API_VERSION,
            "service": "babelapha-provenance-api",
            "status": "ok",
        }

    if parsed.path == "/ready":
        _validate_query(query, set())
        read_openapi_contract()
        list_media_items(
            endpoint_url=PROVENANCE_ENDPOINT,
            bucket=PROVENANCE_BUCKET,
            limit=1,
        )
        return 200, {
            "api_version": API_VERSION,
            "service": "babelapha-provenance-api",
            "status": "ready",
        }

    if parsed.path == "/api/v1/openapi.json":
        _validate_query(query, set())
        return 200, read_openapi_contract()

    if parsed.path == "/api/v1/media":
        _validate_query(query, {"cursor", "limit"})
        cursor = query.get("cursor", [None])[0]
        if cursor == "":
            raise APIError(400, "INVALID_CURSOR", "Cursor cannot be empty")
        try:
            limit = int(query.get("limit", ["50"])[0])
        except ValueError as exc:
            raise APIError(400, "INVALID_LIMIT", "Limit must be an integer") from exc
        try:
            catalog = list_media_items(
                endpoint_url=PROVENANCE_ENDPOINT,
                bucket=PROVENANCE_BUCKET,
                cursor=cursor,
                limit=limit,
            )
        except ValueError as exc:
            if "limit must be" in str(exc).lower():
                raise APIError(400, "INVALID_LIMIT", str(exc)) from exc
            raise
        for item in catalog["items"]:
            item["href"] = _media_href(item["object_id"])
        catalog["next_href"] = (
            "/api/v1/media?"
            + urllib.parse.urlencode(
                {"limit": limit, "cursor": catalog["next_cursor"]},
            )
            if catalog["next_cursor"]
            else None
        )
        return 200, {"api_version": API_VERSION, "data": catalog}

    media_prefix = "/api/v1/media/"
    if parsed.path.startswith(media_prefix):
        _validate_query(query, {"run_id"})
        object_id = _decode_object_id(parsed.path[len(media_prefix) :])
        run_id = query.get("run_id", [None])[0]
        if run_id == "":
            raise APIError(400, "INVALID_RUN_ID", "Run ID cannot be empty")
        records = read_records(
            object_id=object_id,
            run_id=run_id,
            endpoint_url=PROVENANCE_ENDPOINT,
            bucket=PROVENANCE_BUCKET,
        )
        if not records:
            raise APIError(404, "EVIDENCE_NOT_FOUND", "No canonical provenance evidence found")
        delivery = read_openlineage_delivery_evidence(
            object_id=object_id,
            records=records,
            run_id=run_id,
            endpoint_url=PROVENANCE_ENDPOINT,
            bucket=PROVENANCE_BUCKET,
        )
        return 200, {
            "api_version": API_VERSION,
            "data": build_view(object_id, records, delivery),
        }

    raise APIError(404, "NOT_FOUND", "Resource not found")


class ProvenanceAPIHandler(BaseHTTPRequestHandler):
    server_version = "BabelaphaProvenanceAPI/1"

    def _origin(self) -> str | None:
        origin = self.headers.get("Origin")
        return origin if origin and (origin in ALLOWED_ORIGINS or "*" in ALLOWED_ORIGINS) else None

    def send_json(self, status: int, payload: dict) -> None:
        body = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        origin = self._origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", "*" if "*" in ALLOWED_ORIGINS else origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        try:
            status, payload = route_get(self.path)
        except APIError as exc:
            self.send_json(
                exc.status,
                {"api_version": API_VERSION, "error": {"code": exc.code, "message": str(exc)}},
            )
            return
        except Exception as exc:
            print(f"[provenance-api] {type(exc).__name__}: {exc}", file=sys.stderr)
            self.send_json(
                500,
                {
                    "api_version": API_VERSION,
                    "error": {
                        "code": "EVIDENCE_READ_FAILED",
                        "message": "Canonical provenance evidence could not be read or validated",
                    },
                },
            )
            return
        self.send_json(status, payload)

    def do_POST(self) -> None:
        self.send_response(405)
        self.send_header("Allow", "GET")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_OPTIONS(self) -> None:
        origin = self._origin()
        if not origin:
            self.send_json(
                403,
                {
                    "api_version": API_VERSION,
                    "error": {"code": "ORIGIN_NOT_ALLOWED", "message": "Origin is not allowed"},
                },
            )
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*" if "*" in ALLOWED_ORIGINS else origin)
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Accept")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Vary", "Origin")
        self.end_headers()


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), ProvenanceAPIHandler)
    print(f"Babelapha provenance API listening on port {API_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
