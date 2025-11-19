#!/usr/bin/env python3
from airflow.models import DagBag
from airflow.utils.state import State
from airflow.utils.types import DagRunType
from datetime import datetime

# Load DAG
dagbag = DagBag(dag_folder='/opt/airflow/dags', include_examples=False)
dag = dagbag.get_dag('ingest_pipeline')

if dag:
    # Trigger a DAG run with configuration
    run = dag.create_dagrun(
        run_type=DagRunType.MANUAL,
        state=State.QUEUED,
        conf={"id": "test-media-002", "filename": "sample-video.mp4"},
        data_interval_start=datetime.utcnow(),
        data_interval_end=datetime.utcnow(),
    )
    print(f"✓ DAG run triggered: {run.run_id}")
    print(f"  State: {run.state}")
    print(f"  Conf: {run.conf}")
else:
    print("✗ DAG not found")
