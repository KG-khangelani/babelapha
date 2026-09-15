FROM python:3.11.16-slim-bookworm@sha256:528257d48c1da0dcecc2e725d1ae34498d60c965f1241e39cd6a85a8859bdf84

ARG BUILD_VCS_NUMBER=unknown

LABEL org.opencontainers.image.title="Babelapha Provenance Read API" \
      org.opencontainers.image.source="https://github.com/KG-khangelani/babelapha" \
      org.opencontainers.image.revision="${BUILD_VCS_NUMBER}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROVENANCE_API_PORT=8010 \
    PROVENANCE_API_OPENAPI_PATH=/app/contracts/provenance-read-api-v1.openapi.json

WORKDIR /app

COPY docker/provenance-api/requirements.txt /tmp/requirements.txt
RUN pip install --disable-pip-version-check --no-cache-dir --no-compile \
      -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY pipelines/airflow/dags/provenance.py /app/dags/provenance.py
COPY pipelines/airflow/inspect_provenance.py /app/inspect_provenance.py
COPY pipelines/airflow/provenance_api.py /app/provenance_api.py
COPY contracts/provenance-read-api-v1.openapi.json /app/contracts/provenance-read-api-v1.openapi.json

USER 65532:65532

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/ready', timeout=3).read()"]

ENTRYPOINT ["python", "/app/provenance_api.py"]
