#!/usr/bin/env python3
"""
Webhook listener for Pachyderm file upload events.

Listens for PUT_FILE events from Pachyderm and automatically triggers
the ingest_pipeline DAG with extracted file metadata.

Usage:
    python webhook_listener.py --port 8000
"""

import os
import json
import logging
from flask import Flask, request, jsonify
from datetime import datetime
import requests
from typing import Dict

from webhook_payload import build_dag_conf, dag_run_id

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

# Flask app setup
app = Flask(__name__)

# Configuration
AIRFLOW_API_URL = os.environ.get(
    "AIRFLOW_API_URL",
    "http://airflow-webserver:8080/api/v1"
)
AIRFLOW_DAG_ID = os.environ.get("AIRFLOW_DAG_ID", "ingest_pipeline")
PACH_INCOMING_PATH = "/incoming"  # Pachyderm path where uploads arrive
PACH_REPO = "media"
PACH_BRANCH = "master"

def trigger_airflow_dag(metadata: Dict[str, str]) -> bool:
    """
    Trigger the ingest_pipeline DAG in Airflow with the given metadata.
    
    Args:
        metadata: Dict with 'id' and 'filename' keys
    
    Returns:
        True if successful, False otherwise
    """
    try:
        dag_run_url = f"{AIRFLOW_API_URL}/dags/{AIRFLOW_DAG_ID}/dagRuns"
        
        payload = {
            "dag_run_id": dag_run_id(metadata),
            "conf": metadata,
            "note": f"Auto-triggered by Pachyderm webhook for {metadata.get('filename')}"
        }
        
        logger.info(f"Triggering DAG with payload: {payload}")
        
        response = requests.post(
            dag_run_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        
        if response.status_code in [200, 201]:
            run_data = response.json()
            run_id = run_data.get('dag_run_id', 'unknown')
            logger.info(f"✓ DAG triggered successfully: run_id={run_id}")
            return True
        elif response.status_code == 409:
            logger.info("DAG run already exists for this Pachyderm commit and object")
            return True
        else:
            logger.error(
                f"✗ Failed to trigger DAG: status={response.status_code}, "
                f"response={response.text}"
            )
            return False
    
    except requests.exceptions.Timeout:
        logger.error("Request to Airflow API timed out")
        return False
    except requests.exceptions.RequestException as e:
        logger.error(f"Request to Airflow API failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error triggering DAG: {e}")
        return False


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/webhook/pachyderm", methods=["POST"])
def pachyderm_webhook():
    """
    Handle Pachyderm webhook events.
    
    Pachyderm sends a JSON payload with commit info and file operations.
    Expected event format from Pachyderm notifications:
    {
        "action": "put_file" | "delete_file" | ...,
        "path": "/incoming/object-id/filename.ext",
        "commit": {
            "branch": {...},
            "id": "..."
        }
    }
    """
    try:
        event = request.get_json()
        
        if not event:
            logger.warning("Received empty webhook payload")
            return jsonify({"error": "empty payload"}), 400
        
        logger.info(f"Received Pachyderm webhook: {json.dumps(event)}")
        
        # Filter for PUT_FILE events in /incoming path only
        action = event.get("action", "").lower()
        path = event.get("path", "")
        
        if action not in ["put_file", "putfile"]:
            logger.info(f"Ignoring event action: {action}")
            return jsonify({"status": "ignored", "reason": f"action={action}"}), 200
        
        if not path.startswith(PACH_INCOMING_PATH):
            logger.info(f"Ignoring file outside {PACH_INCOMING_PATH}: {path}")
            return jsonify({"status": "ignored", "reason": f"path={path}"}), 200
        
        # Preserve the exact Pachyderm commit in the Airflow run config.
        try:
            metadata = build_dag_conf(event)
        except ValueError as error:
            logger.error(f"Invalid lineage identity: {error}")
            return jsonify({"error": str(error)}), 400
        
        logger.info(f"Extracted metadata: {metadata}")
        
        # Trigger DAG
        if trigger_airflow_dag(metadata):
            return jsonify({
                "status": "success",
                "message": "DAG triggered",
                "metadata": metadata
            }), 202
        else:
            return jsonify({
                "status": "error",
                "message": "Failed to trigger DAG"
            }), 500
    
    except json.JSONDecodeError:
        logger.error("Invalid JSON in webhook payload")
        return jsonify({"error": "invalid json"}), 400
    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/webhook/pachyderm", methods=["GET"])
def webhook_status():
    """Get webhook status."""
    return jsonify({
        "service": "pachyderm-webhook-listener",
        "status": "active",
        "airflow_api": AIRFLOW_API_URL,
        "timestamp": datetime.utcnow().isoformat() + "Z"
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("WEBHOOK_PORT", 8000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    
    logger.info(f"Starting webhook listener on port {port}")
    logger.info(f"Airflow API URL: {AIRFLOW_API_URL}")
    logger.info(f"Debug mode: {debug}")
    
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
