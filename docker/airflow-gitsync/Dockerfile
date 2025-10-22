FROM alpine:3.19

RUN apk add --no-cache \
    bash \
    git \
    curl \
    kubectl \
    ca-certificates

WORKDIR /workspace

COPY sync-to-airflow.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/sync-to-airflow.sh

ENTRYPOINT ["/usr/local/bin/sync-to-airflow.sh"]
