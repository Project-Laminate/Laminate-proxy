#!/usr/bin/env python
"""
C-GET Handler for DICOM operations

Handles C-GET download requests (currently disabled due to presentation context issues)
"""

import logging
from pathlib import Path
from io import BytesIO

logger = logging.getLogger('dicom_receiver.handlers.get')

class GetHandler:
    """Handler for C-GET operations (currently disabled)"""
    
    def __init__(self, storage, query_handler, anonymization_utils, api_integration_utils):
        """
        Initialize the get handler
        
        Parameters:
        -----------
        storage : DicomStorage
            Storage handler for local DICOM files
        query_handler : DicomQueryHandler
            Handler for API queries (can be None)
        anonymization_utils : AnonymizationUtils
            Utilities for de-anonymization
        api_integration_utils : ApiIntegrationUtils
            Utilities for API integration (can be None)
        """
        self.storage = storage
        self.query_handler = query_handler
        self.anonymization_utils = anonymization_utils
        self.api_integration_utils = api_integration_utils
    
    def handle_get(self, event):
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
                    # Avoid logging binary data - truncate long values
                    if isinstance(value, (str, int, float)):
                        display_value = str(value)[:100] + "..." if len(str(value)) > 100 else str(value)
                    else:
                        display_value = f"<{type(value).__name__}>"
                    logger.info(f"   {tag.keyword}: {display_value}")
        
        def get_generator():
            try:
                logger.info("Starting C-GET generator")
                
                # Set all accepted contexts as SCU for sending files back
                for cx in event.assoc.accepted_contexts:
                    cx._as_scu = True
                
                # Determine preferred transfer syntax from the association
                preferred_syntax = None
                for cx in event.assoc.accepted_contexts:
                    if cx.abstract_syntax.startswith('1.2.840.10008.5.1.4.1.2'):  # Storage contexts
                        preferred_syntax = cx.transfer_syntax[0]
                        break
                
                if not preferred_syntax:
                    # Default to Implicit VR Little Endian
                    from pydicom.uid import ImplicitVRLittleEndian
                    preferred_syntax = ImplicitVRLittleEndian
                
                logger.info(f"Using transfer syntax: {preferred_syntax}")
                
                # Get files based on query level
                files = self._get_files_for_query(query_ds, query_level)
                
                if not files:
                    logger.warning("❌ No files found for C-GET request")
                    yield 0  # No sub-operations to perform
                    return
                
                logger.info(f"Found {len(files)} files to send")
                yield len(files)
                
                # Track successful and failed transfers
                successful_transfers = 0
                failed_transfers = 0
                
                # Send each file
                for i, file_path in enumerate(files, 1):
                    try:
                        if isinstance(file_path, bytes):
                            # File data from API
                            logger.info(f"Processing API file {i}/{len(files)}")
                            ds = self._load_dataset_from_bytes(file_path, preferred_syntax)
                        else:
                            # Local file path
                            logger.info(f"Processing local file {i}/{len(files)}: {Path(file_path).name}")
                            ds = self._load_dataset_from_file(file_path, preferred_syntax)
                        
                        if ds:
                            logger.info(f"Yielding dataset {i}/{len(files)}")
                            yield (0xFF00, ds)
                            logger.info(f"Successfully sent file {i}/{len(files)}")
                            successful_transfers += 1
                        else:
                            logger.warning(f"Failed to load dataset {i}/{len(files)}")
                            failed_transfers += 1
                            
                    except Exception as e:
                        logger.error(f"Error sending file {i}/{len(files)}: {str(e)}")
                        failed_transfers += 1
                        continue
                
                # Final status based on transfer results
                if failed_transfers == 0:
                    logger.info(f"✅ C-GET completed successfully: {successful_transfers}/{len(files)} files sent")
                    # Don't yield final status - pynetdicom handles this automatically
                elif successful_transfers > 0:
                    logger.warning(f"⚠️ C-GET completed with warnings: {successful_transfers}/{len(files)} files sent, {failed_transfers} failed")
                    # Don't yield final status - pynetdicom handles this automatically
                else:
                    logger.error(f"❌ C-GET failed: no files could be sent")
                    # Don't yield final status - pynetdicom handles this automatically
                
                logger.info("Completed C-GET generator")
                
            except Exception as e:
                logger.error(f"Error in C-GET generator: {str(e)}")
                # Don't yield error status - let pynetdicom handle it
        
        return get_generator()
    
    def _get_files_for_query(self, query_ds, query_level):
        """Get files based on the query level and parameters"""
        try:
            if query_level == 'STUDY':
                return self._get_study_files(query_ds)
            elif query_level == 'SERIES':
                return self._get_series_files(query_ds)
            elif query_level == 'IMAGE':
                return self._get_image_files(query_ds)
            else:
                logger.warning(f"❌ Unsupported C-GET level: {query_level}")
                return []
        except Exception as e:
            logger.error(f"Error getting files for query: {e}")
            return []
    
    def _get_study_files(self, query_ds):
        """Get all files for a study"""
        study_uid = getattr(query_ds, 'StudyInstanceUID', None)
        if not study_uid:
            logger.warning("❌ No StudyInstanceUID provided for C-GET")
            return []
        
        logger.info(f"🔍 Getting files for study: {study_uid}")
        
        if not self.query_handler or not self.api_integration_utils:
            logger.warning("❌ No API access configured for download")
            return []
        
        try:
            # Get the result_id for this study
            result_id = self.api_integration_utils.get_result_id_for_study(study_uid)
            if not result_id:
                logger.warning(f"❌ No result_id found for study: {study_uid}")
                return []
            
            # Download the study ZIP from API
            logger.info(f"🌐 Downloading study from API (result_id: {result_id})")
            dicom_files = self.api_integration_utils.download_study_from_api(result_id, study_uid)
            
            if not dicom_files:
                logger.warning(f"❌ Failed to download study: {study_uid}")
                return []
            
            logger.info(f"📤 Downloaded {len(dicom_files)} files from API")
            return dicom_files
            
        except Exception as e:
            logger.error(f"❌ Error downloading study {study_uid}: {e}")
            return []
    
    def _get_series_files(self, query_ds):
        """Get all files for a series"""
        study_uid = getattr(query_ds, 'StudyInstanceUID', None)
        series_uid = getattr(query_ds, 'SeriesInstanceUID', None)
        
        if not study_uid or not series_uid:
            logger.warning("❌ StudyInstanceUID and SeriesInstanceUID required for SERIES C-GET")
            return []
        
        logger.info(f"🔍 Getting files for series: {series_uid} from study: {study_uid}")
        
        if not self.query_handler or not self.api_integration_utils:
            logger.warning("❌ No API access configured for download")
            return []
        
        try:
            result_id = self.api_integration_utils.get_result_id_for_study(study_uid)
            if not result_id:
                logger.warning(f"❌ No result_id found for study: {study_uid}")
                return []
            
            # Download the series directly using the series endpoint
            logger.info(f"🌐 Downloading series from API (result_id: {result_id})")
            dicom_files = self.api_integration_utils.download_series_from_api(result_id, series_uid)
            
            if not dicom_files:
                logger.warning(f"❌ No files found for series: {series_uid}")
                return []
            
            logger.info(f"📤 Downloaded {len(dicom_files)} files for series from API")
            return dicom_files
            
        except Exception as e:
            logger.error(f"❌ Error downloading series {series_uid}: {e}")
            return []
    
    def _get_image_files(self, query_ds):
        """Get specific image files (handles both single and multiple SOP Instance UIDs)"""
        study_uid = getattr(query_ds, 'StudyInstanceUID', None)
        series_uid = getattr(query_ds, 'SeriesInstanceUID', None)
        sop_uid = getattr(query_ds, 'SOPInstanceUID', None)
        
        if not study_uid or not series_uid or not sop_uid:
            logger.warning("❌ StudyInstanceUID, SeriesInstanceUID, and SOPInstanceUID required for IMAGE C-GET")
            return []
        
        # Handle multi-value SOP Instance UIDs
        if hasattr(sop_uid, '__iter__') and not isinstance(sop_uid, str):
            # Multiple SOP Instance UIDs - convert to list
            sop_uids = list(sop_uid)
            logger.info(f"🔍 Getting {len(sop_uids)} images from series: {series_uid}")
        else:
            # Single SOP Instance UID
            sop_uids = [str(sop_uid)]
            logger.info(f"🔍 Getting image: {sop_uid}")
        
        if not self.query_handler or not self.api_integration_utils:
            logger.warning("❌ No API access configured for download")
            return []
        
        try:
            result_id = self.api_integration_utils.get_result_id_for_study(study_uid)
            if not result_id:
                logger.warning(f"❌ No result_id found for study: {study_uid}")
                return []
            
            # Download the entire series from API (more efficient than individual downloads)
            logger.info(f"🌐 Downloading series from API to get requested instances")
            dicom_files = self.api_integration_utils.download_series_from_api(
                result_id, series_uid
            )
            
            if not dicom_files:
                logger.warning(f"❌ No files downloaded from API for series: {series_uid}")
                return []
            
            # Filter the downloaded files to only include the requested SOP Instance UIDs
            filtered_files = []
            for file_data in dicom_files:
                try:
                    # If file_data is bytes, we need to read it to check SOP Instance UID
                    if isinstance(file_data, bytes):
                        from pydicom import dcmread
                        from io import BytesIO
                        ds = dcmread(BytesIO(file_data), stop_before_pixels=True)
                        file_sop_uid = getattr(ds, 'SOPInstanceUID', None)
                        if file_sop_uid in sop_uids:
                            filtered_files.append(file_data)
                    else:
                        # If it's a file path, add it (assume it's already filtered)
                        filtered_files.append(file_data)
                except Exception as e:
                    logger.warning(f"Error checking SOP Instance UID in downloaded file: {e}")
                    continue
            
            if filtered_files:
                logger.info(f"📤 Downloaded {len(filtered_files)} matching instances from API")
                return filtered_files
            else:
                logger.warning(f"❌ No matching instances found in downloaded series")
                return []
            
        except Exception as e:
            logger.error(f"❌ Error downloading instances: {e}")
            return []
    
    def _load_dataset_from_file(self, file_path, preferred_syntax):
        """Load and prepare a dataset from a local file"""
        try:
            from pydicom import dcmread
            import pydicom
            
            # Read the DICOM file
            ds = dcmread(file_path, force=True)
            
            # De-anonymize patient information
            self.anonymization_utils.de_anonymize_dataset(ds)
            
            # Set transfer syntax and encoding
            ds.is_little_endian = preferred_syntax in [
                pydicom.uid.ImplicitVRLittleEndian,
                pydicom.uid.ExplicitVRLittleEndian
            ]
            ds.is_implicit_VR = preferred_syntax == pydicom.uid.ImplicitVRLittleEndian
            
            # Set file meta information properly
            if not hasattr(ds, 'file_meta') or ds.file_meta is None:
                ds.file_meta = pydicom.dataset.FileMetaDataset()
            
            # Ensure all required file meta elements are present
            ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
            ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
            ds.file_meta.TransferSyntaxUID = preferred_syntax
            ds.file_meta.ImplementationClassUID = pydicom.uid.PYDICOM_IMPLEMENTATION_UID
            ds.file_meta.ImplementationVersionName = "PYDICOM"
            
            # Set the file meta information version
            ds.file_meta.FileMetaInformationVersion = b'\x00\x01'
            
            # Ensure the dataset is properly encoded
            ds.fix_meta_info(enforce_standard=True)
            
            patient_name = getattr(ds, 'PatientName', 'Unknown')
            sop_uid = getattr(ds, 'SOPInstanceUID', 'Unknown')[:16] + "..." if len(getattr(ds, 'SOPInstanceUID', '')) > 16 else getattr(ds, 'SOPInstanceUID', 'Unknown')
            logger.info(f"📤 Prepared local file: {Path(file_path).name} (Patient: {patient_name}, SOP: {sop_uid})")
            return ds
            
        except Exception as e:
            logger.error(f"Error loading dataset from file {Path(file_path).name}: {e}")
            return None
    
    def _load_dataset_from_bytes(self, file_data, preferred_syntax):
        """Load and prepare a dataset from bytes (API download)"""
        try:
            from pydicom import dcmread
            import pydicom
            
            # Read DICOM from bytes
            ds = dcmread(BytesIO(file_data), force=True)
            
            # De-anonymize patient information
            self.anonymization_utils.de_anonymize_dataset(ds)
            
            # Set transfer syntax and encoding
            ds.is_little_endian = preferred_syntax in [
                pydicom.uid.ImplicitVRLittleEndian,
                pydicom.uid.ExplicitVRLittleEndian
            ]
            ds.is_implicit_VR = preferred_syntax == pydicom.uid.ImplicitVRLittleEndian
            
            # Set file meta information properly
            if not hasattr(ds, 'file_meta') or ds.file_meta is None:
                ds.file_meta = pydicom.dataset.FileMetaDataset()
            
            # Ensure all required file meta elements are present
            ds.file_meta.MediaStorageSOPClassUID = ds.SOPClassUID
            ds.file_meta.MediaStorageSOPInstanceUID = ds.SOPInstanceUID
            ds.file_meta.TransferSyntaxUID = preferred_syntax
            ds.file_meta.ImplementationClassUID = pydicom.uid.PYDICOM_IMPLEMENTATION_UID
            ds.file_meta.ImplementationVersionName = "PYDICOM"
            
            # Set the file meta information version
            ds.file_meta.FileMetaInformationVersion = b'\x00\x01'
            
            # Ensure the dataset is properly encoded
            ds.fix_meta_info(enforce_standard=True)
            
            patient_name = getattr(ds, 'PatientName', 'Unknown')
            sop_uid = getattr(ds, 'SOPInstanceUID', 'Unknown')[:16] + "..." if len(getattr(ds, 'SOPInstanceUID', '')) > 16 else getattr(ds, 'SOPInstanceUID', 'Unknown')
            logger.info(f"📤 Prepared API file: SOP: {sop_uid} (Patient: {patient_name})")
            return ds
            
        except Exception as e:
            logger.error(f"Error loading dataset from bytes: {e}")
            return None
    

 