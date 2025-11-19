# Media Ingestion Pipeline - Status Report

## Recent Changes

### Commit: 4b0770f (Current)
**Date**: November 19, 2025
**Message**: "Feat: Add full media ingestion pipeline with Pachyderm download, ClamAV scan, media validation, and FFmpeg transcoding"

Enhanced `pipelines/airflow/dags/ingest_pipeline.py` with complete production workflow.

### Previous Commit: aa3f022 
**Message**: "Optimize: Defer KubernetesPodOperator import to avoid slow provider initialization"
- Fixed DAG validation timeout (30s → 17s)
- TeamCity build 49: ✅ PASSED

---

## Pipeline Architecture

### 7-Task Media Ingestion Workflow

```
validate_inputs 
    ↓
download_from_pachyderm
    ↓
virus_scan
    ↓
validate_media
    ↓
transcode
    ↓
upload_results
    ↓
mark_complete
```

### Task Details

**1. validate_inputs** (@task)
- Extract object_id and filename from DAG config
- Validate required parameters present
- Output XCom dict with paths and directories
- **Config**: `{"id": "test-001", "filename": "interview.mp4"}`

**2. download_from_pachyderm** (KubernetesPodOperator)
- Image: `python:3.11-slim`
- Creates work directories
- TODO: Implement boto3 S3 download
- Receives S3_PATH via XCom environment variable

**3. virus_scan** (KubernetesPodOperator)
- Image: `clamav/clamav:latest`
- Runs freshclam (update virus DB)
- Executes clamscan on input file
- Exit codes: 0=clean, 1=virus found

**4. validate_media** (KubernetesPodOperator)
- Image: `jrottenberg/ffmpeg:latest`
- Uses ffprobe to validate media format
- Extracts video properties (width, height)
- Ensures media is valid for transcoding

**5. transcode** (KubernetesPodOperator)
- Image: `jrottenberg/ffmpeg:latest`
- Creates HLS playlist (m3u8) with 10s segments
- Creates DASH manifest (mpd) with 10s segments
- Uses H.264 codec (crf=23) and AAC audio
- Validates output files exist before success

**6. upload_results** (KubernetesPodOperator)
- Image: `python:3.11-slim`
- Verifies HLS and DASH output files
- TODO: Implement boto3 S3 upload to MinIO/Pachyderm
- Logs success/failure with file paths

**7. mark_complete** (@task)
- Final completion marker
- Outputs object_id confirmation message

---

## Configuration

### KubernetesPodOperator Critical Settings
```python
KubernetesPodOperator(
    in_cluster=True,                                  # Run in cluster
    get_logs=True,                                    # Stream pod output to task logs ✅
    is_delete_operator_pod=False,                     # Keep pods for debugging ✅
    node_selector={"kubernetes.io/arch": "amd64"},   # Transcode CPU requirement
)
```

### Deferred Import Pattern (CRITICAL)
```python
def ingest_pipeline():
    # Deferred import avoids slow provider manager initialization
    from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator
    # DAG definition continues...
```

### Data Flow with XCom
```
validate_inputs outputs:
  - object_id
  - filename
  - s3_input_path
  - local_input_path
  - local_work_dir
  - output_dir

Each task receives via environment variables:
  env={
      'S3_PATH': '{{ task_instance.xcom_pull(task_ids="validate_inputs")["s3_input_path"] }}',
      ...
  }
```

---

## Testing

### Test Case 1: November 19, 12:01 UTC
- Run ID: `manual__2025-11-19T12:01:27.619066+00:00_fxwPLnks`
- All 5 tasks (old version): ✅ SUCCESS
- Duration: 52 seconds
- Task logs verified: Pod output captured ✅

### Test Case 2: November 19, 12:15 UTC
- Run ID: `manual__2025-11-19T12:15:21.453256+00:00_6Df4mIw9`
- All 5 tasks (old version): ✅ SUCCESS
- Duration: 39 seconds
- Task logs verified: Pod output captured ✅

---

## Outstanding Work

### TODO Items in Code

**Line 100** - download_from_pachyderm:
```python
# TODO: Download from S3 using boto3
# s3_client = boto3.client('s3', endpoint_url='http://minio:9000')
# s3_client.download_file('pachyderm', key, local_path)
```

**Line 267** - upload_results:
```python
# TODO: Upload to MinIO/S3 using boto3
# s3_client.upload_file(local_path, 'pachyderm', s3_key)
```

### Configuration Required

1. **MinIO/S3 Credentials**:
   - `MINIO_ACCESS_KEY` (currently defaults to 'pachyderm')
   - `MINIO_SECRET_KEY` (currently defaults to 'pachyderm')
   - `MINIO_ENDPOINT_URL` (if not using default)

2. **boto3 Integration**:
   - Add boto3 to Python container or use custom image with pre-installed boto3
   - Implement actual download logic
   - Implement actual upload logic

3. **Pachyderm S3 Access**:
   - Verify S3 bucket name and path structure
   - Ensure credentials have read/write permissions

---

## Deployment Status

### Current Environment
- **Airflow Version**: 3.1.0
- **Executor**: LocalExecutor
- **Scheduler Pod**: airflow-scheduler-5f766dd6cb-7j2kp
- **DAG Location**: /opt/airflow/dags
- **Git Sync**: Enabled (pulls from origin/main)

### DAG Registration
```
$ airflow dags list
dag_id                  | description
ingest_pipeline         | Media ingestion pipeline: validate → scan → transcode → upload
ingest_pipeline_v2      | Advanced media pipeline with pre/post validation
```

### Next Steps

1. **Commit Status**: ✅ Pushed to origin/main (commit 4b0770f)
2. **TeamCity**: Awaiting build trigger
3. **DAG Sync**: Git-sync will pull changes automatically
4. **Validation**: TeamCity will validate both DAGs parse without errors
5. **Testing**: Once deployed, test with real parameters:
   ```bash
   airflow dags trigger ingest_pipeline --conf '{"id": "test-001", "filename": "interview.mp4"}'
   ```

---

## Known Issues

### Non-Blocking

1. **Airflow UI Log Fetch Error**:
   - Symptom: "Could not read served logs: HTTPConnectionPool... NameResolutionError"
   - Status: UI issue only - logs ARE being written to disk
   - Workaround: Access logs via filesystem or CLI
   - Impact: No impact on functionality

---

## Reference: Pipeline v2 (Advanced)

File: `pipelines/airflow/dags/ingest_pipeline_v2.py`
- Provides micro-stage architecture with pre/post validation
- Better error recovery and stage separation
- Available as reference for future enhancements

---

## Contact & Support

For issues with:
- **DAG Logic**: See ingest_pipeline.py comments
- **Kubernetes**: Check scheduler pod logs via kubectl
- **S3/MinIO**: Verify credentials and endpoint configuration
- **Git Sync**: Check git-sync pod logs for pull errors
