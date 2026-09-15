FROM apache/airflow:3.1.1-python3.11

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
    "apache-airflow-providers-cncf-kubernetes==10.9.0"
