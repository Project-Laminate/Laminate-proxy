# Docker Setup for DICOM Receiver

This guide explains how to run the DICOM Receiver application using Docker.

## Prerequisites

- Docker and Docker Compose installed on your system
- Basic knowledge of Docker and containerization

## Quick Start

1. Copy the environment configuration template to create your `.env` file:

```bash
cp .env.example .env
```

2. Edit the `.env` file to customize your configuration:

```bash
# Set your API credentials from https://dev-laminate.nyuad.nyu.edu/
DICOM_RECEIVER_API_USERNAME=your_username
DICOM_RECEIVER_API_PASSWORD=your_password

# Enable auto-upload if desired
DICOM_RECEIVER_AUTO_UPLOAD=true
```
3. Edit the `data/storage/nodes.json` file to customize the configuration of your PACS.

4. Build and start the Docker container:

```bash
docker-compose up -d
```

4. Check the logs to verify everything is working:

```bash
docker-compose logs -f
```

---

## Data Persistence

The application uses Docker volumes to persist data:

- `dicom-storage`: Stores received DICOM files
- `dicom-zips`: Stores zipped studies ready for upload

You can view these volumes with:

```bash
docker volume ls
```

## Using the Application

The DICOM receiver will be listening on port *DICOM_RECEIVER_PORT* of your host machine. Configure your DICOM sender (e.g., PACS, modality) to send images to this port.

## Common Operations

### Restart the service

```bash
docker-compose restart
```

### Stop the service

```bash
docker-compose down
```

### View logs

```bash
docker-compose logs -f
```

### Execute commands inside the container

```bash
# Show current configuration
docker-compose exec dicom-receiver dicom-config

# Manually upload a study
docker-compose exec dicom-receiver upload_study.py /data/storage/STUDY_UID
```

### Access the shell inside the container

```bash
docker-compose exec dicom-receiver /bin/bash
```

## Rebuilding after Code Changes

If you make changes to the code, rebuild the container:

```bash
docker-compose down
docker-compose build
docker-compose up -d
```

## Troubleshooting

### Connection issues

If clients can't connect to the DICOM receiver:

1. Verify the container is running:
   ```bash
   docker-compose ps
   ```

2. Check if the port is exposed correctly:
   ```bash
   docker-compose port dicom-receiver 11112
   ```

3. Check the application logs:
   ```bash
   docker-compose logs -f dicom-receiver
   ``` 