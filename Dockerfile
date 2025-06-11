FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Install the application
RUN pip install -e .

# Create necessary directories
RUN mkdir -p /data/storage /data/zips /data/logs

# Expose the DICOM port
EXPOSE ${DICOM_RECEIVER_PORT}

# Set environment variables
ENV DICOM_RECEIVER_STORAGE_DIR=/data/storage
ENV DICOM_RECEIVER_ZIP_DIR=/data/zips
ENV PYTHONUNBUFFERED=1
ENV DICOM_RECEIVER_CLEANUP_AFTER_UPLOAD=true

# Run the DICOM receiver
CMD ["dicom-receiver"]
