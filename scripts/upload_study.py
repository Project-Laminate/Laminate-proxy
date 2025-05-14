#!/usr/bin/env python
"""
Script to manually zip and upload a DICOM study to the API

This script can be used to upload a study that was previously received
but not automatically uploaded.
"""

import argparse
import logging
import sys
from pathlib import Path

from dicom_receiver.core.uploader import ApiUploader
from dicom_receiver.utils.logging_config import configure_logging
from dicom_receiver.config import (
    DEFAULT_API_URL,
    DEFAULT_API_USERNAME,
    DEFAULT_API_PASSWORD,
    DEFAULT_API_TOKEN,
    DEFAULT_ZIP_DIR,
    DEFAULT_CLEANUP_AFTER_UPLOAD,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    print_config
)

logger = logging.getLogger('upload_study')

def main():
    """Main entry point for the script"""
    parser = argparse.ArgumentParser(description='Upload a DICOM study to the API')
    parser.add_argument('study_dir', type=str, help='Path to the study directory')
    parser.add_argument('--api-url', type=str, default=DEFAULT_API_URL,
                        help=f'URL of the API (default/env: {DEFAULT_API_URL})')
    parser.add_argument('--api-username', type=str, default=DEFAULT_API_USERNAME,
                        help='Username for API authentication (default from env variable)')
    parser.add_argument('--api-password', type=str, default=DEFAULT_API_PASSWORD,
                        help='Password for API authentication (default from env variable)')
    parser.add_argument('--api-token', type=str, default=DEFAULT_API_TOKEN,
                        help='Token for API authentication (default from env variable)')
    parser.add_argument('--zip-dir', type=str, default=DEFAULT_ZIP_DIR,
                        help=f'Directory to store zipped study (default/env: {DEFAULT_ZIP_DIR})')
    parser.add_argument('--cleanup-after-upload', action='store_true', default=DEFAULT_CLEANUP_AFTER_UPLOAD,
                        help=f'Remove files after successful upload (default/env: {DEFAULT_CLEANUP_AFTER_UPLOAD})')
    parser.add_argument('--max-retries', type=int, default=DEFAULT_MAX_RETRIES,
                        help=f'Maximum number of retry attempts for API operations (default/env: {DEFAULT_MAX_RETRIES})')
    parser.add_argument('--retry-delay', type=int, default=DEFAULT_RETRY_DELAY,
                        help=f'Delay in seconds between retry attempts (default/env: {DEFAULT_RETRY_DELAY})')
    parser.add_argument('--log-level', type=str, default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help='Logging level (default: INFO)')
    parser.add_argument('--show-config', action='store_true',
                        help='Print the current configuration and exit')
    
    args = parser.parse_args()
    
    # If --show-config is specified, print config and exit
    if args.show_config:
        print_config()
        return 0
    
    # Configure logging
    log_level = getattr(logging, args.log_level)
    configure_logging(level=log_level)
    
    # Check if study directory exists
    study_path = Path(args.study_dir)
    if not study_path.exists() or not study_path.is_dir():
        logger.error(f"Study directory not found: {args.study_dir}")
        return 1
    
    # Create zip directory if it doesn't exist
    zip_dir = Path(args.zip_dir)
    zip_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize the API uploader
    uploader = ApiUploader(
        api_url=args.api_url,
        username=args.api_username,
        password=args.api_password,
        token=args.api_token,
        cleanup_after_upload=args.cleanup_after_upload,
        max_retries=args.max_retries,
        retry_delay=args.retry_delay
    )
    
    logger.info(f"Configured with retry mechanism: max_retries={args.max_retries}, retry_delay={args.retry_delay}s")
    
    # Zip the study
    study_name = study_path.name
    zip_path = zip_dir / f"{study_name}.zip"
    
    logger.info(f"Zipping study: {study_path}")
    zip_file = uploader.zip_study(str(study_path), str(zip_path))
    
    if not zip_file:
        logger.error("Failed to create zip file")
        return 1
    
    logger.info(f"Successfully created zip file: {zip_file}")
    
    # Authenticate with the API if token not provided
    if not uploader.auth_token:
        logger.info(f"Authenticating with API at {args.api_url}")
        if not uploader.login():
            logger.error("Authentication failed")
            return 1
    
    # Upload the study
    logger.info(f"Uploading study to {args.api_url}")
    success, response_data = uploader.upload_study(
        zip_file, 
        study_info={
            'name': study_name,
        },
        study_dir=str(study_path) if args.cleanup_after_upload else None
    )
    
    if success:
        logger.info("Upload successful")
        if response_data and 'id' in response_data:
            logger.info(f"Dataset ID: {response_data.get('id')}")
        if args.cleanup_after_upload:
            logger.info(f"Cleaned up files for study: {study_path.name}")
        return 0
    else:
        logger.error("Upload failed")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 