"""Small Pachyderm-style webhook adapter for the local Airflow 3 stack."""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from webhook_payload import build_dag_conf, dag_run_id


AIRFLOW_API_URL = os.environ.get("AIRFLOW_API_URL", "http://airflow-webserver:8080/api/v2")
AIRFLOW_AUTH_URL = os.environ.get("AIRFLOW_AUTH_URL", "http://airflow-webserver:8080/auth/token")
AIRFLOW_API_USERNAME = os.environ.get("AIRFLOW_API_USERNAME", "admin")
AIRFLOW_API_PASSWORD = os.environ.get("AIRFLOW_API_PASSWORD", "admin123")
AIRFLOW_DAG_ID = os.environ.get("AIRFLOW_DAG_ID", "ingest_pipeline_local")
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", "8000"))


class AirflowAPIError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"Airflow returned {status}: {body}")
        self.status = status


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
        raise AirflowAPIError(error.code, body) from error


def trigger_dag(payload):
    conf = build_dag_conf(payload)
    requested_run_id = dag_run_id(conf)
    auth = post_json(
        AIRFLOW_AUTH_URL,
        {"username": AIRFLOW_API_USERNAME, "password": AIRFLOW_API_PASSWORD},
    )
    access_token = auth.get("access_token")
    if not access_token:
        raise RuntimeError("Airflow token response did not include access_token")

    dag_url = f"{AIRFLOW_API_URL.rstrip('/')}/dags/{urllib.parse.quote(AIRFLOW_DAG_ID, safe='')}/dagRuns"
    try:
        return post_json(
            dag_url,
            {
                "dag_run_id": requested_run_id,
                "conf": conf,
                "logical_date": datetime.now(timezone.utc).isoformat(),
            },
            {"Authorization": f"Bearer {access_token}"},
        )
    except AirflowAPIError as error:
        if error.status == 409:
            return {"dag_run_id": requested_run_id, "duplicate": True}
        raise


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
