FROM apache/airflow:3.3.1-python3.11

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg \
       awscli \
       curl \
       jq \
    && rm -rf /var/lib/apt/lists/*

RUN printf '%s\n' \
    '#!/bin/sh' \
    'exec env PYTHONNOUSERSITE=1 /usr/bin/aws "$@"' \
    > /usr/local/bin/aws \
    && chmod +x /usr/local/bin/aws

USER airflow

RUN pip install --no-cache-dir \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.3.1/constraints-3.11.txt" \
    "apache-airflow-providers-cncf-kubernetes==10.21.0" \
    "apache-airflow-providers-amazon==9.34.0"
