#!/usr/bin/env python
"""
Configuration module for the DICOM receiver

Contains default settings and configuration options with environment variable support
"""

import os
from pathlib import Path

# Helper function to get config values from environment variables with fallbacks
def get_env_or_default(env_name, default_value):
    """Get environment variable value or return default if not set"""
    return os.environ.get(env_name, default_value)

# Base data directory for all persistent data
DEFAULT_DATA_DIR = get_env_or_default('DICOM_RECEIVER_DATA_DIR', 'data')

# Create path helper function
def get_data_path(subpath):
    """Get a path relative to the base data directory"""
    return os.path.join(DEFAULT_DATA_DIR, subpath)

# Default settings with environment variable support
DEFAULT_PORT = int(get_env_or_default('DICOM_RECEIVER_PORT', 11112))
DEFAULT_AE_TITLE = get_env_or_default('DICOM_RECEIVER_AE_TITLE', 'DICOMRCV').encode()
DEFAULT_STORAGE_DIR = get_env_or_default('DICOM_RECEIVER_STORAGE_DIR', get_data_path('storage'))
DEFAULT_TIMEOUT = int(get_env_or_default('DICOM_RECEIVER_TIMEOUT', 60))  # seconds
DEFAULT_KEY_FILE = get_env_or_default('DICOM_RECEIVER_KEY_FILE', get_data_path('keys/encryption_key.key'))
DEFAULT_LOG_LEVEL = get_env_or_default('DICOM_RECEIVER_LOG_LEVEL', 'INFO')
DEFAULT_LOG_FILE = get_env_or_default('DICOM_RECEIVER_LOG_FILE', get_data_path('logs/dicom_receiver.log'))

# API related settings
DEFAULT_API_URL = get_env_or_default('DICOM_RECEIVER_API_URL', 'http://localhost:8000/api')
DEFAULT_API_USERNAME = get_env_or_default('DICOM_RECEIVER_API_USERNAME', None)
DEFAULT_API_PASSWORD = get_env_or_default('DICOM_RECEIVER_API_PASSWORD', None)
DEFAULT_API_TOKEN = get_env_or_default('DICOM_RECEIVER_API_TOKEN', None)
DEFAULT_AUTO_UPLOAD = get_env_or_default('DICOM_RECEIVER_AUTO_UPLOAD', 'false').lower() == 'true'
DEFAULT_ZIP_DIR = get_env_or_default('DICOM_RECEIVER_ZIP_DIR', get_data_path('zips'))
DEFAULT_CLEANUP_AFTER_UPLOAD = get_env_or_default('DICOM_RECEIVER_CLEANUP_AFTER_UPLOAD', 'false').lower() == 'true'

# Retry mechanism settings
DEFAULT_MAX_RETRIES = int(get_env_or_default('DICOM_RECEIVER_MAX_RETRIES', 3))
DEFAULT_RETRY_DELAY = int(get_env_or_default('DICOM_RECEIVER_RETRY_DELAY', 5))

# Configure which patient information fields to encrypt
# Environment variable format: comma-separated list of tags to encrypt
ENV_PII_TAGS = get_env_or_default('DICOM_RECEIVER_PII_TAGS', None)
DEFAULT_PII_TAGS = [
    'PatientName', 
    'PatientID', 
    'PatientBirthDate', 
    'PatientAddress', 
    'PatientTelephoneNumbers',
    'OtherPatientIDs', 
    'OtherPatientNames'
]

PII_TAGS = ENV_PII_TAGS.split(',') if ENV_PII_TAGS else DEFAULT_PII_TAGS

PATIENT_INFO_MAP_FILENAME = get_env_or_default('DICOM_RECEIVER_MAP_FILENAME', get_data_path('patient_info_map.json'))

# Helper functions for configuration
def get_config_dict():
    """Return a dictionary with all configuration values"""
    return {
        'data_dir': DEFAULT_DATA_DIR,
        'port': DEFAULT_PORT,
        'ae_title': DEFAULT_AE_TITLE,
        'storage_dir': DEFAULT_STORAGE_DIR,
        'timeout': DEFAULT_TIMEOUT,
        'key_file': DEFAULT_KEY_FILE,
        'log_level': DEFAULT_LOG_LEVEL,
        'log_file': DEFAULT_LOG_FILE,
        'pii_tags': PII_TAGS,
        'patient_info_map_filename': PATIENT_INFO_MAP_FILENAME,
        'api_url': DEFAULT_API_URL,
        'api_username': DEFAULT_API_USERNAME,
        'api_password': DEFAULT_API_PASSWORD,
        'api_token': DEFAULT_API_TOKEN,
        'auto_upload': DEFAULT_AUTO_UPLOAD,
        'zip_dir': DEFAULT_ZIP_DIR,
        'cleanup_after_upload': DEFAULT_CLEANUP_AFTER_UPLOAD,
        'max_retries': DEFAULT_MAX_RETRIES,
        'retry_delay': DEFAULT_RETRY_DELAY
    }

def print_config():
    """Print current configuration values"""
    config = get_config_dict()
    print("\nCurrent Configuration:")
    print("======================")
    for key, value in config.items():
        if key == 'ae_title' and isinstance(value, bytes):
            value = value.decode()
        if key in ['api_password', 'api_token'] and value:
            value = "****" 
        print(f"{key}: {value}")
    print("======================\n")

def ensure_dirs_exist():
    """Create all required directories if they don't exist"""
    Path(DEFAULT_DATA_DIR).mkdir(exist_ok=True)
    Path(DEFAULT_STORAGE_DIR).mkdir(parents=True, exist_ok=True)
    Path(DEFAULT_ZIP_DIR).mkdir(parents=True, exist_ok=True)
    Path(os.path.dirname(DEFAULT_KEY_FILE)).mkdir(parents=True, exist_ok=True)
    if DEFAULT_LOG_FILE:
        Path(os.path.dirname(DEFAULT_LOG_FILE)).mkdir(parents=True, exist_ok=True)