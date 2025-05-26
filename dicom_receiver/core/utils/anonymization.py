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
    
    def get_original_patient_id(self, anonymized_id):
        """Get the original patient ID from anonymized ID"""
        if not anonymized_id:
            return None
        
        # First try to find the original PatientID in the patient info map
        if hasattr(self.encryptor, 'patient_info_map'):
            for study_uid, patient_info in self.encryptor.patient_info_map.items():
                if 'PatientID' in patient_info:
                    # Check if this study has the anonymized ID we're looking for
                    # by checking if the PatientName was anonymized to this value
                    if 'PatientName' in patient_info:
                        original_name = patient_info['PatientName']
                        if original_name in self.encryptor.patient_name_map:
                            if self.encryptor.patient_name_map[original_name] == anonymized_id:
                                return patient_info['PatientID']
        
        # Fallback: use the same logic as patient name (for backward compatibility)
        reverse_map = {v: k for k, v in self.encryptor.patient_name_map.items()}
        return reverse_map.get(anonymized_id, None)
    
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
            
            # De-anonymize PatientID using the same logic as PatientName
            # (since both are anonymized to the same value during anonymization)
            if hasattr(dataset, 'PatientID'):
                original_id = self.get_original_patient_id(str(dataset.PatientID))
                if original_id:
                    dataset.PatientID = original_id
                    logger.debug(f"🔄 De-anonymized PatientID: {dataset.PatientID}")
            
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