#!/usr/bin/env python3
"""Trigger the ingest_pipeline DAG with test configuration."""

from airflow.api.client.local_client import Client

# Initialize client
client = Client(api_base_url=None, auth=None)

# Trigger DAG with test configuration
result = client.trigger_dag(
    dag_id="ingest_pipeline",
    conf={"id": "test-001", "filename": "sample.mp4"}
)

print(f"DAG run triggered: {result}")
