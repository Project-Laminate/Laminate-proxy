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
        
        self.study_monitor.update_study_activity(study_uid)
        
        # Pass the dataset to get_file_path to determine the patient ID
        file_path = self.storage.get_file_path(study_uid, series_uid, instance_uid, dataset=dataset)
        
        # Encrypt patient information
        self.encryptor.encrypt_dataset(dataset)
        
        # Save the file
        dataset.save_as(file_path)
        
        logger.info(f"Stored DICOM file: {file_path}")
        
        return 0x0000 