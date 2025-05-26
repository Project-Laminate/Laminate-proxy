#!/usr/bin/env python
"""
Command-line interface for the DICOM receiver

This is the main entry point for starting the DICOM receiver service.
"""

import argparse
import logging
import json
from pathlib import Path

from dicom_receiver.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_PORT,
    DEFAULT_AE_TITLE,
    DEFAULT_STORAGE_DIR,
    DEFAULT_TIMEOUT,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_FILE,
    DEFAULT_API_URL,
    DEFAULT_API_USERNAME,
    DEFAULT_API_PASSWORD,
    DEFAULT_API_TOKEN,
    DEFAULT_AUTO_UPLOAD,
    DEFAULT_ZIP_DIR,
    DEFAULT_CLEANUP_AFTER_UPLOAD,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    PATIENT_INFO_MAP_FILENAME,
    print_config,
    ensure_dirs_exist
)
from dicom_receiver.utils.logging_config import configure_logging
from dicom_receiver.core.crypto import DicomAnonymizer
from dicom_receiver.core.storage import DicomStorage, StudyMonitor
from dicom_receiver.core.scp import DicomServiceProvider

logger = logging.getLogger('dicom_receiver')

def main():
    """Main entry point for the script"""
    parser = argparse.ArgumentParser(description='DICOM Receiver Service')
    parser.add_argument('--data-dir', type=str, default=DEFAULT_DATA_DIR,
                        help=f'Base directory for all data (default/env: {DEFAULT_DATA_DIR})')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, 
                        help=f'Port to listen on (default/env: {DEFAULT_PORT})')
    parser.add_argument('--storage', type=str, default=DEFAULT_STORAGE_DIR,
                        help=f'Directory to store received DICOM files (default/env: {DEFAULT_STORAGE_DIR})')
    parser.add_argument('--ae-title', type=str, default=DEFAULT_AE_TITLE.decode(),
                        help=f'AE Title for this SCP (default/env: {DEFAULT_AE_TITLE.decode()})')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT,
                        help=f'Timeout in seconds after receiving the last file in a study (default/env: {DEFAULT_TIMEOUT})')

    parser.add_argument('--log-level', type=str, default=DEFAULT_LOG_LEVEL,
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help=f'Logging level (default/env: {DEFAULT_LOG_LEVEL})')
    parser.add_argument('--log-file', type=str, default=DEFAULT_LOG_FILE,
                        help='Log to file instead of console')
    
    parser.add_argument('--api-url', type=str, default=DEFAULT_API_URL,
                        help=f'URL of the API for uploading studies (default/env: {DEFAULT_API_URL})')
    parser.add_argument('--api-username', type=str, default=DEFAULT_API_USERNAME,
                        help='Username for API authentication (default from env variable)')
    parser.add_argument('--api-password', type=str, default=DEFAULT_API_PASSWORD,
                        help='Password for API authentication (default from env variable)')
    parser.add_argument('--api-token', type=str, default=DEFAULT_API_TOKEN,
                        help='Token for API authentication (default from env variable)')
    parser.add_argument('--auto-upload', action='store_true', default=DEFAULT_AUTO_UPLOAD,
                        help=f'Automatically upload studies when complete (default/env: {DEFAULT_AUTO_UPLOAD})')
    parser.add_argument('--zip-dir', type=str, default=DEFAULT_ZIP_DIR,
                        help=f'Directory to store zipped studies (default/env: {DEFAULT_ZIP_DIR})')
    parser.add_argument('--cleanup-after-upload', action='store_true', default=DEFAULT_CLEANUP_AFTER_UPLOAD,
                        help=f'Remove files after successful upload (default/env: {DEFAULT_CLEANUP_AFTER_UPLOAD})')
    
    parser.add_argument('--max-retries', type=int, default=DEFAULT_MAX_RETRIES,
                       help=f'Maximum number of retry attempts for API operations (default/env: {DEFAULT_MAX_RETRIES})')
    parser.add_argument('--retry-delay', type=int, default=DEFAULT_RETRY_DELAY,
                       help=f'Delay in seconds between retry attempts (default/env: {DEFAULT_RETRY_DELAY})')
    
    parser.add_argument('--show-config', action='store_true',
                        help='Print the current configuration and exit')
                        
    parser.add_argument('--migrate', action='store_true',
                       help='Migrate existing storage to patient/study/series/scans structure')
    
    args = parser.parse_args()
    
    if args.show_config:
        print_config()
        return
    
    ensure_dirs_exist()
    
    log_level = getattr(logging, args.log_level)
    configure_logging(level=log_level, log_file=args.log_file)
    
    logger.info(f"Data directory: {DEFAULT_DATA_DIR}")
    logger.info(f"Port: {args.port}")
    logger.info(f"Storage directory: {args.storage}")
    logger.info(f"AE Title: {args.ae_title}")
    logger.info(f"Timeout: {args.timeout}")

    if args.log_file:
        logger.info(f"Log file: {args.log_file}")
    
    if args.auto_upload:
        logger.info(f"Auto-upload enabled with API URL: {args.api_url}")
        logger.info(f"Zip directory: {args.zip_dir}")
        if args.cleanup_after_upload:
            logger.info("Cleanup after upload is enabled")
        logger.info(f"Upload retry mechanism: max_retries={args.max_retries}, retry_delay={args.retry_delay}s")
    
    storage = DicomStorage(args.storage)
    anonymizer = DicomAnonymizer(Path(args.storage))
    
    # Handle migration if requested
    if args.migrate:
        logger.info("Starting migration to patient/study/series/scans structure...")
        
        # Try to load the patient_study_map from the encryption mapping file
        patient_study_map = None
        map_file_path = Path(args.storage) / PATIENT_INFO_MAP_FILENAME
        
        if map_file_path.exists():
            try:
                with open(map_file_path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict) and 'patient_study_map' in data:
                        patient_study_map = data['patient_study_map']
                        logger.info(f"Loaded patient-study mapping for {len(patient_study_map)} patients")
            except Exception as e:
                logger.error(f"Error loading patient-study map: {e}")
        
        # Perform the migration
        storage.migrate_to_patient_structure(patient_study_map)
        logger.info("Migration complete. Exiting.")
        return
    
    # Continue with normal operation
    study_monitor = StudyMonitor(args.timeout)
    
    dicom_scp = DicomServiceProvider(
        storage=storage,
        study_monitor=study_monitor,
        encryptor=anonymizer,
        port=args.port,
        ae_title=args.ae_title.encode(),
        api_url=args.api_url,
        api_username=args.api_username,
        api_password=args.api_password,
        api_token=args.api_token,
        auto_upload=args.auto_upload,
        zip_dir=args.zip_dir,
        cleanup_after_upload=args.cleanup_after_upload,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay
    )
    
    logger.info(f"Starting DICOM receiver with storage directory: {args.storage}")
    dicom_scp.start()

if __name__ == "__main__":
    main() 