"""Small Pachyderm-style webhook adapter for the local Airflow 3 stack."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


AIRFLOW_API_URL = os.environ.get("AIRFLOW_API_URL", "http://airflow-webserver:8080/api/v2")
AIRFLOW_AUTH_URL = os.environ.get("AIRFLOW_AUTH_URL", "http://airflow-webserver:8080/auth/token")
AIRFLOW_API_USERNAME = os.environ.get("AIRFLOW_API_USERNAME", "admin")
AIRFLOW_API_PASSWORD = os.environ.get("AIRFLOW_API_PASSWORD", "admin123")
AIRFLOW_DAG_ID = os.environ.get("AIRFLOW_DAG_ID", "ingest_pipeline_local")
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", "8000"))


def post_json(url, payload, headers=None):
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Airflow returned {error.code}: {body}") from error


def build_dag_conf(payload):
    if payload.get("id") and payload.get("filename"):
        return {"id": str(payload["id"]), "filename": str(payload["filename"])}

    path = str(payload.get("path", "")).strip("/")
    path_parts = path.split("/")
    if len(path_parts) >= 3 and path_parts[0] == "incoming":
        return {"id": path_parts[-2], "filename": path_parts[-1]}

    raise ValueError("Webhook payload needs id and filename, or an incoming/<id>/<filename> path")


def trigger_dag(payload):
    auth = post_json(
        AIRFLOW_AUTH_URL,
        {"username": AIRFLOW_API_USERNAME, "password": AIRFLOW_API_PASSWORD},
    )
    access_token = auth.get("access_token")
    if not access_token:
        raise RuntimeError("Airflow token response did not include access_token")

    dag_url = f"{AIRFLOW_API_URL.rstrip('/')}/dags/{urllib.parse.quote(AIRFLOW_DAG_ID, safe='')}/dagRuns"
    return post_json(
        dag_url,
        {"conf": build_dag_conf(payload), "logical_date": datetime.now(timezone.utc).isoformat()},
        {"Authorization": f"Bearer {access_token}"},
    )


class WebhookHandler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.send_json(200, {"status": "ok"})
            return
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook/pachyderm":
            self.send_json(404, {"error": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            dag_run = trigger_dag(payload)
        except (ValueError, json.JSONDecodeError) as error:
            self.send_json(400, {"error": str(error)})
            return
        except (RuntimeError, urllib.error.URLError) as error:
            self.send_json(502, {"error": str(error)})
            return

        self.send_json(202, {"status": "triggered", "dag_run_id": dag_run.get("dag_run_id")})


if __name__ == "__main__":
    server = ThreadingHTTPServer(("0.0.0.0", WEBHOOK_PORT), WebhookHandler)
    print(f"Listening for Pachyderm-style webhooks on port {WEBHOOK_PORT}")
    server.serve_forever()
