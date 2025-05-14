#!/bin/bash

if [ ! -f "docker-compose.yml" ]; then
    echo "Error: This script should be run from the project root directory (where docker-compose.yml is located)"
    exit 1
fi

mkdir -p data/storage data/zips data/keys data/logs

chmod -R 777 data

echo "Created data directories for Docker deployment:"
echo "  - ./data/storage - For DICOM files"
echo "  - ./data/zips - For zipped studies"
echo "  - ./data/keys - For encryption keys"
echo "  - ./data/logs - For log files"
echo "These directories are mounted in the Docker container as:"
echo "  - /data/storage"
echo "  - /data/zips"
echo "  - /data/keys"
echo "  - /data/logs"
echo ""
echo "You can now start the Docker container with:"
echo "  docker-compose up -d" 