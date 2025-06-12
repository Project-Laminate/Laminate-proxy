# Local Setup for DICOM Receiver

This guide explains how to run the DICOM Receiver application using a local conda environment for hospital computers that don't have Docker but may have Podman or need to run without containers.

**Before you start:** Create an account on https://dev-laminate.nyuad.nyu.edu/

## Quick Start

1. Create a new conda environment with Python 3.7 or higher:

```bash
conda create -n laminate-proxy python=3.11
conda activate laminate-proxy
```

2. Install the required dependencies:

```bash
pip install -r requirements.txt
```

3. Install the Laminate-proxy package in development mode:

```bash
pip install -e .
```

4. Create the necessary data directories:

```bash
mkdir -p data/storage data/zips data/logs
```

5. Copy the local environment configuration template to create your `.env` file:

```bash
cp .env.example-local .env
```

6. Edit the `.env` file to customize your configuration:

```bash
# Set your API credentials from https://dev-laminate.nyuad.nyu.edu/
DICOM_RECEIVER_API_USERNAME=your_username
DICOM_RECEIVER_API_PASSWORD=your_password

# Enable auto-upload if desired
DICOM_RECEIVER_AUTO_UPLOAD=true
```

7. Source the environment variables to load them into your current session:

```bash
set -a && source .env && set +a
```

8. Edit the `data/storage/nodes.json` file to customize the configuration of your PACS.

9. Start the DICOM receiver:

```bash
dicom-receiver
```

10. Check the logs to verify everything is working:

```bash
tail -f ./data/logs/dicom_receiver.log
```

11. Setup Laminate DICOM Receiver on your PACS with the settings from the `.env` file

---

## Data Persistence

The application stores data in the local `data/` directory within your project:

- `data/storage/`: Stores received DICOM files
- `data/zips/`: Stores zipped studies ready for upload
- `data/logs/`: Stores application logs

## Using the Application

The DICOM receiver will be listening on the port specified in your `.env` file (default: 11112) on your local machine. Configure your DICOM sender (e.g., PACS, modality) to send images to this port.

## Common Operations

### Start the service

```bash
# Activate the conda environment first
conda activate laminate-proxy

# Source environment variables
set -a && source .env && set +a

# Start the service in foreground
dicom-receiver

# Start the service in background (similar to docker-compose -d)
nohup dicom-receiver > ./data/logs/dicom_receiver.log 2>&1 &
```

### Stop the service

```bash
# Find the process
ps aux | grep dicom-receiver

# Kill the process
kill <PID>

# Or if running in foreground, use Ctrl+C
```

### Check if service is running

```bash
# Check if the port is listening
netstat -an | grep 11112

# Check the process
ps aux | grep dicom-receiver
```

### View logs

```bash
# View real-time logs
tail -f ./data/logs/dicom_receiver.log

# View recent logs
tail -n 100 ./data/logs/dicom_receiver.log
```

### Execute commands

```bash
# Activate environment first
conda activate laminate-proxy

# Source environment variables
set -a && source .env && set +a

# Show current configuration
dicom-config

# Manually upload a study
dicom-upload ./data/storage/STUDY_UID

# Query API for results
dicom-query --pretty

# Manage DICOM nodes
dicom-nodes --list
```

## Rebuilding after Code Changes

If you make changes to the code, reinstall the package:

```bash
conda activate laminate-proxy
pip install -e .
```

## Environment Management

### Activate the environment

```bash
conda activate laminate-proxy
```

### Deactivate the environment

```bash
conda deactivate
```

### Update dependencies

```bash
conda activate laminate-proxy
pip install --upgrade pynetdicom pydicom requests orjson
```

### Remove the environment (if needed)

```bash
conda deactivate
conda remove -n laminate-proxy --all
```

## Troubleshooting

### Connection issues

If clients can't connect to the DICOM receiver:

1. Verify the service is running:
   ```bash
   ps aux | grep dicom-receiver
   ```

2. Check if the port is listening:
   ```bash
   netstat -an | grep 11112
   # or
   lsof -i :11112
   ```

3. Check the application logs:
   ```bash
   tail -f ./data/logs/dicom_receiver.log
   ```

4. Verify firewall settings (if applicable):
   ```bash
   # On macOS
   sudo pfctl -sr | grep 11112
   
   # On Linux
   sudo iptables -L | grep 11112
   ```

### Permission issues

If you get permission errors:

1. Ensure the data directories are writable:
   ```bash
   chmod -R 755 data/
   ```

2. Check if the port is available (ports < 1024 require sudo):
   ```bash
   # If using port < 1024, run with sudo
   sudo dicom-receiver
   ```

### Python environment issues

If you get import errors:

1. Ensure you're in the correct conda environment:
   ```bash
   conda activate laminate-proxy
   which python
   which dicom-receiver
   ```

2. Reinstall the package:
   ```bash
   pip install -e .
   ```

### Performance considerations

For hospital environments:

1. **Background service**: Run as a background service for continuous operation
2. **Log rotation**: Consider setting up log rotation for long-term deployments
3. **Monitoring**: Monitor disk space in the `data/` directory
4. **Backup**: Regularly backup the `data/storage/patient_info_map.json` file

### Running as a system service (optional)

For production use, you may want to run the service as a system service:

1. Create a systemd service file (Linux):
   ```bash
   sudo nano /etc/systemd/system/laminate-proxy.service
   ```

2. Add service configuration:
   ```ini
   [Unit]
   Description=Laminate DICOM Receiver
   After=network.target

   [Service]
   Type=simple
   User=your_username
   WorkingDirectory=/path/to/Laminate-proxy
   Environment=PATH=/path/to/conda/envs/laminate-proxy/bin
   ExecStart=/path/to/conda/envs/laminate-proxy/bin/dicom-receiver
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

3. Enable and start the service:
   ```bash
   sudo systemctl enable laminate-proxy
   sudo systemctl start laminate-proxy
   sudo systemctl status laminate-proxy
   ``` 