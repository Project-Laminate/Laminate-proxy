#!/usr/bin/env python
"""
DICOM SCP (Service Class Provider) implementation

Handles DICOM networking, associations, and storage operations
"""

import logging
import os
import signal
import threading
import time
from pathlib import Path

from pydicom import Dataset
from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian
from pynetdicom import AE, evt, StoragePresentationContexts, debug_logger
from pynetdicom.sop_class import Verification

from dicom_receiver.core.crypto import DicomEncryptor
from dicom_receiver.core.storage import DicomStorage, StudyMonitor
from dicom_receiver.core.uploader import ApiUploader

logger = logging.getLogger('dicom_receiver.scp')

class DicomServiceProvider:
    """
    DICOM Service Class Provider (SCP) that receives and processes DICOM files
    """
    
    def __init__(self, 
                 storage: DicomStorage,
                 study_monitor: StudyMonitor,
                 encryptor: DicomEncryptor,
                 port: int = 11112, 
                 ae_title: bytes = b'DICOMRCV',
                 api_url: str = None,
                 api_username: str = None,
                 api_password: str = None,
                 api_token: str = None,
                 auto_upload: bool = False,
                 zip_dir: str = 'zips',
                 cleanup_after_upload: bool = False,
                 max_retries: int = 3,
                 retry_delay: int = 5):
        """
        Initialize the DICOM SCP
        
        Parameters:
        -----------
        storage : DicomStorage
            Storage handler for DICOM files
        study_monitor : StudyMonitor
            Monitor for tracking study completion
        encryptor : DicomEncryptor
            Encryptor for patient information
        port : int
            Port to listen on
        ae_title : bytes
            AE title for this SCP
        api_url : str
            URL of the API for uploading studies
        api_username : str
            Username for API authentication
        api_password : str
            Password for API authentication
        api_token : str
            Existing token for API authentication
        auto_upload : bool
            Whether to automatically upload studies when complete
        zip_dir : str
            Directory to store zipped studies
        cleanup_after_upload : bool
            Whether to remove files after successful upload
        max_retries : int
            Maximum number of retry attempts for failed API operations
        retry_delay : int
            Delay between retry attempts in seconds
        """
        self.storage = storage
        self.study_monitor = study_monitor
        self.encryptor = encryptor
        self.port = port
        self.ae_title = ae_title
        self.api_url = api_url
        self.api_username = api_username
        self.api_password = api_password
        self.api_token = api_token
        self.auto_upload = auto_upload
        self.zip_dir = Path(zip_dir)
        self.cleanup_after_upload = cleanup_after_upload
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        self.is_running = False
        self.server_thread = None
        self.ae = None
        self.shutdown_event = threading.Event()
        
        if self.auto_upload:
            self.zip_dir.mkdir(parents=True, exist_ok=True)
            
            self.api_uploader = ApiUploader(
                api_url=api_url,
                username=api_username,
                password=api_password,
                token=api_token,
                cleanup_after_upload=cleanup_after_upload,
                max_retries=max_retries,
                retry_delay=retry_delay
            )
            
            self.study_monitor.register_study_complete_callback(self._study_complete_handler)
            
            logger.info(f"Auto-upload enabled. Studies will be uploaded to {api_url}")
            if self.cleanup_after_upload:
                logger.info("Cleanup after upload is enabled. Files will be removed after successful upload.")
            logger.info(f"Upload retry mechanism: max_retries={max_retries}, retry_delay={retry_delay}s")
        
    def _handle_store(self, event):
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
    
    def _study_complete_handler(self, study_uid):
        """
        Handle study completion - zip and upload study
        
        Parameters:
        -----------
        study_uid : str
            Study UID of the completed study
        """
        if not self.auto_upload:
            return
        
        logger.info(f"Processing completed study: {study_uid}")
        
        # Get the study directory using the backward compatibility method
        study_dir = self.storage.get_study_path_by_uid(study_uid)
        
        if not study_dir.exists():
            logger.error(f"Study directory not found: {study_dir}")
            return
        
        try:
            # Get the anonymized patient name for this study
            anonymized_name = self.encryptor.get_anonymized_patient_name(study_uid)
            if not anonymized_name:
                logger.warning(f"No anonymized patient name found for study {study_uid}, using study UID")
                anonymized_name = study_uid
            
            # Use anonymized patient name for zip file
            zip_path = self.zip_dir / f"{anonymized_name}.zip"
            
            zip_file = self.api_uploader.zip_study(study_dir, str(zip_path))
            
            if not zip_file:
                logger.error(f"Failed to create zip file for study: {study_uid}")
                return
            
            success, response_data = self.api_uploader.upload_study(
                zip_file,
                study_info={
                    'name': anonymized_name,
                },
                study_dir=str(study_dir) if self.cleanup_after_upload else None
            )
            
            if success:
                logger.info(f"Successfully uploaded study: {study_uid} as {anonymized_name}")
                if response_data and 'id' in response_data:
                    logger.info(f"Dataset ID: {response_data.get('id')}")
                if self.cleanup_after_upload:
                    logger.info(f"Cleaned up files for study: {study_uid}")
            else:
                logger.error(f"Failed to upload study: {study_uid}")
                
        except Exception as e:
            logger.error(f"Error processing completed study {study_uid}: {e}")
    
    def _server_process(self):
        """Run the DICOM server in a separate thread"""
        try:
            self.ae = AE(ae_title=self.ae_title)
            
            self.ae.supported_contexts = StoragePresentationContexts
            
            self.ae.add_supported_context(Verification)
            
            for context in self.ae.supported_contexts:
                context.transfer_syntax = [
                    ExplicitVRLittleEndian, 
                    ImplicitVRLittleEndian
                ]
            
            handlers = [(evt.EVT_C_STORE, self._handle_store)]
            
            self.ae.start_server(
                ("0.0.0.0", self.port), 
                block=False, 
                evt_handlers=handlers
            )
            
            logger.info(f"DICOM server running on port {self.port}")
            
            while not self.shutdown_event.is_set():
                time.sleep(0.1)
                
        except Exception as e:
            logger.error(f"Error in DICOM server process: {e}")
        finally:
            if self.ae:
                self.ae.shutdown()
                logger.info("DICOM server has been shut down")
    
    def start(self):
        """Start the DICOM receiver service in non-blocking mode"""
        if self.is_running:
            logger.warning("DICOM server is already running")
            return
            
        logger.info(f"Starting DICOM receiver on port {self.port}")
        logger.info(f"AE Title: {self.ae_title}")
        
        self.is_running = True
        self.shutdown_event.clear()
        
        self.server_thread = threading.Thread(target=self._server_process, daemon=True)
        self.server_thread.start()
        
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        try:
            while self.server_thread.is_alive():
                self.server_thread.join(1.0)
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received, stopping DICOM receiver")
            self.stop()
    
    def stop(self):
        """Stop the DICOM receiver service"""
        if not self.is_running:
            logger.warning("DICOM server is not running")
            return
            
        logger.info("Stopping DICOM receiver...")
        self.shutdown_event.set()
        
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(5.0)
            
        self.is_running = False
        logger.info("DICOM receiver stopped")
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals for graceful shutdown"""
        logger.info(f"Received signal {signum}, stopping DICOM receiver")
        self.stop() 