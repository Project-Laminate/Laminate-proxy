#!/usr/bin/env python
"""
Study Query Handler for DICOM C-FIND operations

Handles study-level queries with local storage and API fallback
"""

import logging
from pydicom import Dataset

logger = logging.getLogger('dicom_receiver.query.study')

class StudyQueryHandler:
    """Handler for study-level C-FIND queries"""
    
    def __init__(self, storage, query_handler, anonymization_utils, api_integration_utils):
        """
        Initialize the study query handler
        
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
    
    def find_studies(self, query_ds):
        """Find studies matching the query"""
        logger.info("📚 Processing STUDY level C-FIND")
        
        # Get all studies from storage
        studies = self.storage.get_all_studies()
        logger.info(f"📊 Found {len(studies)} studies in local storage")
        
        # If no local studies and we have API access, query the API
        if not studies and self.query_handler and self.api_integration_utils:
            logger.info("🌐 No local studies found, querying API...")
            try:
                api_data = self.query_handler.query_all_metadata()
                if api_data:
                    studies = self.api_integration_utils.extract_studies_from_api_data(
                        api_data, self.anonymization_utils
                    )
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