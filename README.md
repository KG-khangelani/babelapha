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
- **OpenLineage + Marquez** collect and display artifact-level provenance.

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

On Windows/PowerShell, start the stack through the identity-verifying launcher:

```powershell
Copy-Item .env.example .env
.\scripts\Start-TransparentLocalStack.ps1
```

The launcher requires the DAG bundle to match a clean Git commit, builds the
Airflow and provenance API images, injects the exact running Airflow image ID,
and verifies those identities after startup. This is the recommended path for
provenance-bearing runs.

The basic portable Compose path remains available when exact local Git and
container identity is not required:

```bash
cp .env.example .env
docker compose up --build -d
```

The stack includes:

- `minio`: object storage for sample media upload/outputs.
- `minio-init`: one-time bootstrap that creates the `pachyderm` bucket.
- `pachyderm-webhook`: local webhook listener that triggers `ingest_pipeline_local` when a matching Pachyderm-style event payload is posted.
- `airflow-webserver` + `airflow-scheduler`: local Airflow runtime.
- `airflow-init`: one-time DB + admin user bootstrap.
- `marquez` + `marquez-web`: OpenLineage ingestion and lineage graph UI.
- `provenance-api`: read-only, versioned discovery and evidence API on port 8010.

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

5. Confirm immutable provenance records under
   `s3://pachyderm/provenance/<id>/<run-id>/` and inspect the lineage graph at
   <http://localhost:3001>.

   ```powershell
   docker compose run --rm provenance-inspect --list-objects
   docker compose run --rm provenance-inspect --object-id <id>
   ```

   The same canonical view is available over the local read-only API:

   ```bash
   curl http://localhost:8010/api/v1/media
   curl http://localhost:8010/api/v1/media/sample-001
   curl http://localhost:8010/api/v1/openapi.json
   ```

   The media detail response includes an ordered `stage_evidence` ledger. It
   groups retries and terminal decisions by task and explicitly marks expected
   stages that have no immutable record, while the accompanying manifests retain
   the exact artifact, Git, DAG-bundle, and container identities. A verified
   `run_identity` is returned only when every stage agrees on the common
   filename, Pachyderm, Git, DAG, and orchestrator facts. First-class
   `artifact_evidence` nodes group every input/output occurrence by URI and
   reject competing hashes or storage versions.

Alternative event-driven path (closer to production):

1. Send a webhook payload:

```bash
curl -X POST http://localhost:8000/webhook/pachyderm \
  -H "Content-Type: application/json" \
  -d '{"action":"put_file","path":"/incoming/sample-001/sample.mp4","commit":{"id":"local-demo-commit"}}'
```

This posts to the Airflow 3 webhook adapter and queues one deterministic
`ingest_pipeline_local` run for that exact Pachyderm commit and object.

Notes:

- The compose stack is for **local development** and uses `airflow-local` mode.
- The provenance API has no write routes. Keep it private in local development;
  add deployment authentication and rate limiting before exposing it publicly.
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
  - `pipelines/airflow/dags/ingest_pipeline_v2.py` (experimental, provenance-gated Kubernetes boundary diagnostics; no media processing).
  - `pipelines/airflow/dags/ingest_pipeline_local.py` (local Docker/MinIO mode for development).
- **Pachyderm Pipelines**: `pipelines/pachyderm/transcription-pipeline.yaml` versions cleaned transcripts.

## Pipeline Improvement Opportunities

1. Replace duplicated production/local pipeline implementations with one source of truth plus execution mode toggles, then retire the separate `ingest_pipeline_v2` diagnostic when equivalent stage-isolation tests exist.
2. Move hardcoded MinIO defaults into a single config source and fail fast when production secrets are missing.
3. Implement dead-letter handling for failed transcoding/validation runs.
4. Add alerting + metrics on stage latency and error counts (especially for transcoding and uploads).
5. Harden webhook/API authentication for `ingest_pipeline` and lock down endpoint access.
6. Add integration smoke tests for invalid payloads, empty/bad input files, retry history, and end-to-end output verification.

The implemented provenance contract, failure semantics, OpenLineage mapping,
and exact-identity configuration are documented in
[`Documentation/pipeline-transparency.md`](Documentation/pipeline-transparency.md).

## Continuous Integration

TeamCity Kotlin DSL files live in `ci/teamcity`. The `Media Pipeline Checks` build configuration
validates DAG syntax and lints pipeline specs so that broken workflows are caught early.
