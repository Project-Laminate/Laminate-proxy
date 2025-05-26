#!/usr/bin/env python
"""
Query module for the DICOM receiver

Handles API queries and de-anonymization of response data
"""

import json
import logging
import requests
from typing import Dict, List, Optional, Any
from pathlib import Path

from dicom_receiver.core.crypto import DicomAnonymizer
from dicom_receiver.core.uploader import ApiUploader

logger = logging.getLogger('dicom_receiver.query')

class DicomQueryHandler:
    """
    Handles querying the API and de-anonymizing response data
    """
    
    def __init__(self, 
                 api_url: str,
                 storage_dir: str,
                 username: Optional[str] = None, 
                 password: Optional[str] = None, 
                 token: Optional[str] = None,
                 max_retries: int = 3,
                 retry_delay: int = 5):
        """
        Initialize the query handler
        
        Args:
            api_url (str): Base URL for the API
            storage_dir (str): Storage directory containing the anonymization mapping
            username (str, optional): Username for authentication
            password (str, optional): Password for authentication
            token (str, optional): Existing auth token
            max_retries (int): Maximum number of retry attempts
            retry_delay (int): Delay between retry attempts in seconds
        """
        self.api_url = api_url.rstrip('/')
        self.storage_dir = Path(storage_dir)
        
        # Initialize the API uploader for authentication
        self.api_uploader = ApiUploader(
            api_url=api_url,
            username=username,
            password=password,
            token=token,
            max_retries=max_retries,
            retry_delay=retry_delay
        )
        
        # Initialize the anonymizer for de-anonymization
        self.anonymizer = DicomAnonymizer(self.storage_dir)
        
    def _authenticate(self) -> bool:
        """Ensure we have a valid authentication token"""
        if not self.api_uploader.auth_token:
            return self.api_uploader.login()
        return True
    
    def _deanonymize_patient_info(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        De-anonymize patient information in the response data
        
        Args:
            data: The response data containing anonymized patient information
            
        Returns:
            The data with de-anonymized patient information
        """
        # Create a reverse mapping from anonymized names to original names
        reverse_name_map = {v: k for k, v in self.anonymizer.patient_name_map.items()}
        
        def deanonymize_recursive(obj):
            """Recursively de-anonymize patient information in nested structures"""
            if isinstance(obj, dict):
                result = {}
                for key, value in obj.items():
                    # Handle various patient name/ID field names that might appear in the API response
                    if key.lower() in ['patient_name', 'patient_id', 'patientname', 'patientid'] and isinstance(value, str):
                        # Check if this is an anonymized name that we can de-anonymize
                        if value in reverse_name_map:
                            result[key] = reverse_name_map[value]
                            logger.debug(f"De-anonymized {key}: {value} -> {reverse_name_map[value]}")
                        else:
                            result[key] = value
                    # Handle DICOM format patient names (e.g., "DOE^JOHN")
                    elif key.lower() in ['patient_name', 'patientname'] and isinstance(value, str) and '^' in value:
                        # For DICOM format names, check if the base name (before ^) is anonymized
                        name_parts = value.split('^')
                        base_name = name_parts[0] if name_parts else value
                        if base_name in reverse_name_map:
                            # Reconstruct the DICOM format name with de-anonymized base
                            original_name = reverse_name_map[base_name]
                            if len(name_parts) > 1:
                                result[key] = f"{original_name}^{'^'.join(name_parts[1:])}"
                            else:
                                result[key] = original_name
                            logger.debug(f"De-anonymized DICOM name {key}: {value} -> {result[key]}")
                        else:
                            result[key] = value
                    else:
                        result[key] = deanonymize_recursive(value)
                return result
            elif isinstance(obj, list):
                return [deanonymize_recursive(item) for item in obj]
            else:
                return obj
        
        return deanonymize_recursive(data)
    
    def query_all_dicom_metadata(self) -> Optional[Dict[str, Any]]:
        """
        Query the API for all DICOM metadata and return de-anonymized results
        
        Returns:
            Dict containing the de-anonymized response data, or None if failed
        """
        if not self._authenticate():
            logger.error("Failed to authenticate with API")
            return None
        
        query_url = f"{self.api_url}/processing/results/all_dicom_metadata/"
        
        try:
            logger.info(f"Querying DICOM metadata from: {query_url}")
            
            headers = {
                'Authorization': f'Bearer {self.api_uploader.auth_token}',
                'Accept': 'application/json'
            }
            
            response = requests.get(query_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                # Clean the response text to handle invalid JSON values
                response_text = response.text
                # Replace asterisks with null values for invalid numeric fields
                import re
                # Handle various patterns of asterisks in JSON values
                response_text = re.sub(r':\s*\*+', ': null', response_text)  # :***
                response_text = re.sub(r':\s*-?\d*\.\*+', ': null', response_text)  # :-66.***
                response_text = re.sub(r':\s*-?\d+\.\*+', ': null', response_text)  # :1.6000000238419,"slice_location":-66.***
                response_text = re.sub(r'[,\s]\*+[,\s]', ', null,', response_text)  # ,***,
                
                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON decode error: {e}")
                    logger.error(f"Error context: {response_text[max(0, e.pos-50):e.pos+50]}")
                    return None
                
                logger.info(f"Successfully retrieved metadata for {data.get('total_results_with_dicom', 0)} results")
                
                # De-anonymize the patient information
                deanonymized_data = self._deanonymize_patient_info(data)
                
                logger.info("Successfully de-anonymized patient information")
                return deanonymized_data
                
            elif response.status_code == 401:
                logger.warning("Authentication failed, attempting to re-authenticate")
                if self.api_uploader.login():
                    # Retry with new token
                    headers['Authorization'] = f'Bearer {self.api_uploader.auth_token}'
                    response = requests.get(query_url, headers=headers, timeout=30)
                    if response.status_code == 200:
                        data = response.json()
                        deanonymized_data = self._deanonymize_patient_info(data)
                        return deanonymized_data
                
                logger.error("Re-authentication failed")
                return None
                
            else:
                logger.error(f"Query failed with status {response.status_code}: {response.text}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"Error querying API: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during query: {e}")
            return None
    
    def query_result_by_id(self, result_id: str) -> Optional[Dict[str, Any]]:
        """
        Query the API for a specific result by ID and return de-anonymized data
        
        Args:
            result_id: The ID of the result to query
            
        Returns:
            Dict containing the de-anonymized result data, or None if failed
        """
        if not self._authenticate():
            logger.error("Failed to authenticate with API")
            return None
        
        query_url = f"{self.api_url}/processing/results/{result_id}/dicom_metadata/"
        
        try:
            logger.info(f"Querying result {result_id} from: {query_url}")
            
            headers = {
                'Authorization': f'Bearer {self.api_uploader.auth_token}',
                'Accept': 'application/json'
            }
            
            response = requests.get(query_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully retrieved metadata for result {result_id}")
                
                # De-anonymize the patient information
                deanonymized_data = self._deanonymize_patient_info(data)
                
                logger.info("Successfully de-anonymized patient information")
                return deanonymized_data
                
            elif response.status_code == 401:
                logger.warning("Authentication failed, attempting to re-authenticate")
                if self.api_uploader.login():
                    # Retry with new token
                    headers['Authorization'] = f'Bearer {self.api_uploader.auth_token}'
                    response = requests.get(query_url, headers=headers, timeout=30)
                    if response.status_code == 200:
                        data = response.json()
                        deanonymized_data = self._deanonymize_patient_info(data)
                        return deanonymized_data
                
                logger.error("Re-authentication failed")
                return None
                
            else:
                logger.error(f"Query failed with status {response.status_code}: {response.text}")
                return None
                
        except requests.RequestException as e:
            logger.error(f"Error querying API: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during query: {e}")
            return None
    
    def get_anonymization_mapping(self) -> Dict[str, str]:
        """
        Get the current anonymization mapping
        
        Returns:
            Dict mapping original patient names to anonymized names
        """
        return self.anonymizer.patient_name_map.copy()
    
    def get_reverse_anonymization_mapping(self) -> Dict[str, str]:
        """
        Get the reverse anonymization mapping
        
        Returns:
            Dict mapping anonymized names to original patient names
        """
        return {v: k for k, v in self.anonymizer.patient_name_map.items()}
    
    def query_all_metadata(self) -> Optional[Dict[str, Any]]:
        """
        Alias for query_all_dicom_metadata for consistency
        
        Returns:
            Dict containing the de-anonymized response data, or None if failed
        """
        return self.query_all_dicom_metadata() 