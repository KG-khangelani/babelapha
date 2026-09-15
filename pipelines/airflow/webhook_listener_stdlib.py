#!/usr/bin/env python3
"""
Webhook listener for Pachyderm file upload events.
Uses only Python stdlib (no external dependencies).

Listens for PUT_FILE events from Pachyderm and triggers ingest_pipeline DAG.
"""

import os
import json
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime
import threading

from webhook_payload import build_dag_conf, dag_run_id

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
AIRFLOW_API_URL = os.environ.get(
    "AIRFLOW_API_URL",
    "http://airflow-webserver:8080/api/v1"
)
AIRFLOW_DAG_ID = os.environ.get("AIRFLOW_DAG_ID", "ingest_pipeline")
WEBHOOK_PORT = int(os.environ.get("WEBHOOK_PORT", 8000))
PACH_INCOMING_PATH = "/incoming"

def trigger_airflow_dag(metadata):
    """
    Trigger the ingest_pipeline DAG in Airflow with the given metadata.
    """
    try:
        dag_run_url = f"{AIRFLOW_API_URL}/dags/{AIRFLOW_DAG_ID}/dagRuns"
        
        payload = {
            "dag_run_id": dag_run_id(metadata),
            "conf": metadata,
            "note": f"Auto-triggered by Pachyderm webhook for {metadata.get('filename')}"
        }
        
        logger.info(f"Triggering DAG with payload: {payload}")
        
        data = json.dumps(payload).encode('utf-8')
        req = Request(
            dag_run_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        
        with urlopen(req, timeout=10) as response:
            response_data = response.read().decode('utf-8')
            status_code = response.status
            
            if status_code in [200, 201]:
                run_data = json.loads(response_data)
                run_id = run_data.get('dag_run_id', 'unknown')
                logger.info(f"✓ DAG triggered successfully: run_id={run_id}")
                return True
            else:
                logger.error(f"✗ Failed to trigger DAG: status={status_code}")
                return False
    
    except HTTPError as e:
        if e.code == 409:
            logger.info("DAG run already exists for this Pachyderm commit and object")
            return True
        logger.error(f"Airflow API returned HTTP {e.code}")
        return False
    except URLError as e:
        logger.error(f"Request to Airflow API failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error triggering DAG: {e}")
        return False


class WebhookHandler(BaseHTTPRequestHandler):
    """HTTP request handler for webhook."""
    
    def log_message(self, format, *args):
        """Override to use our logger."""
        logger.info(format % args)
    
    def do_GET(self):
        """Handle GET requests."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = json.dumps({"status": "ok"}).encode('utf-8')
            self.wfile.write(response)
        elif self.path == "/webhook/pachyderm":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = json.dumps({
                "service": "pachyderm-webhook-listener",
                "status": "active",
                "airflow_api": AIRFLOW_API_URL,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }).encode('utf-8')
            self.wfile.write(response)
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        """Handle POST requests (webhook events)."""
        if self.path != "/webhook/pachyderm":
            self.send_response(404)
            self.end_headers()
            return
        
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            
            if not body:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "empty payload"}).encode('utf-8'))
                return
            
            event = json.loads(body)
            logger.info(f"Received Pachyderm webhook: {json.dumps(event)}")
            
            # Filter for PUT_FILE events in /incoming path
            action = event.get("action", "").lower()
            path = event.get("path", "")
            
            if action not in ["put_file", "putfile"]:
                logger.info(f"Ignoring event action: {action}")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ignored",
                    "reason": f"action={action}"
                }).encode('utf-8'))
                return
            
            if not path.startswith(PACH_INCOMING_PATH):
                logger.info(f"Ignoring file outside {PACH_INCOMING_PATH}: {path}")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ignored",
                    "reason": f"path={path}"
                }).encode('utf-8'))
                return
            
            # Preserve the exact Pachyderm commit in the Airflow run config.
            try:
                metadata = build_dag_conf(event)
            except ValueError as error:
                logger.error(f"Invalid lineage identity: {error}")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(error)}).encode('utf-8'))
                return
            
            logger.info(f"Extracted metadata: {metadata}")
            
            # Trigger DAG (in background thread to avoid blocking)
            def trigger_in_background():
                if trigger_airflow_dag(metadata):
                    logger.info("DAG trigger succeeded")
                else:
                    logger.error("DAG trigger failed")
            
            thread = threading.Thread(target=trigger_in_background, daemon=True)
            thread.start()
            
            # Respond immediately
            self.send_response(202)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = json.dumps({
                "status": "success",
                "message": "DAG trigger queued",
                "metadata": metadata
            }).encode('utf-8')
            self.wfile.write(response)
        
        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook payload")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "invalid json"}).encode('utf-8'))
        except Exception as e:
            logger.error(f"Webhook processing error: {e}", exc_info=True)
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))


def run_server():
    """Start the webhook HTTP server."""
    server_address = ("0.0.0.0", WEBHOOK_PORT)
    httpd = HTTPServer(server_address, WebhookHandler)
    
    logger.info(f"Starting webhook listener on port {WEBHOOK_PORT}")
    logger.info(f"Airflow API URL: {AIRFLOW_API_URL}")
    logger.info(f"Listening for events at http://0.0.0.0:{WEBHOOK_PORT}/webhook/pachyderm")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down webhook listener")
        httpd.shutdown()


if __name__ == "__main__":
    run_server()
