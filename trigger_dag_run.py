#!/usr/bin/env python3
"""Trigger the ingest_pipeline DAG with proper test configuration."""

import requests
import json

# Airflow API endpoint
api_url = "http://airflow-api-server:8080/api/v1/dags/ingest_pipeline/dagRuns"

# Test configuration
conf = {
    "id": "test-media-001",
    "filename": "sample-video.mp4"
}

# Trigger DAG run
response = requests.post(
    api_url,
    json={"conf": conf},
    headers={"Content-Type": "application/json"}
)

print(f"Status Code: {response.status_code}")
print(f"Response: {response.text}")

if response.status_code in [200, 201]:
    print("\n✓ DAG run triggered successfully!")
    run_data = response.json()
    print(f"Run ID: {run_data.get('dag_run_id', 'N/A')}")
    print(f"State: {run_data.get('state', 'N/A')}")
else:
    print("\n✗ Failed to trigger DAG run")
