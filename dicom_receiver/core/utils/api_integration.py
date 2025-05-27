#!/usr/bin/env python
"""
API Integration utilities for DICOM operations

Handles API queries, downloads, and data processing
"""

import logging
import tempfile
import zipfile
import requests
from pathlib import Path
from io import BytesIO

logger = logging.getLogger('dicom_receiver.utils.api_integration')

class ApiIntegrationUtils:
    """Utilities for API integration and downloads"""
    
    def __init__(self, query_handler, api_url):
        """
        Initialize with query handler and API URL
        
        Parameters:
        -----------
        query_handler : DicomQueryHandler
            The query handler for API operations
        api_url : str
            Base API URL
        """
        self.query_handler = query_handler
        self.api_url = api_url
    
    def get_result_id_for_study(self, study_uid):
        """Get the result_id for a given study UID from API metadata"""
        try:
            api_data = self.query_handler.query_all_metadata()
            if api_data and 'results' in api_data:
                for result_item in api_data['results']:
                    if 'dicom_data' in result_item and 'studies' in result_item['dicom_data']:
                        studies_data = result_item['dicom_data']['studies']
                        if study_uid in studies_data:
                            return result_item['result']['id']
            return None
        except Exception as e:
            logger.error(f"❌ Error getting result_id for study {study_uid}: {e}")
            return None
    
    def download_study_from_api(self, result_id, study_uid, series_filter=None, instance_filter=None):
        """Download study ZIP from API and extract DICOM files"""
        try:
            # Ensure we have a valid authentication token
            if not self.query_handler._authenticate():
                logger.error("❌ Failed to authenticate for download")
                return []
            
            # Prepare download URL and headers
            url = f"{self.api_url}/processing/results/{result_id}/download_dicom_study/"
            params = {"study_uid": study_uid}
            headers = {"Authorization": f"Bearer {self.query_handler.api_uploader.auth_token}"}
            
            logger.info(f"🌐 Downloading from: {url}")
            logger.info(f"📋 Parameters: {params}")
            
            # Download the ZIP file
            response = requests.get(url, params=params, headers=headers, stream=True)
            
            # Handle authentication failure
            if response.status_code == 401:
                logger.warning("❌ Authentication failed during download, attempting to re-authenticate")
                # Clear the existing token to force fresh authentication
                with self.query_handler.api_uploader.auth_lock:
                    self.query_handler.api_uploader.auth_token = None
                
                if self.query_handler._authenticate():
                    # Retry with new token
                    headers["Authorization"] = f"Bearer {self.query_handler.api_uploader.auth_token}"
                    response = requests.get(url, params=params, headers=headers, stream=True)
                    response.raise_for_status()
                else:
                    logger.error("❌ Re-authentication failed during download")
                    return []
            else:
                response.raise_for_status()
            
            # Create temporary directory for extraction
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = Path(temp_dir) / "study.zip"
                
                # Save ZIP file
                with open(zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                logger.info(f"📦 Downloaded ZIP file: {zip_path.stat().st_size} bytes")
                
                # Extract DICOM files
                dicom_files = []
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    for file_info in zip_ref.filelist:
                        if file_info.filename.lower().endswith('.dcm'):
                            # Extract to temporary location
                            extracted_path = zip_ref.extract(file_info, temp_dir)
                            
                            # Apply filters if specified
                            if series_filter or instance_filter:
                                try:
                                    from pydicom import dcmread
                                    ds = dcmread(extracted_path)
                                    
                                    if series_filter and getattr(ds, 'SeriesInstanceUID', '') != series_filter:
                                        continue
                                    if instance_filter and getattr(ds, 'SOPInstanceUID', '') != instance_filter:
                                        continue
                                except Exception as e:
                                    logger.warning(f"⚠️ Could not read DICOM file for filtering: {e}")
                                    continue
                            
                            dicom_files.append(extracted_path)
                
                logger.info(f"📁 Extracted {len(dicom_files)} DICOM files")
                
                # Read files into memory (since temp_dir will be deleted)
                file_data = []
                for file_path in dicom_files:
                    with open(file_path, 'rb') as f:
                        file_data.append(f.read())
                
                return file_data
                
        except Exception as e:
            logger.error(f"❌ Error downloading study from API: {e}")
            return []
    
    def extract_patients_from_api_data(self, api_data, anonymization_utils):
        """Extract unique patients from API data with de-anonymization"""
        unique_patients = {}
        
        if not api_data or 'results' not in api_data:
            return []
        
        for result_item in api_data['results']:
            if 'dicom_data' in result_item and 'studies' in result_item['dicom_data']:
                studies_data = result_item['dicom_data']['studies']
                for study_uid, study_info in studies_data.items():
                    patient_id = study_info.get('patient_id', '')
                    if patient_id and patient_id not in unique_patients:
                        # De-anonymize the patient information
                        original_name = anonymization_utils.get_original_patient_name(study_info.get('patient_name', ''))
                        original_id = anonymization_utils.get_original_patient_id(patient_id)
                        
                        unique_patients[patient_id] = {
                            'PatientName': original_name or study_info.get('patient_name', ''),
                            'PatientID': original_id or patient_id,
                            'PatientBirthDate': study_info.get('patient_birth_date', ''),
                            'PatientSex': study_info.get('patient_sex', '')
                        }
        
        return list(unique_patients.values())
    
    def extract_studies_from_api_data(self, api_data, anonymization_utils):
        """Extract unique studies from API data with de-anonymization"""
        unique_studies = {}
        
        if not api_data or 'results' not in api_data:
            return []
        
        for result_item in api_data['results']:
            if 'dicom_data' in result_item and 'studies' in result_item['dicom_data']:
                studies_data = result_item['dicom_data']['studies']
                for study_uid, study_info in studies_data.items():
                    if study_uid and study_uid not in unique_studies:
                        # De-anonymize the patient information
                        original_name = anonymization_utils.get_original_patient_name(study_info.get('patient_name', ''))
                        original_id = anonymization_utils.get_original_patient_id(study_info.get('patient_id', ''))
                        
                        unique_studies[study_uid] = {
                            'PatientName': original_name or study_info.get('patient_name', ''),
                            'PatientID': original_id or study_info.get('patient_id', ''),
                            'PatientBirthDate': study_info.get('patient_birth_date', ''),
                            'PatientSex': study_info.get('patient_sex', ''),
                            'StudyInstanceUID': study_uid,
                            'StudyID': study_info.get('study_id', ''),
                            'StudyDescription': study_info.get('study_description', ''),
                            'StudyDate': study_info.get('study_date', ''),
                            'StudyTime': study_info.get('study_time', ''),
                            'AccessionNumber': study_info.get('accession_number', '')
                        }
        
        return list(unique_studies.values())
    
    def extract_series_from_api_data(self, api_data, study_uid, anonymization_utils):
        """Extract series for a specific study from API data with de-anonymization"""
        unique_series = {}
        
        if not api_data or 'results' not in api_data:
            return []
        
        for result_item in api_data['results']:
            if 'dicom_data' in result_item and 'studies' in result_item['dicom_data']:
                studies_data = result_item['dicom_data']['studies']
                if study_uid in studies_data:
                    study_info = studies_data[study_uid]
                    if 'series' in study_info:
                        for series_uid_key, series_info in study_info['series'].items():
                            if series_uid_key and series_uid_key not in unique_series:
                                # De-anonymize the patient information
                                original_name = anonymization_utils.get_original_patient_name(study_info.get('patient_name', ''))
                                original_id = anonymization_utils.get_original_patient_id(study_info.get('patient_id', ''))
                                
                                unique_series[series_uid_key] = {
                                    'PatientName': original_name or study_info.get('patient_name', ''),
                                    'PatientID': original_id or study_info.get('patient_id', ''),
                                    'StudyInstanceUID': study_uid,
                                    'SeriesInstanceUID': series_uid_key,
                                    'SeriesNumber': series_info.get('series_number', ''),
                                    'SeriesDescription': series_info.get('series_description', ''),
                                    'Modality': series_info.get('modality', ''),
                                    'SeriesDate': '',  # Not available in this structure
                                    'SeriesTime': ''   # Not available in this structure
                                }
        
        return list(unique_series.values())
    
    def extract_images_from_api_data(self, api_data, study_uid, series_uid, anonymization_utils):
        """Extract images for a specific series from API data with de-anonymization"""
        unique_images = {}
        
        if not api_data or 'results' not in api_data:
            return []
        
        for result_item in api_data['results']:
            if 'dicom_data' in result_item and 'studies' in result_item['dicom_data']:
                studies_data = result_item['dicom_data']['studies']
                if study_uid in studies_data:
                    study_info = studies_data[study_uid]
                    if 'series' in study_info and series_uid in study_info['series']:
                        series_info = study_info['series'][series_uid]
                        if 'instances' in series_info:
                            for instance_info in series_info['instances']:
                                sop_uid = instance_info.get('sop_instance_uid', '')
                                if sop_uid and sop_uid not in unique_images:
                                    # De-anonymize the patient information
                                    original_name = anonymization_utils.get_original_patient_name(instance_info.get('patient_name', ''))
                                    original_id = anonymization_utils.get_original_patient_id(instance_info.get('patient_id', ''))
                                    
                                    unique_images[sop_uid] = {
                                        'PatientName': original_name or instance_info.get('patient_name', ''),
                                        'PatientID': original_id or instance_info.get('patient_id', ''),
                                        'StudyInstanceUID': study_uid,
                                        'SeriesInstanceUID': series_uid,
                                        'SOPInstanceUID': sop_uid,
                                        'SOPClassUID': '',  # Not available in this structure
                                        'InstanceNumber': instance_info.get('instance_number', '')
                                    }
        
        return list(unique_images.values()) 