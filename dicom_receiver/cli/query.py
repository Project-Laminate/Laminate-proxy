#!/usr/bin/env python
"""
Command-line interface for querying DICOM metadata from the API

This CLI allows users to query the API for DICOM metadata and get de-anonymized results.
"""

import argparse
import json
import logging
from pathlib import Path

from dicom_receiver.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_STORAGE_DIR,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_FILE,
    DEFAULT_API_URL,
    DEFAULT_API_USERNAME,
    DEFAULT_API_PASSWORD,
    DEFAULT_API_TOKEN,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    ensure_dirs_exist
)
from dicom_receiver.utils.logging_config import configure_logging
from dicom_receiver.core.query import DicomQueryHandler

logger = logging.getLogger('dicom_receiver.query')

def main():
    """Main entry point for the query CLI"""
    parser = argparse.ArgumentParser(description='Query DICOM metadata from API')
    
    # Storage and data directories
    parser.add_argument('--data-dir', type=str, default=DEFAULT_DATA_DIR,
                        help=f'Base directory for all data (default/env: {DEFAULT_DATA_DIR})')
    parser.add_argument('--storage', type=str, default=DEFAULT_STORAGE_DIR,
                        help=f'Directory containing anonymization mapping (default/env: {DEFAULT_STORAGE_DIR})')
    
    # API configuration
    parser.add_argument('--api-url', type=str, default=DEFAULT_API_URL,
                        help=f'URL of the API (default/env: {DEFAULT_API_URL})')
    parser.add_argument('--api-username', type=str, default=DEFAULT_API_USERNAME,
                        help='Username for API authentication (default from env variable)')
    parser.add_argument('--api-password', type=str, default=DEFAULT_API_PASSWORD,
                        help='Password for API authentication (default from env variable)')
    parser.add_argument('--api-token', type=str, default=DEFAULT_API_TOKEN,
                        help='Token for API authentication (default from env variable)')
    
    # Retry configuration
    parser.add_argument('--max-retries', type=int, default=DEFAULT_MAX_RETRIES,
                       help=f'Maximum number of retry attempts (default/env: {DEFAULT_MAX_RETRIES})')
    parser.add_argument('--retry-delay', type=int, default=DEFAULT_RETRY_DELAY,
                       help=f'Delay in seconds between retry attempts (default/env: {DEFAULT_RETRY_DELAY})')
    
    # Logging configuration
    parser.add_argument('--log-level', type=str, default=DEFAULT_LOG_LEVEL,
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help=f'Logging level (default/env: {DEFAULT_LOG_LEVEL})')
    parser.add_argument('--log-file', type=str, default=DEFAULT_LOG_FILE,
                        help='Log to file instead of console')
    
    # Query options
    parser.add_argument('--result-id', type=str,
                        help='Query specific result by ID')
    parser.add_argument('--output', type=str,
                        help='Output file to save the results (JSON format)')
    parser.add_argument('--pretty', action='store_true',
                        help='Pretty print the JSON output')
    parser.add_argument('--show-mapping', action='store_true',
                        help='Show the anonymization mapping')
    
    args = parser.parse_args()
    
    # Ensure directories exist
    ensure_dirs_exist()
    
    # Configure logging
    log_level = getattr(logging, args.log_level)
    configure_logging(level=log_level, log_file=args.log_file)
    
    # Validate API URL
    if not args.api_url:
        logger.error("API URL is required. Set DICOM_RECEIVER_API_URL environment variable or use --api-url")
        return 1
    
    logger.info(f"Using API URL: {args.api_url}")
    logger.info(f"Using storage directory: {args.storage}")
    
    # Initialize the query handler
    try:
        query_handler = DicomQueryHandler(
            api_url=args.api_url,
            storage_dir=args.storage,
            username=args.api_username,
            password=args.api_password,
            token=args.api_token,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay
        )
    except Exception as e:
        logger.error(f"Failed to initialize query handler: {e}")
        return 1
    
    # Show anonymization mapping if requested
    if args.show_mapping:
        mapping = query_handler.get_anonymization_mapping()
        reverse_mapping = query_handler.get_reverse_anonymization_mapping()
        
        print("\n=== Anonymization Mapping ===")
        print("Original Name -> Anonymized Name:")
        for original, anonymized in mapping.items():
            print(f"  {original} -> {anonymized}")
        
        print("\nAnonymized Name -> Original Name:")
        for anonymized, original in reverse_mapping.items():
            print(f"  {anonymized} -> {original}")
        print()
    
    # Perform the query
    try:
        if args.result_id:
            logger.info(f"Querying specific result: {args.result_id}")
            result = query_handler.query_result_by_id(args.result_id)
        else:
            logger.info("Querying all DICOM metadata")
            result = query_handler.query_all_dicom_metadata()
        
        if result is None:
            logger.error("Query failed")
            return 1
        
        # Format output
        if args.pretty:
            output_text = json.dumps(result, indent=2, ensure_ascii=False)
        else:
            output_text = json.dumps(result, ensure_ascii=False)
        
        # Save to file or print to stdout
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(output_text)
            
            logger.info(f"Results saved to: {output_path}")
            
            # Also print summary to console
            if 'total_results_with_dicom' in result:
                print(f"Successfully queried {result['total_results_with_dicom']} results with DICOM data")
            elif 'result' in result:
                print(f"Successfully queried result: {result['result'].get('name', 'Unknown')}")
            else:
                print("Query completed successfully")
        else:
            print(output_text)
        
        return 0
        
    except KeyboardInterrupt:
        logger.info("Query interrupted by user")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error during query: {e}")
        return 1

if __name__ == "__main__":
    exit(main()) 