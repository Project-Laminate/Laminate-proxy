#!/usr/bin/env python
"""
DICOM SCP (Service Class Provider) implementation

Handles DICOM networking, associations, and storage operations
"""

import logging
import os
import signal
import threading
import time
import tempfile
import zipfile
import requests
from pathlib import Path

from pydicom import Dataset
from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian
from pynetdicom import AE, evt, StoragePresentationContexts, QueryRetrievePresentationContexts, debug_logger
from pynetdicom.sop_class import (
    Verification,
    StudyRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelFind,
    ModalityWorklistInformationFind,
    StudyRootQueryRetrieveInformationModelGet,
    PatientRootQueryRetrieveInformationModelGet
)

from dicom_receiver.core.crypto import DicomEncryptor
from dicom_receiver.core.storage import DicomStorage, StudyMonitor
from dicom_receiver.core.uploader import ApiUploader
from dicom_receiver.core.query import DicomQueryHandler

logger = logging.getLogger('dicom_receiver.scp')

class DicomServiceProvider:
    """
    DICOM Service Class Provider (SCP) that receives and processes DICOM files
    """
    
    def __init__(self, 
                 storage: DicomStorage,
                 study_monitor: StudyMonitor,
                 encryptor: DicomEncryptor,
                 port: int = 11112, 
                 ae_title: bytes = b'DICOMRCV',
                 api_url: str = None,
                 api_username: str = None,
                 api_password: str = None,
                 api_token: str = None,
                 auto_upload: bool = False,
                 zip_dir: str = 'zips',
                 cleanup_after_upload: bool = False,
                 max_retries: int = 3,
                 retry_delay: int = 5):
        """
        Initialize the DICOM SCP
        
        Parameters:
        -----------
        storage : DicomStorage
            Storage handler for DICOM files
        study_monitor : StudyMonitor
            Monitor for tracking study completion
        encryptor : DicomEncryptor
            Encryptor for patient information
        port : int
            Port to listen on
        ae_title : bytes
            AE title for this SCP
        api_url : str
            URL of the API for uploading studies
        api_username : str
            Username for API authentication
        api_password : str
            Password for API authentication
        api_token : str
            Existing token for API authentication
        auto_upload : bool
            Whether to automatically upload studies when complete
        zip_dir : str
            Directory to store zipped studies
        cleanup_after_upload : bool
            Whether to remove files after successful upload
        max_retries : int
            Maximum number of retry attempts for failed API operations
        retry_delay : int
            Delay between retry attempts in seconds
        """
        self.storage = storage
        self.study_monitor = study_monitor
        self.encryptor = encryptor
        self.port = port
        self.ae_title = ae_title
        self.api_url = api_url
        self.api_username = api_username
        self.api_password = api_password
        self.api_token = api_token
        self.auto_upload = auto_upload
        self.zip_dir = Path(zip_dir)
        self.cleanup_after_upload = cleanup_after_upload
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        self.is_running = False
        self.server_thread = None
        self.ae = None
        self.shutdown_event = threading.Event()
        
        # Initialize query handler for API queries
        if api_url:
            self.query_handler = DicomQueryHandler(
                api_url=api_url,
                storage_dir=str(storage.storage_dir),
                username=api_username,
                password=api_password,
                token=api_token
            )
            logger.info(f"Query handler initialized for API: {api_url}")
        else:
            self.query_handler = None
            logger.info("No API URL provided - queries will only use local storage")
        
        if self.auto_upload:
            self.zip_dir.mkdir(parents=True, exist_ok=True)
            
            self.api_uploader = ApiUploader(
                api_url=api_url,
                username=api_username,
                password=api_password,
                token=api_token,
                cleanup_after_upload=cleanup_after_upload,
                max_retries=max_retries,
                retry_delay=retry_delay
            )
            
            self.study_monitor.register_study_complete_callback(self._study_complete_handler)
            
            logger.info(f"Auto-upload enabled. Studies will be uploaded to {api_url}")
            if self.cleanup_after_upload:
                logger.info("Cleanup after upload is enabled. Files will be removed after successful upload.")
            logger.info(f"Upload retry mechanism: max_retries={max_retries}, retry_delay={retry_delay}s")
        
    def _handle_store(self, event):
        """Handle a C-STORE request"""
        dataset = event.dataset
        
        study_uid = dataset.StudyInstanceUID
        series_uid = dataset.SeriesInstanceUID
        instance_uid = dataset.SOPInstanceUID
        
        self.study_monitor.update_study_activity(study_uid)
        
        # Pass the dataset to get_file_path to determine the patient ID
        file_path = self.storage.get_file_path(study_uid, series_uid, instance_uid, dataset=dataset)
        
        # Encrypt patient information
        self.encryptor.encrypt_dataset(dataset)
        
        # Save the file
        dataset.save_as(file_path)
        
        logger.info(f"Stored DICOM file: {file_path}")
        
        return 0x0000
    
    def _handle_find(self, event):
        """Handle a C-FIND request"""
        logger.info("=" * 60)
        logger.info("🔍 RECEIVED C-FIND REQUEST")
        logger.info("=" * 60)
        
        # Get the query dataset
        query_ds = event.identifier
        
        # Get the query level
        query_level = getattr(query_ds, 'QueryRetrieveLevel', 'STUDY')
        logger.info(f"📋 Query Level: {query_level}")
        
        # Log query parameters
        logger.info("📝 Query Parameters:")
        for tag in query_ds:
            if hasattr(query_ds, tag.keyword) and tag.keyword:
                value = getattr(query_ds, tag.keyword, '')
                if value:
                    logger.info(f"   {tag.keyword}: {value}")
                else:
                    logger.info(f"   {tag.keyword}: <empty> (requesting this field)")
        
        try:
            if query_level == 'PATIENT':
                yield from self._find_patients(query_ds)
            elif query_level == 'STUDY':
                yield from self._find_studies(query_ds)
            elif query_level == 'SERIES':
                yield from self._find_series(query_ds)
            elif query_level == 'IMAGE':
                yield from self._find_images(query_ds)
            else:
                logger.warning(f"❌ Unsupported query level: {query_level}")
                yield 0xC000, None  # Unable to process
                
        except Exception as e:
            logger.error(f"❌ Error processing C-FIND request: {e}")
            yield 0xC000, None  # Unable to process
    
    def _handle_get(self, event):
        """Handle a C-GET request"""
        logger.info("=" * 60)
        logger.info("📥 RECEIVED C-GET REQUEST")
        logger.info("=" * 60)
        
        # Get the query dataset
        query_ds = event.identifier
        
        # Get the query level
        query_level = getattr(query_ds, 'QueryRetrieveLevel', 'STUDY')
        logger.info(f"📋 Query Level: {query_level}")
        
        # Log query parameters
        logger.info("📝 Query Parameters:")
        for tag in query_ds:
            if hasattr(query_ds, tag.keyword) and tag.keyword:
                value = getattr(query_ds, tag.keyword, '')
                if value:
                    logger.info(f"   {tag.keyword}: {value}")
        
        try:
            if query_level == 'STUDY':
                yield from self._get_study(query_ds)
            elif query_level == 'SERIES':
                yield from self._get_series(query_ds)
            elif query_level == 'IMAGE':
                yield from self._get_image(query_ds)
            else:
                logger.warning(f"❌ Unsupported C-GET level: {query_level}")
                yield 0xC000, None  # Unable to process
                
        except Exception as e:
            logger.error(f"❌ Error processing C-GET request: {e}")
            yield 0xC000, None  # Unable to process
    
    def _find_patients(self, query_ds):
        """Find patients matching the query"""
        logger.info("👤 Processing PATIENT level C-FIND")
        
        # Get all unique patients from storage
        patients = self.storage.get_all_patients()
        logger.info(f"📊 Found {len(patients)} patients in local storage")
        
        # If no local patients and we have API access, query the API
        if not patients and self.query_handler:
            logger.info("🌐 No local patients found, querying API...")
            try:
                api_data = self.query_handler.query_all_metadata()
                if api_data and 'results' in api_data:
                    # Extract unique patients from API data
                    unique_patients = {}
                    for result_item in api_data['results']:
                        if 'dicom_data' in result_item and 'studies' in result_item['dicom_data']:
                            studies_data = result_item['dicom_data']['studies']
                            for study_uid, study_info in studies_data.items():
                                patient_id = study_info.get('patient_id', '')
                                if patient_id and patient_id not in unique_patients:
                                    # De-anonymize the patient information
                                    original_name = self._get_original_patient_name(study_info.get('patient_name', ''))
                                    original_id = self._get_original_patient_id(patient_id)
                                    
                                    unique_patients[patient_id] = {
                                        'PatientName': original_name or study_info.get('patient_name', ''),
                                        'PatientID': original_id or patient_id,
                                        'PatientBirthDate': study_info.get('patient_birth_date', ''),
                                        'PatientSex': study_info.get('patient_sex', '')
                                    }
                    
                    patients = list(unique_patients.values())
                    logger.info(f"🌐 Found {len(patients)} patients from API")
                else:
                    logger.warning("🌐 API query returned no data")
            except Exception as e:
                logger.error(f"❌ Error querying API: {e}")
        
        response_count = 0
        for patient_info in patients:
            # Create response dataset
            response_ds = Dataset()
            response_ds.QueryRetrieveLevel = 'PATIENT'
            
            response_ds.PatientName = patient_info.get('PatientName', '')
            response_ds.PatientID = patient_info.get('PatientID', '')
            
            if 'PatientBirthDate' in patient_info:
                response_ds.PatientBirthDate = patient_info['PatientBirthDate']
            if 'PatientSex' in patient_info:
                response_ds.PatientSex = patient_info['PatientSex']
            
            logger.info(f"📤 Returning patient #{response_count + 1}: {response_ds.PatientName} (ID: {response_ds.PatientID})")
            response_count += 1
            yield 0xFF00, response_ds  # Pending status
        
        # Final status
        logger.info(f"✅ PATIENT query completed - returned {response_count} patients")
        logger.info("=" * 60)
        yield 0x0000, None  # Success
    
    def _find_studies(self, query_ds):
        """Find studies matching the query"""
        logger.info("📚 Processing STUDY level C-FIND")
        
        # Get all studies from storage
        studies = self.storage.get_all_studies()
        logger.info(f"📊 Found {len(studies)} studies in local storage")
        
        # If no local studies and we have API access, query the API
        if not studies and self.query_handler:
            logger.info("🌐 No local studies found, querying API...")
            try:
                api_data = self.query_handler.query_all_metadata()
                if api_data and 'results' in api_data:
                    # Extract unique studies from API data
                    unique_studies = {}
                    for result_item in api_data['results']:
                        if 'dicom_data' in result_item and 'studies' in result_item['dicom_data']:
                            studies_data = result_item['dicom_data']['studies']
                            for study_uid, study_info in studies_data.items():
                                if study_uid and study_uid not in unique_studies:
                                    # De-anonymize the patient information
                                    original_name = self._get_original_patient_name(study_info.get('patient_name', ''))
                                    original_id = self._get_original_patient_id(study_info.get('patient_id', ''))
                                    
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
                    
                    studies = list(unique_studies.values())
                    logger.info(f"🌐 Found {len(studies)} studies from API")
                else:
                    logger.warning("🌐 API query returned no data")
            except Exception as e:
                logger.error(f"❌ Error querying API: {e}")
        
        response_count = 0
        for study_info in studies:
            # Create response dataset
            response_ds = Dataset()
            response_ds.QueryRetrieveLevel = 'STUDY'
            
            # Set patient information (already de-anonymized if from API)
            response_ds.PatientName = study_info.get('PatientName', '')
            response_ds.PatientID = study_info.get('PatientID', '')
            
            # Set study information
            response_ds.StudyInstanceUID = study_info.get('StudyInstanceUID', '')
            response_ds.StudyID = study_info.get('StudyID', '')
            response_ds.StudyDescription = study_info.get('StudyDescription', '')
            response_ds.StudyDate = study_info.get('StudyDate', '')
            response_ds.StudyTime = study_info.get('StudyTime', '')
            response_ds.AccessionNumber = study_info.get('AccessionNumber', '')
            
            if 'PatientBirthDate' in study_info:
                response_ds.PatientBirthDate = study_info['PatientBirthDate']
            if 'PatientSex' in study_info:
                response_ds.PatientSex = study_info['PatientSex']
            if 'NumberOfStudyRelatedSeries' in study_info:
                response_ds.NumberOfStudyRelatedSeries = study_info['NumberOfStudyRelatedSeries']
            if 'NumberOfStudyRelatedInstances' in study_info:
                response_ds.NumberOfStudyRelatedInstances = study_info['NumberOfStudyRelatedInstances']
            
            logger.info(f"📤 Returning study #{response_count + 1}:")
            logger.info(f"   👤 Patient: {response_ds.PatientName} (ID: {response_ds.PatientID})")
            logger.info(f"   📋 Study: {response_ds.StudyDescription or 'No Description'}")
            logger.info(f"   📅 Date: {response_ds.StudyDate or 'Unknown'}")
            logger.info(f"   🆔 UID: {response_ds.StudyInstanceUID}")
            logger.info(f"   📊 Series: {getattr(response_ds, 'NumberOfStudyRelatedSeries', 0)}, Images: {getattr(response_ds, 'NumberOfStudyRelatedInstances', 0)}")
            
            response_count += 1
            yield 0xFF00, response_ds  # Pending status
        
        # Final status
        logger.info(f"✅ STUDY query completed - returned {response_count} studies")
        logger.info("=" * 60)
        yield 0x0000, None  # Success
    
    def _find_series(self, query_ds):
        """Find series matching the query"""
        logger.info("📁 Processing SERIES level C-FIND")
        
        study_uid = getattr(query_ds, 'StudyInstanceUID', None)
        if not study_uid:
            logger.warning("❌ No StudyInstanceUID provided for SERIES level query")
            yield 0xC000, None
            return
        
        logger.info(f"🔍 Looking for series in study: {study_uid}")
        
        # Get series for the specified study
        series_list = self.storage.get_series_for_study(study_uid)
        logger.info(f"📊 Found {len(series_list)} series in local storage")
        
        # If no local series and we have API access, query the API
        if not series_list and self.query_handler:
            logger.info("🌐 No local series found, querying API...")
            try:
                api_data = self.query_handler.query_all_metadata()
                if api_data and 'results' in api_data:
                    # Extract series for the specified study from API data
                    unique_series = {}
                    for result_item in api_data['results']:
                        if 'dicom_data' in result_item and 'studies' in result_item['dicom_data']:
                            studies_data = result_item['dicom_data']['studies']
                            if study_uid in studies_data:
                                study_info = studies_data[study_uid]
                                if 'series' in study_info:
                                    for series_uid_key, series_info in study_info['series'].items():
                                        if series_uid_key and series_uid_key not in unique_series:
                                            # De-anonymize the patient information
                                            original_name = self._get_original_patient_name(study_info.get('patient_name', ''))
                                            original_id = self._get_original_patient_id(study_info.get('patient_id', ''))
                                            
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
                    
                    series_list = list(unique_series.values())
                    logger.info(f"🌐 Found {len(series_list)} series from API")
                else:
                    logger.warning("🌐 API query returned no data")
            except Exception as e:
                logger.error(f"❌ Error querying API: {e}")
        
        response_count = 0
        for series_info in series_list:
            # Create response dataset
            response_ds = Dataset()
            response_ds.QueryRetrieveLevel = 'SERIES'
            
            # Set patient information (already de-anonymized if from API)
            response_ds.PatientName = series_info.get('PatientName', '')
            response_ds.PatientID = series_info.get('PatientID', '')
            
            # Set study information
            response_ds.StudyInstanceUID = series_info.get('StudyInstanceUID', '')
            
            # Set series information
            response_ds.SeriesInstanceUID = series_info.get('SeriesInstanceUID', '')
            response_ds.SeriesNumber = series_info.get('SeriesNumber', '')
            response_ds.SeriesDescription = series_info.get('SeriesDescription', '')
            response_ds.Modality = series_info.get('Modality', '')
            response_ds.SeriesDate = series_info.get('SeriesDate', '')
            response_ds.SeriesTime = series_info.get('SeriesTime', '')
            
            if 'NumberOfSeriesRelatedInstances' in series_info:
                response_ds.NumberOfSeriesRelatedInstances = series_info['NumberOfSeriesRelatedInstances']
            
            logger.info(f"📤 Returning series #{response_count + 1}:")
            logger.info(f"   👤 Patient: {response_ds.PatientName} (ID: {response_ds.PatientID})")
            logger.info(f"   📁 Series: {response_ds.SeriesDescription or 'No Description'} (#{response_ds.SeriesNumber or 'N/A'})")
            logger.info(f"   🏥 Modality: {response_ds.Modality or 'Unknown'}")
            logger.info(f"   🆔 UID: {response_ds.SeriesInstanceUID}")
            logger.info(f"   🖼️ Images: {getattr(response_ds, 'NumberOfSeriesRelatedInstances', 0)}")
            
            response_count += 1
            yield 0xFF00, response_ds  # Pending status
        
        # Final status
        logger.info(f"✅ SERIES query completed - returned {response_count} series")
        logger.info("=" * 60)
        yield 0x0000, None  # Success
    
    def _find_images(self, query_ds):
        """Find images matching the query"""
        logger.info("🖼️ Processing IMAGE level C-FIND")
        
        study_uid = getattr(query_ds, 'StudyInstanceUID', None)
        series_uid = getattr(query_ds, 'SeriesInstanceUID', None)
        
        if not study_uid or not series_uid:
            logger.warning("❌ StudyInstanceUID and SeriesInstanceUID required for IMAGE level query")
            yield 0xC000, None
            return
        
        logger.info(f"🔍 Looking for images in study: {study_uid}")
        logger.info(f"🔍 Series: {series_uid}")
        
        # Get images for the specified series
        images = self.storage.get_images_for_series(study_uid, series_uid)
        logger.info(f"📊 Found {len(images)} images in local storage")
        
        # If no local images and we have API access, query the API
        if not images and self.query_handler:
            logger.info("🌐 No local images found, querying API...")
            try:
                api_data = self.query_handler.query_all_metadata()
                if api_data and 'results' in api_data:
                    # Extract images for the specified series from API data
                    unique_images = {}
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
                                                original_name = self._get_original_patient_name(instance_info.get('patient_name', ''))
                                                original_id = self._get_original_patient_id(instance_info.get('patient_id', ''))
                                                
                                                unique_images[sop_uid] = {
                                                    'PatientName': original_name or instance_info.get('patient_name', ''),
                                                    'PatientID': original_id or instance_info.get('patient_id', ''),
                                                    'StudyInstanceUID': study_uid,
                                                    'SeriesInstanceUID': series_uid,
                                                    'SOPInstanceUID': sop_uid,
                                                    'SOPClassUID': '',  # Not available in this structure
                                                    'InstanceNumber': instance_info.get('instance_number', '')
                                                }
                    
                    images = list(unique_images.values())
                    logger.info(f"🌐 Found {len(images)} images from API")
                else:
                    logger.warning("🌐 API query returned no data")
            except Exception as e:
                logger.error(f"❌ Error querying API: {e}")
        
        response_count = 0
        for image_info in images:
            # Create response dataset
            response_ds = Dataset()
            response_ds.QueryRetrieveLevel = 'IMAGE'
            
            # Set patient information (already de-anonymized if from API)
            response_ds.PatientName = image_info.get('PatientName', '')
            response_ds.PatientID = image_info.get('PatientID', '')
            
            # Set study information
            response_ds.StudyInstanceUID = image_info.get('StudyInstanceUID', '')
            
            # Set series information
            response_ds.SeriesInstanceUID = image_info.get('SeriesInstanceUID', '')
            
            # Set image information
            response_ds.SOPInstanceUID = image_info.get('SOPInstanceUID', '')
            response_ds.SOPClassUID = image_info.get('SOPClassUID', '')
            response_ds.InstanceNumber = image_info.get('InstanceNumber', '')
            
            logger.info(f"📤 Returning image #{response_count + 1}:")
            logger.info(f"   👤 Patient: {response_ds.PatientName} (ID: {response_ds.PatientID})")
            logger.info(f"   🖼️ Instance: #{response_ds.InstanceNumber or 'N/A'}")
            logger.info(f"   🆔 SOP UID: {response_ds.SOPInstanceUID}")
            logger.info(f"   📋 SOP Class: {response_ds.SOPClassUID}")
            
            response_count += 1
            yield 0xFF00, response_ds  # Pending status
        
        # Final status
        logger.info(f"✅ IMAGE query completed - returned {response_count} images")
        logger.info("=" * 60)
        yield 0x0000, None  # Success
    
    def _get_original_patient_name(self, anonymized_name):
        """Get the original patient name from anonymized name"""
        if not anonymized_name:
            return None
        
        # Check if this is an anonymized name that we can de-anonymize
        reverse_map = {v: k for k, v in self.encryptor.patient_name_map.items()}
        return reverse_map.get(anonymized_name, None)
    
    def _get_original_patient_id(self, anonymized_id):
        """Get the original patient ID from anonymized ID"""
        if not anonymized_id:
            return None
        
        # For patient ID, we use the same logic as patient name
        reverse_map = {v: k for k, v in self.encryptor.patient_name_map.items()}
        return reverse_map.get(anonymized_id, None)
    
    def _de_anonymize_dataset(self, dataset):
        """De-anonymize patient information in a DICOM dataset"""
        try:
            # De-anonymize PatientName
            if hasattr(dataset, 'PatientName'):
                original_name = self._get_original_patient_name(str(dataset.PatientName))
                if original_name:
                    dataset.PatientName = original_name
                    logger.debug(f"🔄 De-anonymized PatientName: {dataset.PatientName}")
            
            # De-anonymize PatientID  
            if hasattr(dataset, 'PatientID'):
                original_id = self._get_original_patient_id(str(dataset.PatientID))
                if original_id:
                    dataset.PatientID = original_id
                    logger.debug(f"🔄 De-anonymized PatientID: {dataset.PatientID}")
            
            # Restore other anonymized fields from "ANON" to original values if available
            # Note: Since we only store patient name mapping, other fields remain "ANON"
            # This could be extended to restore other fields if needed
            
        except Exception as e:
            logger.warning(f"⚠️ Error de-anonymizing dataset: {e}")
    
    def _get_study(self, query_ds):
        """Handle C-GET request for study level"""
        logger.info("📚 Processing STUDY level C-GET")
        
        study_uid = getattr(query_ds, 'StudyInstanceUID', None)
        if not study_uid:
            logger.warning("❌ No StudyInstanceUID provided for C-GET")
            yield 0xC000, None
            return
        
        logger.info(f"🔍 Downloading study: {study_uid}")
        
        # First check if we have it locally
        local_files = self.storage.get_images_for_study(study_uid)
        if local_files:
            logger.info(f"📁 Found {len(local_files)} local files for study")
            yield from self._send_local_files(local_files)
            return
        
        # Download from API if not local
        if not self.query_handler:
            logger.warning("❌ No API access configured for download")
            yield 0xC000, None
            return
        
        try:
            # Get the result_id for this study
            result_id = self._get_result_id_for_study(study_uid)
            if not result_id:
                logger.warning(f"❌ No result_id found for study: {study_uid}")
                yield 0xC000, None
                return
            
            # Download the study ZIP from API
            logger.info(f"🌐 Downloading study from API (result_id: {result_id})")
            dicom_files = self._download_study_from_api(result_id, study_uid)
            
            if not dicom_files:
                logger.warning(f"❌ Failed to download study: {study_uid}")
                yield 0xC000, None
                return
            
            # Send the downloaded files
            logger.info(f"📤 Sending {len(dicom_files)} downloaded files")
            yield from self._send_downloaded_files(dicom_files)
            
        except Exception as e:
            logger.error(f"❌ Error downloading study {study_uid}: {e}")
            yield 0xC000, None
    
    def _get_series(self, query_ds):
        """Handle C-GET request for series level"""
        logger.info("📁 Processing SERIES level C-GET")
        
        study_uid = getattr(query_ds, 'StudyInstanceUID', None)
        series_uid = getattr(query_ds, 'SeriesInstanceUID', None)
        
        if not study_uid or not series_uid:
            logger.warning("❌ StudyInstanceUID and SeriesInstanceUID required for SERIES C-GET")
            yield 0xC000, None
            return
        
        logger.info(f"🔍 Downloading series: {series_uid} from study: {study_uid}")
        
        # Check local storage first
        local_files = self.storage.get_images_for_series(study_uid, series_uid)
        if local_files:
            logger.info(f"📁 Found {len(local_files)} local files for series")
            yield from self._send_local_files(local_files)
            return
        
        # Download from API - get the whole study and filter for this series
        if not self.query_handler:
            logger.warning("❌ No API access configured for download")
            yield 0xC000, None
            return
        
        try:
            result_id = self._get_result_id_for_study(study_uid)
            if not result_id:
                logger.warning(f"❌ No result_id found for study: {study_uid}")
                yield 0xC000, None
                return
            
            # Download the study and filter for the specific series
            logger.info(f"🌐 Downloading study from API and filtering for series")
            dicom_files = self._download_study_from_api(result_id, study_uid, series_filter=series_uid)
            
            if not dicom_files:
                logger.warning(f"❌ No files found for series: {series_uid}")
                yield 0xC000, None
                return
            
            logger.info(f"📤 Sending {len(dicom_files)} downloaded files for series")
            yield from self._send_downloaded_files(dicom_files)
            
        except Exception as e:
            logger.error(f"❌ Error downloading series {series_uid}: {e}")
            yield 0xC000, None
    
    def _get_image(self, query_ds):
        """Handle C-GET request for image level"""
        logger.info("🖼️ Processing IMAGE level C-GET")
        
        study_uid = getattr(query_ds, 'StudyInstanceUID', None)
        series_uid = getattr(query_ds, 'SeriesInstanceUID', None)
        sop_uid = getattr(query_ds, 'SOPInstanceUID', None)
        
        if not study_uid or not series_uid or not sop_uid:
            logger.warning("❌ StudyInstanceUID, SeriesInstanceUID, and SOPInstanceUID required for IMAGE C-GET")
            yield 0xC000, None
            return
        
        logger.info(f"🔍 Downloading image: {sop_uid}")
        
        # Check local storage first
        local_file = self.storage.get_file_path(study_uid, series_uid, sop_uid)
        if local_file.exists():
            logger.info(f"📁 Found local file: {local_file}")
            yield from self._send_local_files([str(local_file)])
            return
        
        # Download from API - get the whole study and filter for this instance
        if not self.query_handler:
            logger.warning("❌ No API access configured for download")
            yield 0xC000, None
            return
        
        try:
            result_id = self._get_result_id_for_study(study_uid)
            if not result_id:
                logger.warning(f"❌ No result_id found for study: {study_uid}")
                yield 0xC000, None
                return
            
            # Download the study and filter for the specific instance
            logger.info(f"🌐 Downloading study from API and filtering for instance")
            dicom_files = self._download_study_from_api(result_id, study_uid, instance_filter=sop_uid)
            
            if not dicom_files:
                logger.warning(f"❌ Instance not found: {sop_uid}")
                yield 0xC000, None
                return
            
            logger.info(f"📤 Sending downloaded instance")
            yield from self._send_downloaded_files(dicom_files)
            
        except Exception as e:
            logger.error(f"❌ Error downloading instance {sop_uid}: {e}")
            yield 0xC000, None
    
    def _study_complete_handler(self, study_uid):
        """
        Handle study completion - zip and upload study
        
        Parameters:
        -----------
        study_uid : str
            Study UID of the completed study
        """
        if not self.auto_upload:
            return
        
        logger.info(f"Processing completed study: {study_uid}")
        
        # Get the study directory using the backward compatibility method
        study_dir = self.storage.get_study_path_by_uid(study_uid)
        
        if not study_dir.exists():
            logger.error(f"Study directory not found: {study_dir}")
            return
        
        try:
            # Get the anonymized patient name for this study
            anonymized_name = self.encryptor.get_anonymized_patient_name(study_uid)
            if not anonymized_name:
                logger.warning(f"No anonymized patient name found for study {study_uid}, using study UID")
                anonymized_name = study_uid
            
            # Use anonymized patient name for zip file
            zip_path = self.zip_dir / f"{anonymized_name}.zip"
            
            zip_file = self.api_uploader.zip_study(study_dir, str(zip_path))
            
            if not zip_file:
                logger.error(f"Failed to create zip file for study: {study_uid}")
                return
            
            success, response_data = self.api_uploader.upload_study(
                zip_file,
                study_info={
                    'name': anonymized_name,
                },
                study_dir=str(study_dir) if self.cleanup_after_upload else None
            )
            
            if success:
                logger.info(f"Successfully uploaded study: {study_uid} as {anonymized_name}")
                if response_data and 'id' in response_data:
                    logger.info(f"Dataset ID: {response_data.get('id')}")
                if self.cleanup_after_upload:
                    logger.info(f"Cleaned up files for study: {study_uid}")
            else:
                logger.error(f"Failed to upload study: {study_uid}")
                
        except Exception as e:
            logger.error(f"Error processing completed study {study_uid}: {e}")
    
    def _get_result_id_for_study(self, study_uid):
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
    
    def _download_study_from_api(self, result_id, study_uid, series_filter=None, instance_filter=None):
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
    
    def _send_local_files(self, file_paths):
        """Send local DICOM files via C-GET response"""
        try:
            from pydicom import dcmread
            
            # First yield the number of sub-operations
            yield len(file_paths)
            
            sent_count = 0
            for file_path in file_paths:
                try:
                    # Read the DICOM file
                    ds = dcmread(file_path)
                    
                    # De-anonymize patient information in the local DICOM file
                    self._de_anonymize_dataset(ds)
                    
                    # Send as C-STORE sub-operation
                    logger.info(f"📤 Sending de-anonymized local file: {Path(file_path).name} (Patient: {getattr(ds, 'PatientName', 'Unknown')})")
                    yield 0xFF00, ds  # Pending with dataset
                    sent_count += 1
                    
                except Exception as e:
                    logger.warning(f"⚠️ Could not send file {file_path}: {e}")
                    continue
            
            logger.info(f"✅ C-GET completed - sent {sent_count} de-anonymized local files")
            yield 0x0000, None  # Success
            
        except Exception as e:
            logger.error(f"❌ Error sending local files: {e}")
            yield 0xC000, None  # Unable to process
    
    def _send_downloaded_files(self, file_data_list):
        """Send downloaded DICOM file data via C-GET response"""
        try:
            from pydicom import dcmread
            from io import BytesIO
            
            # First yield the number of sub-operations
            yield len(file_data_list)
            
            sent_count = 0
            for file_data in file_data_list:
                try:
                    # Read DICOM from bytes
                    ds = dcmread(BytesIO(file_data))
                    
                    # De-anonymize patient information in the downloaded DICOM file
                    self._de_anonymize_dataset(ds)
                    
                    # Send as C-STORE sub-operation
                    logger.info(f"📤 Sending de-anonymized file: {getattr(ds, 'SOPInstanceUID', 'Unknown')} (Patient: {getattr(ds, 'PatientName', 'Unknown')})")
                    yield 0xFF00, ds  # Pending with dataset
                    sent_count += 1
                    
                except Exception as e:
                    logger.warning(f"⚠️ Could not send downloaded file: {e}")
                    continue
            
            logger.info(f"✅ C-GET completed - sent {sent_count} de-anonymized files")
            logger.info("=" * 60)
            yield 0x0000, None  # Success
            
        except Exception as e:
            logger.error(f"❌ Error sending downloaded files: {e}")
            yield 0xC000, None  # Unable to process
    
    def _server_process(self):
        """Run the DICOM server in a separate thread"""
        try:
            self.ae = AE(ae_title=self.ae_title)
            
            # Add storage presentation contexts
            self.ae.supported_contexts = StoragePresentationContexts
            
            # Add query/retrieve presentation contexts for C-FIND
            self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
            self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelFind)
            self.ae.add_supported_context(ModalityWorklistInformationFind)
            
            # C-GET disabled due to presentation context issues with some DICOM viewers
            # self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelGet)
            # self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelGet)
            
            # Add verification context
            self.ae.add_supported_context(Verification)
            
            for context in self.ae.supported_contexts:
                context.transfer_syntax = [
                    ExplicitVRLittleEndian, 
                    ImplicitVRLittleEndian
                ]
            
            handlers = [
                (evt.EVT_C_STORE, self._handle_store),
                (evt.EVT_C_FIND, self._handle_find),
                # C-GET disabled due to presentation context issues
                # (evt.EVT_C_GET, self._handle_get)
            ]
            
            self.ae.start_server(
                ("0.0.0.0", self.port), 
                block=False, 
                evt_handlers=handlers
            )
            
            logger.info(f"DICOM server running on port {self.port}")
            logger.info("C-FIND queries supported for browsing studies")
            logger.info("C-GET disabled - use dicom-query command or API for downloads")
            
            while not self.shutdown_event.is_set():
                time.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Error in DICOM server process: {e}")
        finally:
            if self.ae:
                self.ae.shutdown()
                logger.info("DICOM server has been shut down")
    
    def start(self):
        """Start the DICOM receiver service in non-blocking mode"""
        if self.is_running:
            logger.warning("DICOM server is already running")
            return
            
        logger.info(f"Starting DICOM receiver on port {self.port}")
        logger.info(f"AE Title: {self.ae_title}")
        
        self.is_running = True
        self.shutdown_event.clear()
        
        self.server_thread = threading.Thread(target=self._server_process, daemon=True)
        self.server_thread.start()
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            while self.server_thread.is_alive():
                self.server_thread.join(1.0)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, stopping DICOM receiver")
            self.stop()
    
    def stop(self):
        """Stop the DICOM receiver service"""
        if not self.is_running:
            logger.warning("DICOM server is not running")
            return
            
        logger.info("Stopping DICOM receiver...")
        self.shutdown_event.set()
        
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(5.0)
            
        self.is_running = False
        logger.info("DICOM receiver stopped")
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals for graceful shutdown"""
        logger.info(f"Received signal {signum}, stopping DICOM receiver")
        self.stop() 