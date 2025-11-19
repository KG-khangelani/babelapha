#!/bin/bash
# Build Docker images on a Kubernetes node and load into containerd
# Run this script on any node in the cluster

set -e

VERSION="${1:-latest}"
BUILD_DIR="/tmp/pipeline-build-$(date +%Y%m%d-%H%M%S)"

echo "=== Building Pipeline Images ==="
echo "Version: $VERSION"
echo "Build directory: $BUILD_DIR"
echo ""

# Clone repository
echo "[1/5] Cloning repository..."
git clone https://github.com/KG-khangelani/babelapha.git "$BUILD_DIR"
cd "$BUILD_DIR"

# Build ClamAV image
echo "[2/5] Building clamav:$VERSION..."
cd docker/clamav
cp ../utils/pfs_move.py .
docker build -t "clamav:$VERSION" -t "clamav:latest" -f dockerfile .
cd "$BUILD_DIR"

# Build Validate image
echo "[3/5] Building validate:$VERSION..."
cd docker/validate
cp ../utils/pfs_move.py .
docker build -t "validate:$VERSION" -t "validate:latest" -f dockerfile .
cd "$BUILD_DIR"

# Build Transcode image
echo "[4/5] Building transcode:$VERSION..."
cd docker/transcode
docker build -t "transcode:$VERSION" -t "transcode:latest" -f dockerfile .
cd "$BUILD_DIR"

# Load into containerd
echo "[5/5] Loading images into containerd..."
docker save "clamav:$VERSION" | sudo ctr -n k8s.io images import /dev/stdin
docker save "validate:$VERSION" | sudo ctr -n k8s.io images import /dev/stdin
docker save "transcode:$VERSION" | sudo ctr -n k8s.io images import /dev/stdin

# Cleanup
echo "Cleaning up..."
cd /tmp
rm -rf "$BUILD_DIR"
docker image prune -f

echo ""
echo "=== Build Complete ==="
echo "Images built and loaded into containerd:"
echo "  - clamav:$VERSION (also tagged as latest)"
echo "  - validate:$VERSION (also tagged as latest)"
echo "  - transcode:$VERSION (also tagged as latest)"
echo ""
echo "To distribute to other nodes, run:"
echo "  ctr -n k8s.io images export /tmp/clamav.tar clamav:$VERSION"
echo "  scp /tmp/clamav.tar node:/tmp/"
echo "  ssh node 'sudo ctr -n k8s.io images import /tmp/clamav.tar'"
