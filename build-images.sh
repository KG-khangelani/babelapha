#!/bin/bash
# Build and push Docker images for the media pipeline

set -e

# Configuration
REGISTRY="${DOCKER_REGISTRY:-localhost:5000}"
VERSION="${BUILD_VERSION:-latest}"

echo "Building pipeline Docker images..."
echo "Registry: $REGISTRY"
echo "Version: $VERSION"

# Build ClamAV scanner
echo "==> Building clamav scanner..."
cd docker/clamav
cp ../utils/pfs_move.py .
docker build -t ${REGISTRY}/clamav:${VERSION} -f dockerfile .
rm pfs_move.py
echo "✓ Built ${REGISTRY}/clamav:${VERSION}"

# Build validator
echo "==> Building media validator..."
cd ../validate
cp ../utils/pfs_move.py .
docker build -t ${REGISTRY}/validate:${VERSION} -f dockerfile .
rm pfs_move.py
echo "✓ Built ${REGISTRY}/validate:${VERSION}"

# Build transcoder
echo "==> Building transcoder..."
cd ../transcode
docker build -t ${REGISTRY}/transcode:${VERSION} -f dockerfile .
echo "✓ Built ${REGISTRY}/transcode:${VERSION}"

cd ../..

# Push images if requested
if [ "$PUSH_IMAGES" = "true" ]; then
    echo ""
    echo "Pushing images to registry..."
    docker push ${REGISTRY}/clamav:${VERSION}
    docker push ${REGISTRY}/validate:${VERSION}
    docker push ${REGISTRY}/transcode:${VERSION}
    echo "✓ All images pushed"
fi

echo ""
echo "Build complete!"
echo "Images:"
echo "  - ${REGISTRY}/clamav:${VERSION}"
echo "  - ${REGISTRY}/validate:${VERSION}"
echo "  - ${REGISTRY}/transcode:${VERSION}"
