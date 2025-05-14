#!/usr/bin/env python
"""
API uploader module for the DICOM receiver

Handles authentication and upload of zipped DICOM studies to remote API
"""

import os
import json
import logging
import zipfile
import requests
import shutil
import time
import threading
from pathlib import Path
from typing import Dict, Optional, Any

logger = logging.getLogger('dicom_receiver.uploader')

class ApiUploader:
    """
    Handles authentication and uploading of zipped DICOM studies
    """
    
    def __init__(self, 
                 api_url: str,
                 username: Optional[str] = None, 
                 password: Optional[str] = None, 
                 token: Optional[str] = None, 
                 cleanup_after_upload: bool = False,
                 max_retries: int = 3,
                 retry_delay: int = 5):
        """
        Initialize the API uploader
        
        Args:
            api_url (str): Base URL for the API
            username (str, optional): Username for authentication
            password (str, optional): Password for authentication
            token (str, optional): Existing auth token
            cleanup_after_upload (bool): Whether to remove files after successful upload
            max_retries (int): Maximum number of retry attempts for failed uploads
            retry_delay (int): Delay between retry attempts in seconds
        """
        self.api_url = api_url.rstrip('/')
        self.username = username
        self.password = password
        self.auth_token = token
        self.user_info = None
        self.cleanup_after_upload = cleanup_after_upload
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        self.auth_lock = threading.Lock()
        
    def login(self) -> tuple:
        """
        Authenticate with the API and get access token
        
        Returns:
            bool: True if authentication successful, False otherwise
        """
        with self.auth_lock:
            if self.auth_token:
                return True
                
            if not self.username or not self.password:
                logger.error("Username and password required for authentication")
                return False
                
            login_url = f"{self.api_url}/users/login/"
            
            for attempt in range(1, self.max_retries + 1):
                try:
                    logger.debug(f"Authentication attempt {attempt}/{self.max_retries}")
                    response = requests.post(
                        login_url,
                        json={"username_or_email": self.username, "password": self.password},
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        auth_data = response.json()
                        self.auth_token = auth_data.get("access")
                        self.user_info = auth_data.get("user")
                        logger.info(f"Successfully authenticated as {self.username}")
                        return True
                    else:
                        logger.warning(f"Authentication failed: {response.status_code} - {response.text}")
                        
                        if 400 <= response.status_code < 500 and response.status_code != 429:
                            logger.error("Client error, not retrying")
                            return False
                            
                except (requests.RequestException, ConnectionError, TimeoutError) as e:
                    logger.warning(f"Error during authentication attempt {attempt}: {e}")
                
                if attempt < self.max_retries:
                    logger.info(f"Retrying authentication in {self.retry_delay} seconds...")
                    time.sleep(self.retry_delay)
                    
            logger.error(f"Authentication failed after {self.max_retries} attempts")
            return False
    
    def zip_study(self, study_dir: str, output_zip: Optional[str] = None) -> Optional[str]:
        """
        Create a zip file from a study directory
        
        Args:
            study_dir (str): Path to the study directory
            output_zip (str, optional): Path for the output zip file
            
        Returns:
            str: Path to the created zip file or None if failed
        """
        study_path = Path(study_dir)
        
        if not output_zip:
            output_zip = f"{study_path.parent / study_path.name}.zip"
        
        try:
            logger.info(f"Creating zip file from study at {study_dir}")
            with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(study_dir):
                    for file in files:
                        file_path = Path(root) / file
                        arcname = file_path.relative_to(study_path.parent)
                        zipf.write(file_path, arcname)
            
            logger.info(f"Successfully created zip file at {output_zip}")
            return output_zip
        
        except Exception as e:
            logger.error(f"Error creating zip file: {e}")
            return None
    
    def upload_study(self, 
                     zip_file_path: str, 
                     study_info: Optional[Dict[str, Any]] = None,
                     study_dir: Optional[str] = None,
                     name: Optional[str] = None) -> tuple:
        """
        Upload a zipped study to the API with retry mechanism
        
        Args:
            zip_file_path (str): Path to the zip file
            study_info (dict, optional): Additional study information
            study_dir (str, optional): Path to the original study directory (for cleanup)
            name (str, optional): Name for the dataset. If not provided, uses filename
            
        Returns:
            tuple: (success (bool), response_data (dict or None))
        """
        if not self.auth_token and not self.login():
            logger.error("Failed to obtain authentication token for upload")
            return False, None
            
        upload_url = f"{self.api_url}/data/datasets/"
        upload_success = False
        response_data = None
        
        if not name and not (study_info and 'name' in study_info):
            zip_basename = os.path.basename(zip_file_path)
            name = os.path.splitext(zip_basename)[0]
            logger.info(f"Using dataset name: {name}")
        
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.info(f"Upload attempt {attempt}/{self.max_retries} for {zip_file_path}")
                
                logger.debug(f"Opening file: {zip_file_path}")
                logger.debug(f"File size: {os.path.getsize(zip_file_path)} bytes")
                
                form_data = {}
                
                if name:
                    form_data['name'] = name
                elif study_info and 'name' in study_info:
                    form_data['name'] = study_info['name']
                
                if study_info:
                    for key, value in study_info.items():
                        if key != 'name':
                            form_data[key] = str(value)
                
                files = {
                    'file': (os.path.basename(zip_file_path), open(zip_file_path, 'rb'), 'application/octet-stream')
                }
                
                headers = {
                    'Authorization': f'Bearer {self.auth_token}',
                    'User-Agent': 'Mozilla/5.0',
                    'Accept': 'application/json'
                }
                
                response = requests.post(
                    upload_url,
                    headers=headers,
                    files=files,
                    data=form_data
                )
                
                files['file'][1].close()
                
                logger.debug(f"Upload response status: {response.status_code}")
                logger.debug(f"Upload response content type: {response.headers.get('Content-Type', 'unknown')}")
                
                upload_success = response.status_code in (200, 201)
                
                if upload_success and 'application/json' in response.headers.get('Content-Type', ''):
                    try:
                        response_data = response.json()
                        logger.info(f"Dataset uploaded with ID: {response_data.get('id')}")
                    except json.JSONDecodeError:
                        logger.warning("Unable to parse JSON response")
                
                if upload_success:
                    logger.info(f"Successfully uploaded study: {zip_file_path}")
                    break
                else:
                    error_msg = f"Upload failed: {response.status_code} - {response.text}"
                    
                    if response.status_code == 401:
                        logger.warning("Authentication failed, token may be expired. Attempting to refresh...")
                        with self.auth_lock:
                            self.auth_token = None
                        if not self.login():
                            logger.error("Failed to refresh authentication token")
                            break
                    
                    elif 400 <= response.status_code < 500 and response.status_code != 429:
                        logger.error(f"{error_msg} - Client error, not retrying")
                        break
                    
                    else:
                        logger.warning(error_msg)
                    
            except Exception as e:
                logger.warning(f"Error during upload attempt {attempt}: {e}")
                if 'files' in locals() and 'file' in files and hasattr(files['file'][1], 'close'):
                    try:
                        files['file'][1].close()
                    except:
                        pass
            
            if attempt < self.max_retries:
                retry_seconds = self.retry_delay * attempt
                logger.info(f"Retrying upload in {retry_seconds} seconds...")
                time.sleep(retry_seconds)
        
        if upload_success and self.cleanup_after_upload:
            self.cleanup_files(zip_file_path, study_dir)
            
        return upload_success, response_data
                
    def cleanup_files(self, zip_file_path: str, study_dir: Optional[str] = None) -> None:
        """
        Remove zip file and optionally the study directory after successful upload
        
        Args:
            zip_file_path (str): Path to the zip file to remove
            study_dir (str, optional): Path to the study directory to remove
        """
        try:
            if zip_file_path and os.path.exists(zip_file_path):
                logger.info(f"Removing zip file: {zip_file_path}")
                os.remove(zip_file_path)
            
            if study_dir and os.path.exists(study_dir):
                logger.info(f"Removing study directory: {study_dir}")
                shutil.rmtree(study_dir)
                
        except Exception as e:
            logger.error(f"Error cleaning up files: {e}") 