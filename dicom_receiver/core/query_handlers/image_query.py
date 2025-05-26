#!/usr/bin/env python
"""
Image Query Handler for DICOM C-FIND operations

Handles image-level queries with local storage and API fallback
"""

import logging
from pydicom import Dataset

logger = logging.getLogger('dicom_receiver.query.image')

class ImageQueryHandler:
    """Handler for image-level C-FIND queries"""
    
    def __init__(self, storage, query_handler, anonymization_utils, api_integration_utils):
        """
        Initialize the image query handler
        
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
    
    def find_images(self, query_ds):
        """Find images matching the query"""
        logger.info("🖼️ Processing IMAGE level C-FIND")
        
        study_uid = getattr(query_ds, 'StudyInstanceUID', None)
        series_uid = getattr(query_ds, 'SeriesInstanceUID', None)
        
        if not study_uid:
            logger.warning("❌ StudyInstanceUID required for IMAGE level query")
            # Return success with no results instead of failure
            logger.info("✅ IMAGE query completed - no StudyInstanceUID provided, returning 0 images")
            logger.info("=" * 60)
            yield 0x0000, None
            return
        
        if not series_uid:
            logger.info("ℹ️ No SeriesInstanceUID provided, will search all series in study")
            # Continue with the query but search all series in the study
        
        logger.info(f"🔍 Looking for images in study: {study_uid}")
        if series_uid:
            logger.info(f"🔍 Series: {series_uid}")
            # Get images for the specified series
            images = self.storage.get_images_for_series(study_uid, series_uid)
        else:
            logger.info(f"🔍 Series: All series in study")
            # Get all images in the study (across all series)
            images = self.storage.get_images_for_study(study_uid)
        
        logger.info(f"📊 Found {len(images)} images in local storage")
        
        # If no local images and we have API access, query the API
        if not images and self.query_handler and self.api_integration_utils:
            logger.info("🌐 No local images found, querying API...")
            try:
                api_data = self.query_handler.query_all_metadata()
                if api_data:
                    if series_uid:
                        # Query specific series
                        images = self.api_integration_utils.extract_images_from_api_data(
                            api_data, study_uid, series_uid, self.anonymization_utils
                        )
                    else:
                        # Query all series in study - we'll need to implement this
                        # For now, return empty list to avoid errors
                        images = []
                        logger.info("🌐 API query for all series in study not yet implemented")
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