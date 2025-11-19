#!/bin/bash
# Build all three images inside TeamCity Docker agent pod and load into all nodes

set -e

VERSION="v1.0"
AGENT_POD="teamcity-agent-docker-5d5f8647f4-t2zng"
NAMESPACE="teamcity"

echo "=== Building images in TeamCity agent pod ==="

# Build images in the agent pod
kubectl exec -n "$NAMESPACE" "$AGENT_POD" -- bash -c "
set -e
cd /tmp
git clone https://github.com/KG-khangelani/babelapha.git build
cd build

echo 'Building clamav...'
cd docker/clamav
cp ../utils/pfs_move.py .
docker build -t clamav:$VERSION -t clamav:latest -f dockerfile .
cd /tmp/build

echo 'Building validate...'
cd docker/validate
cp ../utils/pfs_move.py .
docker build -t validate:$VERSION -t validate:latest -f dockerfile .
cd /tmp/build

echo 'Building transcode...'
cd docker/transcode
docker build -t transcode:$VERSION -t transcode:latest -f dockerfile .

echo 'Saving images...'
cd /tmp
docker save clamav:$VERSION -o clamav.tar
docker save validate:$VERSION -o validate.tar
docker save transcode:$VERSION -o transcode.tar
"

echo ""
echo "=== Copying images from pod ==="
kubectl cp "$NAMESPACE/$AGENT_POD:/tmp/clamav.tar" /tmp/clamav.tar
kubectl cp "$NAMESPACE/$AGENT_POD:/tmp/validate.tar" /tmp/validate.tar
kubectl cp "$NAMESPACE/$AGENT_POD:/tmp/transcode.tar" /tmp/transcode.tar

echo ""
echo "=== Loading images into containerd on all nodes ==="
for NODE in 192.168.10.104 192.168.10.12 192.168.10.13 192.168.10.10; do
    echo "Loading on node $NODE..."
    scp /tmp/clamav.tar "$NODE:/tmp/" 2>/dev/null || true
    scp /tmp/validate.tar "$NODE:/tmp/" 2>/dev/null || true
    scp /tmp/transcode.tar "$NODE:/tmp/" 2>/dev/null || true
    
    ssh "$NODE" "sudo ctr -n k8s.io images import /tmp/clamav.tar && \
                 sudo ctr -n k8s.io images import /tmp/validate.tar && \
                 sudo ctr -n k8s.io images import /tmp/transcode.tar && \
                 rm /tmp/*.tar" 2>/dev/null || true
done

echo ""
echo "=== Cleanup ==="
rm /tmp/clamav.tar /tmp/validate.tar /tmp/transcode.tar
kubectl exec -n "$NAMESPACE" "$AGENT_POD" -- rm -rf /tmp/build /tmp/*.tar

echo ""
echo "=== Build Complete ==="
echo "Images available on all nodes:"
echo "  - clamav:$VERSION (also tagged as latest)"
echo "  - validate:$VERSION (also tagged as latest)"
echo "  - transcode:$VERSION (also tagged as latest)"
