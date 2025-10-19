# 🧠 Media Platform

### Transparent, Computation-Friendly Interview Library

---

## 🚀 What This Project Is About

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

## 🧱 Project Structure (Simplified)

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

## 🧩 Core Technologies

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

## 🧪 Getting Started (Local Dev)

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

### 3. (Optional) Run everything via Docker Compose
We’ll add a simple `docker-compose.yml` soon to bring up MinIO, the API, and the web frontend in one command.

---

## 🎯 Objectives

This project aims to:
1. Build an open-source foundation for multimedia research data.
2. Make interview datasets reproducible, transparent, and accessible.
3. Introduce **interactive provenance** — a visual system that lets users explore how each artifact was created (which workflow, dataset version, and model produced it).
4. Offer a practical learning ground for data infrastructure enthusiasts.

---

## 🪪 License

- **Code:** MIT  
- **Data/Content:** Licensed per dataset manifest (to be defined)
