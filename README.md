# DICOM Receiver

A secure DICOM receiver service for hospital use that receives DICOM images, organizes them by study/series, anonymizes patient information, and uploads completed studies to a remote API.

## Features

- Receives DICOM images from PACS and modalities
- Organizes files by study and series in a structured storage
- Anonymizes patient information for privacy compliance (replaces PII with "ANON" and uses sequential patient naming like "sub-001")
- Provides tools to restore original patient information when needed
- Automatic study completion detection with configurable timeout
- Zips completed studies automatically
- Uploads completed studies to a configurable API endpoint
- Handles multiple concurrent DICOM connections
- Thread-safe upload operations with retry mechanism
- Automatic cleanup of transmitted data
- Command-line tools for all operations

## Installation

```bash
# Install from the repository
pip install -e .
```

## Configuration

The application supports a flexible configuration system with three levels of precedence:
1. Environment variables (highest precedence)
2. Command-line arguments
3. Default values (lowest precedence)

### Environment Variables

#### Basic Configuration
- `DICOM_RECEIVER_PORT` - Port to listen on (default: 11112)
- `DICOM_RECEIVER_AE_TITLE` - AE Title for the DICOM SCP (default: DICOMRCV)
- `DICOM_RECEIVER_STORAGE_DIR` - Directory to store received DICOM files (default: storage)
- `DICOM_RECEIVER_TIMEOUT` - Timeout in seconds for study completion detection (default: 60)

- `DICOM_RECEIVER_LOG_LEVEL` - Logging level (default: INFO)
- `DICOM_RECEIVER_LOG_FILE` - Log file path (default: None, logs to console)

#### API Integration
- `DICOM_RECEIVER_API_URL` - URL of the API (default: http://localhost:8000/api)
- `DICOM_RECEIVER_API_USERNAME` - Username for API authentication
- `DICOM_RECEIVER_API_PASSWORD` - Password for API authentication
- `DICOM_RECEIVER_API_TOKEN` - Existing token for API authentication (optional)
- `DICOM_RECEIVER_AUTO_UPLOAD` - Enable automatic upload (true/false, default: false)
- `DICOM_RECEIVER_ZIP_DIR` - Directory to store zipped studies (default: zips)
- `DICOM_RECEIVER_CLEANUP_AFTER_UPLOAD` - Remove files after successful upload (true/false, default: false)

#### Performance and Reliability
- `DICOM_RECEIVER_MAX_RETRIES` - Maximum number of retry attempts for API operations (default: 3)
- `DICOM_RECEIVER_RETRY_DELAY` - Delay in seconds between retry attempts (default: 5)

## Usage

### Starting the DICOM Receiver

```bash
# Start with default settings
dicom-receiver

# Start with custom settings
dicom-receiver --port 11112 --storage /path/to/storage --ae-title MYAETITLE

# Start with automatic upload to API
dicom-receiver --auto-upload --api-url http://example.com/api --api-username user --api-password pass

# Configure performance and reliability
dicom-receiver --max-connections 20 --max-retries 5 --retry-delay 10 --cleanup-after-upload
```

### Restoring Patient Information

```bash
# Restore patient information in a DICOM file
dicom-restore anonymized_file.dcm restored_file.dcm --map-file patient_info_map.json
```

### Manually Uploading a Study

```bash
# Upload a study that wasn't automatically uploaded
upload_study.py /path/to/study --api-url http://example.com/api --api-username user --api-password pass

# Upload with automatic cleanup and retry options
upload_study.py /path/to/study --cleanup-after-upload --max-retries 5 --retry-delay 10
```

### Viewing Configuration

```bash
# View current configuration
dicom_config.py
```

## API Integration Details

When a study is completed (determined by a configurable timeout after receiving the last file), the system:

1. Creates a zip file containing all the DICOM files in the study
2. Authenticates with the API server using either:
   - Username and password, which returns an access token
   - A provided API token
3. Uploads the zip file to the API endpoint using the token for authentication
4. Optionally removes the zip file and original DICOM files after successful upload

### API Authentication

The authentication endpoint (`/users/login/`) expects a request like:

```json
{
  "username": "username",
  "password": "password"
}
```

And returns a response like:

```json
{
  "access": "JWT_ACCESS_TOKEN",
  "refresh": "JWT_REFRESH_TOKEN",
  "user": {
    "id": 1,
    "email": "user@example.com",
    "username": "username",
    "first_name": "First",
    "last_name": "Last",
    "full_name": "First Last",
    "date_joined": "2025-05-06T17:18:01.724455Z",
    "is_active": true,
    "is_superuser": false
  }
}
```

### API Upload

The upload endpoint (`/data/upload/`) expects a multipart form request with:
- `file`: The zip file containing the study
- Authentication header: `Authorization: Bearer JWT_ACCESS_TOKEN`

## Reliability Features

### Concurrent Connection Handling
The DICOM receiver uses a non-blocking server model that can handle multiple incoming DICOM connections simultaneously. This is especially important in hospital environments where multiple modalities may be sending studies concurrently.

### Thread Safety
All operations including authentication, uploads, and file management are thread-safe, ensuring data integrity even under high load conditions.

### Retry Mechanism
The system includes an intelligent retry mechanism for API operations:
- Configurable maximum retry attempts and delay between retries
- Exponential backoff for progressive delays
- Smart retry logic (e.g., client errors are not retried, authentication failures trigger token refresh)
- Proper error handling with detailed logging

### Automatic Cleanup
When enabled, the system automatically removes zip files and original DICOM files after successful upload to the API, helping to prevent disk space issues in long-running deployments.

## Docker Support

The application can be run in a Docker container for easy deployment. See the Docker-specific documentation in `README-docker.md`.

## Architecture


- **Core Components**
  - `storage.py` - Handles file storage and study completion detection
  - `crypto.py` - Handles anonymization/restoration of patient information
  - `scp.py` - DICOM Service Class Provider implementation
  - `uploader.py` - API authentication and study upload functionality

- **Command-line Interfaces**
  - `receiver.py` - Main entry point for the DICOM receiver
  - `restore.py` - Tool for restoring patient information

- **Utility Scripts**
  - `dicom_receiver_start.py` - Script to start the receiver
  - `restore_dicom_info.py` - Script to restore DICOM information
  - `dicom_config.py` - Script to display current configuration
  - `upload_study.py` - Script to manually upload a study to the API