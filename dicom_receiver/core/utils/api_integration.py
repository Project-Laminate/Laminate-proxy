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

    def download_series_from_api(self, result_id, series_uid, instance_filter=None):
        """Download series ZIP from API and extract DICOM files"""
        try:
            # Ensure we have a valid authentication token
            if not self.query_handler._authenticate():
                logger.error("❌ Failed to authenticate for series download")
                return []
            
            # Prepare download URL and headers
            url = f"{self.api_url}/processing/results/{result_id}/download_dicom_series/"
            params = {"series_uid": series_uid}
            headers = {"Authorization": f"Bearer {self.query_handler.api_uploader.auth_token}"}
            
            logger.info(f"🌐 Downloading series from: {url}")
            logger.info(f"📋 Parameters: {params}")
            
            # Download the ZIP file
            response = requests.get(url, params=params, headers=headers, stream=True, timeout=300)
            
            # Handle authentication failure
            if response.status_code == 401:
                logger.warning("❌ Authentication failed during series download, attempting to re-authenticate")
                # Clear the existing token to force fresh authentication
                with self.query_handler.api_uploader.auth_lock:
                    self.query_handler.api_uploader.auth_token = None
                
                if self.query_handler._authenticate():
                    # Retry with new token
                    headers["Authorization"] = f"Bearer {self.query_handler.api_uploader.auth_token}"
                    response = requests.get(url, params=params, headers=headers, stream=True, timeout=300)
                    response.raise_for_status()
                else:
                    logger.error("❌ Re-authentication failed during series download")
                    return []
            elif response.status_code != 200:
                logger.error(f"❌ API returned status {response.status_code}: {response.text[:200]}")
                return []
            
            # Check content type
            content_type = response.headers.get('content-type', '').lower()
            if 'application/zip' not in content_type and 'application/octet-stream' not in content_type:
                logger.warning(f"⚠️ Unexpected content type: {content_type}")
            
            # Check content length
            content_length = response.headers.get('content-length')
            if content_length:
                logger.info(f"📦 Expected download size: {int(content_length)} bytes")
            else:
                logger.warning("⚠️ No content-length header in response")
            
            # Create temporary directory for extraction
            with tempfile.TemporaryDirectory() as temp_dir:
                zip_path = Path(temp_dir) / "series.zip"
                
                # Save ZIP file
                downloaded_size = 0
                with open(zip_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:  # Filter out keep-alive chunks
                            f.write(chunk)
                            downloaded_size += len(chunk)
                
                actual_size = zip_path.stat().st_size
                logger.info(f"📦 Downloaded series ZIP file: {actual_size} bytes")
                
                # Validate ZIP file
                if actual_size == 0:
                    logger.error("❌ Downloaded ZIP file is empty")
                    return []
                
                # Check if it's a valid ZIP file
                try:
                    with zipfile.ZipFile(zip_path, 'r') as test_zip:
                        test_zip.testzip()
                    logger.info("✅ ZIP file validation passed")
                except zipfile.BadZipFile as e:
                    logger.error(f"❌ Invalid ZIP file: {e}")
                    return []
                except Exception as e:
                    logger.error(f"❌ ZIP validation error: {e}")
                    return []
                
                # Extract DICOM files
                dicom_files = []
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    logger.info(f"📦 ZIP contains {len(zip_ref.filelist)} files")
                    
                    for file_info in zip_ref.filelist:
                        # Skip directories
                        if file_info.is_dir():
                            continue
                            
                        # Check if it's a DICOM file (by extension or content)
                        filename = file_info.filename.lower()
                        if filename.endswith('.dcm') or filename.endswith('.dicom'):
                            logger.debug(f"📄 Extracting DICOM file: {file_info.filename}")
                            
                            try:
                                # Extract to temporary location
                                extracted_path = zip_ref.extract(file_info, temp_dir)
                                
                                # Verify it's actually a DICOM file by trying to read it
                                from pydicom import dcmread
                                ds = dcmread(extracted_path, stop_before_pixels=True)
                                
                                # Apply instance filter if specified
                                if instance_filter:
                                    if getattr(ds, 'SOPInstanceUID', '') != instance_filter:
                                        logger.debug(f"⏭️ Skipping file - SOP Instance UID doesn't match filter")
                                        continue
                                
                                dicom_files.append(extracted_path)
                                logger.debug(f"✅ Added DICOM file: {file_info.filename}")
                                
                            except Exception as e:
                                logger.warning(f"⚠️ Could not process file {file_info.filename}: {e}")
                                continue
                        else:
                            logger.debug(f"⏭️ Skipping non-DICOM file: {file_info.filename}")
                
                logger.info(f"📁 Successfully extracted {len(dicom_files)} valid DICOM files from series")
                
                # Read files into memory and apply de-anonymization
                file_data = []
                processed_count = 0
                fallback_count = 0
                
                for i, file_path in enumerate(dicom_files, 1):
                    try:
                        logger.debug(f"📖 Processing DICOM file {i}/{len(dicom_files)}: {Path(file_path).name}")
                        
                        # Read the DICOM file
                        from pydicom import dcmread
                        ds = dcmread(file_path, force=True)
                        
                        # Log some basic info about the file
                        patient_name = getattr(ds, 'PatientName', 'Unknown')
                        sop_uid = getattr(ds, 'SOPInstanceUID', 'Unknown')
                        logger.debug(f"   Patient: {patient_name}, SOP: {sop_uid[:20]}...")
                        
                        # Apply de-anonymization to restore original patient information
                        self._deanonymize_dicom_dataset(ds)
                        
                        # Log after de-anonymization
                        patient_name_after = getattr(ds, 'PatientName', 'Unknown')
                        if patient_name != patient_name_after:
                            logger.debug(f"   De-anonymized: {patient_name} -> {patient_name_after}")
                        
                        # Ensure proper DICOM file metadata for pixel data accessibility
                        self._fix_dicom_file_metadata(ds)
                        
                        # Convert back to bytes
                        from io import BytesIO
                        buffer = BytesIO()
                        ds.save_as(buffer)
                        file_data.append(buffer.getvalue())
                        processed_count += 1
                        
                    except Exception as e:
                        logger.warning(f"⚠️ Error processing DICOM file {Path(file_path).name}: {e}")
                        logger.warning(f"   Falling back to raw file read")
                        
                        try:
                            # Fallback: read file as-is without de-anonymization
                            with open(file_path, 'rb') as f:
                                file_data.append(f.read())
                            fallback_count += 1
                        except Exception as e2:
                            logger.error(f"❌ Failed to read file even as raw bytes: {e2}")
                            continue
                
                logger.info(f"📊 Processing complete: {processed_count} de-anonymized, {fallback_count} fallback, {len(file_data)} total files")
                return file_data
                
        except Exception as e:
            logger.error(f"❌ Error downloading series from API: {e}")
            return []

    def _deanonymize_dicom_dataset(self, dataset):
        """De-anonymize patient information in a DICOM dataset"""
        try:
            # Get the reverse mapping from anonymized names to original names
            reverse_name_map = {v: k for k, v in self.query_handler.anonymizer.patient_name_map.items()}
            
            # De-anonymize PatientName if it exists and is anonymized
            if hasattr(dataset, 'PatientName') and str(dataset.PatientName) in reverse_name_map:
                original_name = reverse_name_map[str(dataset.PatientName)]
                dataset.PatientName = original_name
                logger.debug(f"De-anonymized PatientName: {str(dataset.PatientName)} -> {original_name}")
            
            # Handle PatientID de-anonymization (supports both old and new formats)
            if hasattr(dataset, 'PatientID'):
                current_id = str(dataset.PatientID)
                # Check if this might be an old anonymized ID that needs de-anonymization
                if current_id in reverse_name_map:
                    # This is an old anonymized ID, try to find the original
                    if hasattr(self.query_handler, 'anonymizer') and hasattr(self.query_handler.anonymizer, 'patient_info_map'):
                        for study_uid, patient_info in self.query_handler.anonymizer.patient_info_map.items():
                            if ('PatientID' in patient_info and 'PatientName' in patient_info and
                                patient_info['PatientName'] in self.query_handler.anonymizer.patient_name_map and
                                self.query_handler.anonymizer.patient_name_map[patient_info['PatientName']] == current_id):
                                dataset.PatientID = patient_info['PatientID']
                                logger.debug(f"De-anonymized old PatientID: {current_id} -> {patient_info['PatientID']}")
                                break
                else:
                    # New format - PatientID is already original
                    logger.debug(f"PatientID (already original): {current_id}")
            
            # Try to restore other patient information from the anonymizer's mapping
            if hasattr(dataset, 'StudyInstanceUID'):
                study_uid = str(dataset.StudyInstanceUID)
                if study_uid in self.query_handler.anonymizer.patient_info_map:
                    original_info = self.query_handler.anonymizer.patient_info_map[study_uid]
                    
                    # Restore other PII fields if they were anonymized
                    for field_name, original_value in original_info.items():
                        current_value = str(getattr(dataset, field_name)) if hasattr(dataset, field_name) else ""
                        
                        # Check for various anonymized values
                        if (current_value == "ANON" or 
                            current_value == "19000101" or  # Anonymous date
                            current_value == "000000"):     # Anonymous time
                            setattr(dataset, field_name, original_value)
                            logger.debug(f"Restored {field_name}: {current_value} -> {original_value}")
                            
        except Exception as e:
            logger.warning(f"⚠️ Error during de-anonymization: {e}")

    def _fix_dicom_file_metadata(self, dataset):
        """Fix DICOM file metadata to ensure pixel data accessibility"""
        try:
            import pydicom
            from pydicom.uid import ImplicitVRLittleEndian, ExplicitVRLittleEndian
            
            # Ensure file_meta exists
            if not hasattr(dataset, 'file_meta') or dataset.file_meta is None:
                dataset.file_meta = pydicom.dataset.FileMetaDataset()
            
            # CRITICAL: Preserve original TransferSyntaxUID if it exists
            # Only set a default if completely missing
            if not hasattr(dataset.file_meta, 'TransferSyntaxUID') or dataset.file_meta.TransferSyntaxUID is None:
                # No transfer syntax specified - use default
                preferred_syntax = ExplicitVRLittleEndian
                dataset.file_meta.TransferSyntaxUID = preferred_syntax
                logger.debug(f"No TransferSyntaxUID found, setting default: {preferred_syntax}")
            else:
                # Preserve the original transfer syntax
                preferred_syntax = dataset.file_meta.TransferSyntaxUID
                logger.debug(f"Preserving original TransferSyntaxUID: {preferred_syntax}")
            
            # Set transfer syntax and encoding based on the actual transfer syntax
            dataset.is_little_endian = preferred_syntax in [
                ImplicitVRLittleEndian,
                ExplicitVRLittleEndian
            ]
            dataset.is_implicit_VR = preferred_syntax == ImplicitVRLittleEndian
            
            # Ensure all required file meta elements are present
            dataset.file_meta.MediaStorageSOPClassUID = dataset.SOPClassUID
            dataset.file_meta.MediaStorageSOPInstanceUID = dataset.SOPInstanceUID
            dataset.file_meta.ImplementationClassUID = pydicom.uid.PYDICOM_IMPLEMENTATION_UID
            dataset.file_meta.ImplementationVersionName = "PYDICOM"
            
            # Set the file meta information version
            dataset.file_meta.FileMetaInformationVersion = b'\x00\x01'
            
        except Exception as e:
            logger.warning(f"⚠️ Error fixing DICOM file metadata: {e}")

    def download_study_files(self, study_uid):
        """Download files for a study (wrapper method for move handler compatibility)"""
        try:
            result_id = self.get_result_id_for_study(study_uid)
            if not result_id:
                logger.warning(f"❌ No result_id found for study: {study_uid}")
                return []
            
            return self.download_study_from_api(result_id, study_uid)
        except Exception as e:
            logger.error(f"❌ Error downloading study files for {study_uid}: {e}")
            return []

    def download_series_files(self, series_uid, study_uid):
        """Download files for a series (wrapper method for move handler compatibility)"""
        try:
            result_id = self.get_result_id_for_study(study_uid)
            if not result_id:
                logger.warning(f"❌ No result_id found for study: {study_uid}")
                return []
            
            return self.download_series_from_api(result_id, series_uid)
        except Exception as e:
            logger.error(f"❌ Error downloading series files for {series_uid}: {e}")
            return []

    def download_image_files(self, sop_uid, series_uid, study_uid):
        """Download files for a specific image (wrapper method for move handler compatibility)"""
        try:
            result_id = self.get_result_id_for_study(study_uid)
            if not result_id:
                logger.warning(f"❌ No result_id found for study: {study_uid}")
                return []
            
            return self.download_series_from_api(result_id, series_uid, instance_filter=sop_uid)
        except Exception as e:
            logger.error(f"❌ Error downloading image files for {sop_uid}: {e}")
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