FROM alpine:3.19

# Install dependencies
RUN apk add --no-cache \
    bash \
    git \
    curl \
    tar \
    ca-certificates

# Install pachctl
ARG PACH_VERSION=2.8.0
RUN curl -o /tmp/pachctl.tar.gz -L \
    https://github.com/pachyderm/pachyderm/releases/download/v${PACH_VERSION}/pachctl_${PACH_VERSION}_linux_amd64.tar.gz && \
    tar -xzf /tmp/pachctl.tar.gz -C /tmp && \
    mv /tmp/pachctl_${PACH_VERSION}_linux_amd64/pachctl /usr/local/bin/ && \
    chmod +x /usr/local/bin/pachctl && \
    rm -rf /tmp/pachctl*

# Create working directory
WORKDIR /workspace

# Copy sync script
COPY sync-to-pachyderm.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/sync-to-pachyderm.sh

ENTRYPOINT ["/usr/local/bin/sync-to-pachyderm.sh"]
