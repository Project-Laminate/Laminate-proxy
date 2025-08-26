#!/usr/bin/env python
"""
C-STORE Handler for DICOM operations

Handles incoming DICOM file storage requests
"""

import logging

logger = logging.getLogger('dicom_receiver.handlers.store')

class StoreHandler:
    """Handler for C-STORE operations"""
    
    def __init__(self, storage, study_monitor, encryptor):
        """
        Initialize the store handler
        
        Parameters:
        -----------
        storage : DicomStorage
            Storage handler for DICOM files
        study_monitor : StudyMonitor
            Monitor for tracking study completion
        encryptor : DicomEncryptor/DicomAnonymizer
            Encryptor/anonymizer for patient information
        """
        self.storage = storage
        self.study_monitor = study_monitor
        self.encryptor = encryptor
    
    def handle_store(self, event):
        """Handle a C-STORE request"""
        dataset = event.dataset
        
        study_uid = dataset.StudyInstanceUID
        series_uid = dataset.SeriesInstanceUID
        instance_uid = dataset.SOPInstanceUID
        
        # Log PatientID before processing
        patient_id_before = getattr(dataset, 'PatientID', 'NOT_FOUND')
        logger.info(f"📥 Storing DICOM - PatientID: '{patient_id_before}', Study: {study_uid}")
        
        self.study_monitor.update_study_activity(study_uid)
        
        # Pass the dataset to get_file_path to determine the patient ID
        file_path = self.storage.get_file_path(study_uid, series_uid, instance_uid, dataset=dataset)
        
        # Encrypt patient information
        self.encryptor.encrypt_dataset(dataset)
        
        # Ensure proper DICOM file metadata for pixel data accessibility
        self._fix_dicom_file_metadata(dataset)
        
        # Save the file
        dataset.save_as(file_path)
        
        logger.info(f"✅ Stored DICOM file: {file_path}")
        
        return 0x0000
    
    def _fix_dicom_file_metadata(self, dataset):
        """Fix DICOM file metadata to ensure pixel data accessibility and Horos compatibility"""
        try:
            import pydicom
            from pydicom.uid import ImplicitVRLittleEndian, ExplicitVRLittleEndian
            
            # CRITICAL: Add DICOM preamble for Horos compatibility
            if not hasattr(dataset, 'preamble') or dataset.preamble is None:
                dataset.preamble = b'\x00' * 128  # 128-byte preamble required by DICOM standard
                logger.debug("Added DICOM preamble for viewer compatibility")
            
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
            
            # Fix patient name format for better Horos compatibility
            if hasattr(dataset, 'PatientName'):
                patient_name = str(dataset.PatientName)
                if patient_name.startswith('sub-') and '^' not in patient_name:
                    # Convert "sub-002" to "sub-002^" format (more DICOM compliant)
                    dataset.PatientName = f"{patient_name}^"
                    logger.debug(f"Fixed patient name format for DICOM compliance: {patient_name} -> {dataset.PatientName}")
            
        except Exception as e:
            logger.warning(f"⚠️ Error fixing DICOM file metadata: {e}") 