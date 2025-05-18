#!/bin/bash
set -e

# Build for ARM64 (Apple Silicon)
echo "Building Docker image for ARM64 architecture..."
docker build -t amrshadid/laminate-proxy:latest .

# You can tag with a specific version if needed
# VERSION=1.1.0
# docker tag amrshadid/laminate-proxy:latest amrshadid/laminate-proxy:$VERSION

# Push to Docker Hub
echo "Publishing to Docker Hub..."
docker push amrshadid/laminate-proxy:latest
# docker push amrshadid/laminate-proxy:$VERSION

echo "Done! Image published as amrshadid/laminate-proxy:latest" 