# Babelapha
> **Note:** "Babelapha" is a working placeholder name. Until a name worthy to replace it comesby.


## What This Project Is About

**Media Platform** is an open project to turn interview videos into searchable, versioned, and analyzable data.

It starts simple:

- We upload videos to **MinIO (S3)**.
- **Airflow** runs workflows that extract audio, create transcripts, and store metadata.
- **Pachyderm** versions all data so every change is traceable.
- **FastAPI** serves a clean backend for the data.
- **React (Next.js)** provides the public website.
- **TeamCity** automates builds and deployments.

As we grow, we’ll add things like **Milvus** for semantic search, **OpenTelemetry** for monitoring,  
and an **interactive provenance explorer** so anyone can visually trace how each dataset was created.

---

## Project Structure (Simplified)

```
├─ README.md
├─ services/
│  ├─ api/          # FastAPI backend
│  └─ web/          # React/Next.js frontend
├─ pipelines/
│  ├─ airflow/      # DAGs (workflow definitions)
│  └─ pachyderm/    # Pipeline YAMLs
├─ platform/        # Helm charts / deploy scripts
├─ infra/           # Terraform cluster setup
└─ ci/
   └─ teamcity/     # TeamCity build settings
```

---

## Core Technologies

| Purpose | Tool |
|----------|------|
| Workflow orchestration | Apache Airflow |
| Data versioning | Pachyderm |
| Storage | MinIO (S3 API) |
| API backend | FastAPI |
| Frontend | React / Next.js |
| CI/CD | TeamCity |
| Orchestration | Kubernetes |

---

## Getting Started (Local Dev)

### 1. Run the API

```bash
cd services/api
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 2. Run the Web App

```bash
cd services/web
npm install
npm run dev
```

### 3. Run the local pipeline stack via Docker Compose (Airflow + MinIO)

Use the compose stack to run the local pipeline stack:

```bash
# one-time: create your env file (optional but recommended)
cp .env.example .env
docker compose up --build -d
```

The stack includes:

- `minio`: object storage for sample media upload/outputs.
- `minio-init`: one-time bootstrap that creates the `pachyderm` bucket.
- `pachyderm-webhook`: local webhook listener that triggers `ingest_pipeline_local` when a matching Pachyderm-style event payload is posted.
- `airflow-webserver` + `airflow-scheduler`: local Airflow runtime.
- `airflow-init`: one-time DB + admin user bootstrap.

To run the pipeline:

1. Upload a test file to `s3://pachyderm/incoming/<id>/<filename>` in MinIO.

```bash
# Bash
docker compose run --rm \
  --entrypoint /bin/sh \
  -v "$(pwd):/workspace" \
  minio-init -c 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" && mc cp /workspace/sample.mp4 local/pachyderm/incoming/sample-001/sample.mp4'

# PowerShell
docker compose run --rm --entrypoint /bin/sh -v "${PWD}:/workspace" minio-init -c 'mc alias set local http://minio:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD" && mc cp /workspace/sample.mp4 local/pachyderm/incoming/sample-001/sample.mp4'
```

2. Trigger `ingest_pipeline_local` from Airflow with conf:
 

```bash
docker compose exec airflow-webserver airflow dags trigger ingest_pipeline_local \
  --conf '{"id":"sample-001","filename":"sample.mp4"}'
```

3. Watch logs in the scheduler.

```bash
docker compose logs -f airflow-scheduler
```

4. Confirm outputs in MinIO under:

```text
s3://pachyderm/output/<id>/hls/*
s3://pachyderm/output/<id>/dash/*
```

Alternative event-driven path (closer to production):

1. Send a webhook payload:

```bash
curl -X POST http://localhost:8000/webhook/pachyderm \
  -H "Content-Type: application/json" \
  -d '{"action":"put_file","path":"/incoming/sample-001/sample.mp4"}'
```

This posts directly to `webhook_listener_stdlib` and queues an `ingest_pipeline_local` DAG run.

Notes:

- The compose stack is for **local development** and uses `airflow-local` mode.
- The production-style `ingest_pipeline` DAG still requires Kubernetes (currently via `KubernetesPodOperator`) and Pachyderm webhook wiring.
- The old `services/api` and `services/web` folders are not present in this checkout, so this compose currently focuses on the pipeline stack only.

---

## Objectives

This project aims to:

1. Build an open-source foundation for multimedia research data.
2. Make interview datasets reproducible, transparent, and accessible.
3. Introduce **interactive provenance** — a visual system that lets users explore how each artifact was created (which workflow, dataset version, and model produced it).
4. Offer a practical learning ground for data infrastructure enthusiasts.

---

## License

- **Code:** MIT  
- **Data/Content:** Licensed per dataset manifest (to be defined)

## Pipelines

- **Airflow DAGs**:
  - `pipelines/airflow/dags/ingest_pipeline.py` (production/Kubernetes mode).
  - `pipelines/airflow/dags/ingest_pipeline_v2.py` (experimental refactor).
  - `pipelines/airflow/dags/ingest_pipeline_local.py` (local Docker/MinIO mode for development).
- **Pachyderm Pipelines**: `pipelines/pachyderm/transcription-pipeline.yaml` versions cleaned transcripts.

## Pipeline Improvement Opportunities

1. Replace duplicated pipeline implementations (`ingest_pipeline.py`, `ingest_pipeline_v2.py`, `ingest_pipeline_local.py`) with one source of truth plus execution mode toggles.
2. Wire local mode to a true file-availability contract (manifest/checksum tracking) before stage transitions.
3. Move hardcoded MinIO defaults into a single config source and fail fast when env vars are missing.
4. Add structured report output to the MinIO prefix for each stage (`/reports/<id>/...`) and keep it consistent with Pachyderm-side scripts.
5. Implement retry/backoff and dead-letter handling for failed transcoding/validation runs.
6. Add alerting + metrics on stage latency and error counts (especially for transcoding and uploads).
7. Harden webhook/API authentication for `ingest_pipeline` and lock down endpoint access.
8. Add integration smoke tests for: local DAG trigger, invalid payload handling, empty/bad input files, and end-to-end output verification.

## Continuous Integration

TeamCity Kotlin DSL files live in `ci/teamcity`. The `Media Pipeline Checks` build configuration
validates DAG syntax and lints pipeline specs so that broken workflows are caught early.
