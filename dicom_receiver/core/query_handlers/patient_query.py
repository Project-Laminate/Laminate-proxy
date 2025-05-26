#!/usr/bin/env python
"""
Patient Query Handler for DICOM C-FIND operations

Handles patient-level queries with local storage and API fallback
"""

import logging
from pydicom import Dataset

logger = logging.getLogger('dicom_receiver.query.patient')

class PatientQueryHandler:
    """Handler for patient-level C-FIND queries"""
    
    def __init__(self, storage, query_handler, anonymization_utils, api_integration_utils):
        """
        Initialize the patient query handler
        
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
    
    def find_patients(self, query_ds):
        """Find patients matching the query"""
        logger.info("👤 Processing PATIENT level C-FIND")
        
        # Get all unique patients from storage
        patients = self.storage.get_all_patients()
        logger.info(f"📊 Found {len(patients)} patients in local storage")
        
        # If no local patients and we have API access, query the API
        if not patients and self.query_handler and self.api_integration_utils:
            logger.info("🌐 No local patients found, querying API...")
            try:
                api_data = self.query_handler.query_all_metadata()
                if api_data:
                    patients = self.api_integration_utils.extract_patients_from_api_data(
                        api_data, self.anonymization_utils
                    )
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