#!/usr/bin/env python
"""
C-FIND Handler for DICOM operations

Coordinates C-FIND queries across different levels (PATIENT, STUDY, SERIES, IMAGE)
"""

import logging
from dicom_receiver.core.query_handlers.patient_query import PatientQueryHandler
from dicom_receiver.core.query_handlers.study_query import StudyQueryHandler
from dicom_receiver.core.query_handlers.series_query import SeriesQueryHandler
from dicom_receiver.core.query_handlers.image_query import ImageQueryHandler

logger = logging.getLogger('dicom_receiver.handlers.find')

class FindHandler:
    """Handler for C-FIND operations"""
    
    def __init__(self, storage, query_handler, anonymization_utils, api_integration_utils):
        """
        Initialize the find handler
        
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
        
        # Initialize query handlers
        self.patient_handler = PatientQueryHandler(
            storage, query_handler, anonymization_utils, api_integration_utils
        )
        self.study_handler = StudyQueryHandler(
            storage, query_handler, anonymization_utils, api_integration_utils
        )
        self.series_handler = SeriesQueryHandler(
            storage, query_handler, anonymization_utils, api_integration_utils
        )
        self.image_handler = ImageQueryHandler(
            storage, query_handler, anonymization_utils, api_integration_utils
        )
    
    def handle_find(self, event):
        """Handle a C-FIND request"""
        logger.info("=" * 60)
        logger.info("🔍 RECEIVED C-FIND REQUEST")
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
                else:
                    logger.info(f"   {tag.keyword}: <empty> (requesting this field)")
        
        try:
            if query_level == 'PATIENT':
                yield from self.patient_handler.find_patients(query_ds)
            elif query_level == 'STUDY':
                yield from self.study_handler.find_studies(query_ds)
            elif query_level == 'SERIES':
                yield from self.series_handler.find_series(query_ds)
            elif query_level == 'IMAGE':
                yield from self.image_handler.find_images(query_ds)
            else:
                logger.warning(f"❌ Unsupported query level: {query_level}")
                yield 0xC000, None  # Unable to process
                
        except Exception as e:
            logger.error(f"❌ Error processing C-FIND request: {e}")
            yield 0xC000, None  # Unable to process 