#!/usr/bin/env python
"""
Command-line interface for the DICOM patient information restoration

This script restores the original patient information to anonymized DICOM files.
"""

import argparse
import logging
from pathlib import Path

from dicom_receiver.core.crypto import restore_file
from dicom_receiver.utils.logging_config import configure_logging
from dicom_receiver.config import (
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_FILE,
    print_config
)

logger = logging.getLogger('restore_patient_info')

def main():
    """Main entry point for the script"""
    parser = argparse.ArgumentParser(description='Restore patient information in DICOM files')
    parser.add_argument('anonymized_file', type=str, help='Path to the anonymized DICOM file')
    parser.add_argument('original_file', type=str, help='Path to save the restored DICOM file')
    parser.add_argument('--map-file', type=str, help='Path to the patient info map file')
    parser.add_argument('--log-level', type=str, default=DEFAULT_LOG_LEVEL,
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help=f'Logging level (default/env: {DEFAULT_LOG_LEVEL})')
    parser.add_argument('--log-file', type=str, default=DEFAULT_LOG_FILE,
                        help='Log to file instead of console')
    parser.add_argument('--show-config', action='store_true',
                        help='Print the current configuration and exit')
    
    args = parser.parse_args()
    
    if args.show_config:
        print_config()
        return 0
    
    log_level = getattr(logging, args.log_level)
    configure_logging(level=log_level, log_file=args.log_file)
    
    logger.info(f"Anonymized file: {args.anonymized_file}")
    logger.info(f"Output file: {args.original_file}")
    if args.map_file:
        logger.info(f"Map file: {args.map_file}")
    
    try:
        success = restore_file(
            args.anonymized_file,
            args.original_file,
            args.map_file
        )
        
        if success:
            logger.info(f"Successfully restored patient information to {args.original_file}")
        else:
            logger.error("Failed to restore patient information")
            return 1
    except Exception as e:
        logger.error(f"Error restoring patient information: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main()) 