FROM alpine:3.24.1

RUN apk add --no-cache \
    bash \
    git \
    python3 \
    curl \
    kubectl \
    ca-certificates

WORKDIR /workspace

COPY sync-to-airflow.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/sync-to-airflow.sh

ENTRYPOINT ["/usr/local/bin/sync-to-airflow.sh"]
