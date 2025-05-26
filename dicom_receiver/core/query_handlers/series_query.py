#!/usr/bin/env python
"""
Series Query Handler for DICOM C-FIND operations

Handles series-level queries with local storage and API fallback
"""

import logging
from pydicom import Dataset

logger = logging.getLogger('dicom_receiver.query.series')

class SeriesQueryHandler:
    """Handler for series-level C-FIND queries"""
    
    def __init__(self, storage, query_handler, anonymization_utils, api_integration_utils):
        """
        Initialize the series query handler
        
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
    
    def find_series(self, query_ds):
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
        if not series_list and self.query_handler and self.api_integration_utils:
            logger.info("🌐 No local series found, querying API...")
            try:
                api_data = self.query_handler.query_all_metadata()
                if api_data:
                    series_list = self.api_integration_utils.extract_series_from_api_data(
                        api_data, study_uid, self.anonymization_utils
                    )
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