#!/usr/bin/env python
"""
Logging configuration for the DICOM receiver
"""

import logging
import sys
from pathlib import Path

def configure_logging(level=logging.INFO, log_file=None):
    """
    Configure logging for the application
    
    Parameters:
    -----------
    level : int
        Logging level (default: logging.INFO)
    log_file : str, optional
        Path to log file. If None, logs to console only.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    
    # Create formatters
    console_formatter = logging.Formatter('%(levelname)s - %(message)s')
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)
    
    # Configure pynetdicom logger
    pynd_logger = logging.getLogger('pynetdicom')
    pynd_logger.setLevel(logging.INFO)
    
    return root_logger 