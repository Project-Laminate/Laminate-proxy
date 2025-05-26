#!/usr/bin/env python
"""
DICOM C-MOVE Handler

Handles C-MOVE operations by sending files to a specified destination AE.
C-MOVE is more widely supported than C-GET by DICOM viewers like Horos.
"""

import logging
from pathlib import Path
from io import BytesIO

from pydicom import dcmread

from dicom_receiver.core.config import AEConfiguration

logger = logging.getLogger('dicom_receiver.handlers.move')

class MoveHandler:
    """
    Handler for DICOM C-MOVE operations
    
    C-MOVE works by sending files to a specified destination AE (Application Entity)
    rather than sending them back directly to the requesting client like C-GET does.
    This makes it more compatible with DICOM viewers like Horos.
    """
    
    def __init__(self, storage, query_handler, anonymization_utils, api_integration_utils, ae_config=None):
        """
        Initialize the C-MOVE handler
        
        Parameters:
        -----------
        storage : DicomStorage
            Storage handler for local DICOM files
        query_handler : DicomQueryHandler
            Handler for API queries (can be None for local-only)
        anonymization_utils : AnonymizationUtils
            Utilities for de-anonymization
        api_integration_utils : ApiIntegrationUtils
            Utilities for API integration (can be None for local-only)
        ae_config : AEConfiguration, optional
            AE configuration for destination mapping
        """
        self.storage = storage
        self.query_handler = query_handler
        self.anonymization_utils = anonymization_utils
        self.api_integration_utils = api_integration_utils
        self.ae_config = ae_config or AEConfiguration()
        
    def handle_move(self, event):
        """
        Handle C-MOVE request
        
        For C-MOVE, pynetdicom expects us to:
        1. Return the destination address
        2. Yield the datasets to be moved
        3. pynetdicom handles the actual C-STORE operations automatically
        
        Parameters:
        -----------
        event : pynetdicom.events.Event
            The C-MOVE request event
            
        Yields:
        -------
        tuple or Dataset or int
            Destination address, datasets, or status codes
        """
        try:
            request = event.request
            # Handle both string and bytes for MoveDestination
            if hasattr(request.MoveDestination, 'decode'):
                move_destination = request.MoveDestination.decode('utf-8').strip()
            else:
                move_destination = str(request.MoveDestination).strip()
            
            logger.info(f"🔄 C-MOVE request received")
            logger.info(f"📍 Move Destination AE: {move_destination}")
            
            # Get the identifier and log query parameters
            identifier = request.Identifier
            query_level = getattr(identifier, 'QueryRetrieveLevel', 'STUDY')
            logger.info(f"🔍 Query Level: {query_level}")
            
            # Debug: Log the raw identifier structure
            logger.info(f"🔍 Raw identifier elements:")
            for elem in identifier:
                # Avoid logging binary data
                if elem.value is not None:
                    if isinstance(elem.value, (str, int, float)):
                        display_value = str(elem.value)[:100] + "..." if len(str(elem.value)) > 100 else str(elem.value)
                    else:
                        display_value = f"<{type(elem.value).__name__}>"
                else:
                    display_value = "None"
                logger.info(f"   {elem.keyword} ({elem.tag}): {display_value} (VR: {elem.VR})")
            
            # Log the query parameters
            query_params = {}
            for elem in identifier:
                if elem.value and str(elem.value).strip():
                    query_params[elem.keyword] = str(elem.value).strip()
                elif elem.keyword in ['QueryRetrieveLevel', 'StudyInstanceUID', 'SeriesInstanceUID', 'SOPInstanceUID', 'PatientID']:
                    # Log important fields even if empty
                    query_params[elem.keyword] = str(elem.value) if elem.value else '<empty>'
            
            logger.info(f"🔍 Query parameters: {query_params}")
            
            # Extract StudyInstanceUID directly from identifier
            study_uid = None
            for elem in identifier:
                if elem.keyword == 'StudyInstanceUID' and elem.value:
                    study_uid = str(elem.value).strip()
                    logger.info(f"🔍 Extracted StudyInstanceUID: {study_uid}")
                    break
            
            # Get the destination AE's network address from configuration
            destination_ip, destination_port = self.ae_config.get_ae_address(move_destination)
            logger.info(f"🌐 Destination address: {destination_ip}:{destination_port}")
            
            # Check if we have any files to move before yielding destination
            # This prevents unnecessary connection attempts
            temp_local_files = self._find_local_files(identifier, study_uid)
            temp_api_files = []
            if not temp_local_files and self.api_integration_utils:
                logger.info("📡 No local files found, checking API...")
                temp_api_files = self._find_api_files(identifier, study_uid)
            
            total_temp_files = len(temp_local_files) + len(temp_api_files)
            
            if total_temp_files == 0:
                logger.warning("❌ No matching files found for C-MOVE request")
                logger.warning(f"   Searched for StudyInstanceUID: {study_uid}")
                logger.warning(f"   Query Level: {query_level}")
                yield 0xA701  # Refused: Out of Resources - Unable to perform sub-operations
                return
            
            logger.info(f"📁 Found {total_temp_files} files to move ({len(temp_local_files)} local, {len(temp_api_files)} from API)")
            logger.info(f"🚀 Initiating C-MOVE to {move_destination} at {destination_ip}:{destination_port}")
            
            # First yield the destination address (required by pynetdicom for C-MOVE)
            yield (destination_ip, destination_port)
            
            # Use the files we already found
            local_files = temp_local_files
            api_files = temp_api_files
            total_files = total_temp_files
            
            # Yield the number of sub-operations
            yield total_files
            
            sent_count = 0
            
            # Yield local files as datasets
            for file_path in local_files:
                try:
                    # Read the DICOM dataset
                    ds = dcmread(file_path)
                    
                    # De-anonymize patient information
                    self.anonymization_utils.de_anonymize_dataset(ds)
                    
                    sent_count += 1
                    logger.info(f"📤 Yielding local file {sent_count}/{total_files}: {Path(file_path).name}")
                    
                    # Yield the dataset - pynetdicom will handle the C-STORE
                    yield 0xFF00, ds  # Pending with dataset
                    
                except Exception as e:
                    logger.error(f"❌ Error processing local file {Path(file_path).name}: {e}")
                    yield 0xB000  # Warning: Sub-operations Complete - One or more Failures
            
            # Yield API files as datasets
            for file_data in api_files:
                try:
                    # Read the DICOM dataset from bytes
                    ds = dcmread(BytesIO(file_data))
                    
                    # De-anonymize patient information
                    self.anonymization_utils.de_anonymize_dataset(ds)
                    
                    sent_count += 1
                    logger.info(f"📤 Yielding API file {sent_count}/{total_files}")
                    
                    # Yield the dataset - pynetdicom will handle the C-STORE
                    yield 0xFF00, ds  # Pending with dataset
                    
                except Exception as e:
                    logger.error(f"❌ Error processing API file: {e}")
                    yield 0xB000  # Warning: Sub-operations Complete - One or more Failures
            
            # Final status
            logger.info(f"🎉 C-MOVE completed: {sent_count}/{total_files} files yielded to pynetdicom for transmission")
            yield 0x0000  # Success
                
        except Exception as e:
            logger.error(f"❌ Error in C-MOVE handler: {e}")
            yield 0xA701  # Refused: Out of Resources - Unable to perform sub-operations
    
    def _find_local_files(self, identifier, study_uid=None):
        """Find matching files in local storage"""
        try:
            # Use the same logic as the find handler to locate files
            files = []
            
            # Get query level
            query_level = getattr(identifier, 'QueryRetrieveLevel', 'STUDY')
            
            if query_level == 'PATIENT':
                patient_id = getattr(identifier, 'PatientID', None)
                if patient_id:
                    # Find all studies for this patient
                    patient_dir = self.storage.storage_dir / patient_id
                    if patient_dir.exists():
                        for study_dir in patient_dir.iterdir():
                            if study_dir.is_dir():
                                files.extend(self._get_all_files_in_study(study_dir))
            
            elif query_level == 'STUDY':
                # Use the passed study_uid or extract from identifier
                if not study_uid:
                    study_uid = getattr(identifier, 'StudyInstanceUID', None)
                    if study_uid:
                        study_uid = str(study_uid).strip()
                
                if study_uid and study_uid.strip():
                    logger.info(f"🔍 Looking for study: {study_uid}")
                    study_dir = self.storage.get_study_path_by_uid(study_uid)
                    if study_dir and study_dir.exists():
                        logger.info(f"📁 Found study directory: {study_dir}")
                        files.extend(self._get_all_files_in_study(study_dir))
                    else:
                        logger.warning(f"📁 Study directory not found for UID: {study_uid}")
                else:
                    logger.warning("❌ No StudyInstanceUID provided for STUDY level query")
            
            elif query_level == 'SERIES':
                series_uid = getattr(identifier, 'SeriesInstanceUID', None)
                if series_uid:
                    # Find series across all studies
                    for patient_dir in self.storage.storage_dir.iterdir():
                        if patient_dir.is_dir():
                            for study_dir in patient_dir.iterdir():
                                if study_dir.is_dir():
                                    series_dir = study_dir / series_uid
                                    if series_dir.exists():
                                        files.extend(self._get_all_files_in_series(series_dir))
            
            elif query_level == 'IMAGE':
                sop_uid = getattr(identifier, 'SOPInstanceUID', None)
                if sop_uid:
                    # Find specific image across all studies
                    for patient_dir in self.storage.storage_dir.iterdir():
                        if patient_dir.is_dir():
                            for study_dir in patient_dir.iterdir():
                                if study_dir.is_dir():
                                    for series_dir in study_dir.iterdir():
                                        if series_dir.is_dir():
                                            for file_path in series_dir.glob('*.dcm'):
                                                try:
                                                    ds = dcmread(file_path, stop_before_pixels=True)
                                                    if getattr(ds, 'SOPInstanceUID', None) == sop_uid:
                                                        files.append(file_path)
                                                except:
                                                    continue
            
            return files
            
        except Exception as e:
            logger.error(f"Error finding local files: {e}")
            return []
    
    def _find_api_files(self, identifier, study_uid=None):
        """Find matching files from API and download them"""
        try:
            if not self.api_integration_utils:
                return []
            
            # Use the API integration utils to download files
            query_level = getattr(identifier, 'QueryRetrieveLevel', 'STUDY')
            
            if query_level == 'STUDY':
                # Use the passed study_uid or extract from identifier
                if not study_uid:
                    study_uid = getattr(identifier, 'StudyInstanceUID', None)
                    if study_uid:
                        study_uid = str(study_uid).strip()
                
                if study_uid and study_uid.strip():
                    logger.info(f"🌐 Downloading study from API: {study_uid}")
                    return self.api_integration_utils.download_study_files(study_uid)
            
            elif query_level == 'SERIES':
                series_uid = getattr(identifier, 'SeriesInstanceUID', None)
                study_uid = getattr(identifier, 'StudyInstanceUID', None)
                if series_uid:
                    return self.api_integration_utils.download_series_files(series_uid, study_uid)
            
            elif query_level == 'IMAGE':
                sop_uid = getattr(identifier, 'SOPInstanceUID', None)
                series_uid = getattr(identifier, 'SeriesInstanceUID', None)
                study_uid = getattr(identifier, 'StudyInstanceUID', None)
                if sop_uid:
                    return self.api_integration_utils.download_image_files(sop_uid, series_uid, study_uid)
            
            return []
            
        except Exception as e:
            logger.error(f"Error finding API files: {e}")
            return []
    
    def _get_all_files_in_study(self, study_dir):
        """Get all DICOM files in a study directory"""
        files = []
        for series_dir in study_dir.iterdir():
            if series_dir.is_dir():
                files.extend(self._get_all_files_in_series(series_dir))
        return files
    
    def _get_all_files_in_series(self, series_dir):
        """Get all DICOM files in a series directory"""
        return list(series_dir.glob('*.dcm'))
    
 