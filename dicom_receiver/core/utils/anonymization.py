#!/usr/bin/env python
"""
Anonymization utilities for DICOM data

Handles de-anonymization of patient information for query responses
"""

import logging

logger = logging.getLogger('dicom_receiver.utils.anonymization')

class AnonymizationUtils:
    """Utilities for handling anonymization and de-anonymization"""
    
    def __init__(self, encryptor):
        """
        Initialize with encryptor/anonymizer instance
        
        Parameters:
        -----------
        encryptor : DicomEncryptor/DicomAnonymizer
            The anonymizer instance with patient name mappings
        """
        self.encryptor = encryptor
    
    def get_original_patient_name(self, anonymized_name):
        """Get the original patient name from anonymized name"""
        if not anonymized_name:
            return None
        
        # Check if this is an anonymized name that we can de-anonymize
        reverse_map = {v: k for k, v in self.encryptor.patient_name_map.items()}
        return reverse_map.get(anonymized_name, None)
    
    def get_original_patient_id(self, patient_id):
        """Get the original patient ID from patient ID (handles both old and new anonymization)"""
        if not patient_id:
            return None
        
        # Check if this is an old anonymized ID (like "sub-001") that needs to be de-anonymized
        if hasattr(self.encryptor, 'patient_info_map'):
            for study_uid, patient_info in self.encryptor.patient_info_map.items():
                if 'PatientID' in patient_info and 'PatientName' in patient_info:
                    original_name = patient_info['PatientName']
                    # Check if the PatientName was anonymized to this patient_id value
                    if (original_name in self.encryptor.patient_name_map and 
                        self.encryptor.patient_name_map[original_name] == patient_id):
                        # This is an old anonymized ID, return the original PatientID
                        return patient_info['PatientID']
        
        # For new format or if not found in old format, return as-is
        # This is the actual patient ID from the DICOM data
        return patient_id
    
    def de_anonymize_dataset(self, dataset):
        """De-anonymize patient information in a DICOM dataset"""
        try:
            # Use the encryptor's restore_dataset method which properly handles all PII fields
            if hasattr(self.encryptor, 'restore_dataset'):
                success = self.encryptor.restore_dataset(dataset)
                if success:
                    logger.debug(f"🔄 De-anonymized dataset using patient info map")
                    return
            
            # Fallback to manual de-anonymization using patient name mapping
            # De-anonymize PatientName
            if hasattr(dataset, 'PatientName'):
                original_name = self.get_original_patient_name(str(dataset.PatientName))
                if original_name:
                    dataset.PatientName = original_name
                    logger.debug(f"🔄 De-anonymized PatientName: {dataset.PatientName}")
            
            # PatientID is no longer anonymized, so it should already be the original value
            # But we still call get_original_patient_id for consistency and future compatibility
            if hasattr(dataset, 'PatientID'):
                original_id = self.get_original_patient_id(str(dataset.PatientID))
                if original_id:
                    dataset.PatientID = original_id
                    logger.debug(f"🔄 Verified PatientID: {dataset.PatientID}")
            
            # Restore other anonymized fields from "ANON" to original values if available
            # Note: Since we only store patient name mapping, other fields remain "ANON"
            # This could be extended to restore other fields if needed
            
        except Exception as e:
            logger.warning(f"⚠️ Error de-anonymizing dataset: {e}")
    
    def de_anonymize_patient_info(self, patient_info):
        """De-anonymize patient information in a dictionary"""
        if not patient_info:
            return patient_info
        
        result = patient_info.copy()
        
        # De-anonymize patient name
        if 'patient_name' in result:
            original_name = self.get_original_patient_name(result['patient_name'])
            if original_name:
                result['patient_name'] = original_name
        
        # De-anonymize patient ID
        if 'patient_id' in result:
            original_id = self.get_original_patient_id(result['patient_id'])
            if original_id:
                result['patient_id'] = original_id
        
        return result 