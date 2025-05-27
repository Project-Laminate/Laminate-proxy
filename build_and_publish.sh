#!/bin/bash
set -e

# Build for ARM64 (Apple Silicon)
echo "Building Docker image for ARM64 architecture..."
docker build -t as18701/laminate-proxy:latest .

# You can tag with a specific version if needed
# VERSION=1.1.0
# docker tag as18701/laminate-proxy:latest as18701/laminate-proxy:$VERSION

# Push to Docker Hub
echo "Publishing to Docker Hub..."
docker push as18701/laminate-proxy:latest
# docker push as18701/laminate-proxy:$VERSION

echo "Done! Image published as as18701/laminate-proxy:latest" 