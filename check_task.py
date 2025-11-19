#!/usr/bin/env python3
from airflow.models import TaskInstance
from airflow.utils.session import create_session
from sqlalchemy import desc

with create_session() as session:
    ti = session.query(TaskInstance).filter(
        TaskInstance.task_id == 'virus_scan',
        TaskInstance.dag_id == 'ingest_pipeline'
    ).order_by(desc(TaskInstance.start_date)).first()
    
    if ti:
        print(f"Task State: {ti.state}")
        print(f"Try Number: {ti.try_number}")
        print(f"Max Tries: {ti.max_tries}")
        print(f"Start Date: {ti.start_date}")
        print(f"End Date: {ti.end_date}")
        print(f"Duration: {ti.duration}")
        print(f"Hostname: {ti.hostname}")
        print(f"Operator: {ti.operator}")
        
        # Try to get the log
        try:
            from airflow.utils.log.log_reader import TaskLogReader
            log_reader = TaskLogReader()
            logs = log_reader.read_log_chunks(ti, ti.try_number)
            print("\n=== Task Logs ===")
            for log_chunk in logs:
                print(log_chunk[1])
        except Exception as e:
            print(f"\nCouldn't read logs: {e}")
    else:
        print("Task instance not found")
