#!/usr/bin/env python
"""
DICOM SCP (Service Class Provider) implementation

Main coordinator for DICOM networking, associations, and operations
"""

import logging
import signal
import threading
import time
from pathlib import Path

from pydicom.uid import ExplicitVRLittleEndian, ImplicitVRLittleEndian
from pynetdicom import AE, evt, StoragePresentationContexts, _config
from pynetdicom.sop_class import (
    Verification,
    StudyRootQueryRetrieveInformationModelFind,
    PatientRootQueryRetrieveInformationModelFind,
    ModalityWorklistInformationFind,
    StudyRootQueryRetrieveInformationModelGet,
    PatientRootQueryRetrieveInformationModelGet,
    StudyRootQueryRetrieveInformationModelMove,
    PatientRootQueryRetrieveInformationModelMove,
)

from dicom_receiver.core.crypto import DicomEncryptor
from dicom_receiver.core.storage import DicomStorage, StudyMonitor
from dicom_receiver.core.uploader import ApiUploader
from dicom_receiver.core.query import DicomQueryHandler
from dicom_receiver.core.handlers import StoreHandler, FindHandler, GetHandler, MoveHandler
from dicom_receiver.core.utils import AnonymizationUtils, ApiIntegrationUtils

logger = logging.getLogger('dicom_receiver.scp')

class DicomServiceProvider:
    """
    DICOM Service Class Provider (SCP) that receives and processes DICOM files
    
    This is the main coordinator that orchestrates all DICOM operations through
    focused, modular handlers.
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
        # Core components
        self.storage = storage
        self.study_monitor = study_monitor
        self.encryptor = encryptor
        self.port = port
        self.ae_title = ae_title
        self.api_url = api_url
        
        # Server state
        self.is_running = False
        self.server_thread = None
        self.ae = None
        self.shutdown_event = threading.Event()
        
        # Initialize utilities
        self.anonymization_utils = AnonymizationUtils(encryptor)
        
        # Initialize query handler for API queries
        if api_url:
            self.query_handler = DicomQueryHandler(
                api_url=api_url,
                storage_dir=str(storage.storage_dir),
                username=api_username,
                password=api_password,
                token=api_token
            )
            self.api_integration_utils = ApiIntegrationUtils(self.query_handler, api_url)
            logger.info(f"Query handler initialized for API: {api_url}")
        else:
            self.query_handler = None
            self.api_integration_utils = None
            logger.info("No API URL provided - queries will only use local storage")
        
        # Initialize AE configuration for C-MOVE operations
        from dicom_receiver.core.config import AEConfiguration
        self.ae_config = AEConfiguration()
        
        # Initialize handlers
        self.store_handler = StoreHandler(storage, study_monitor, encryptor)
        self.find_handler = FindHandler(
            storage, self.query_handler, self.anonymization_utils, self.api_integration_utils
        )
        self.get_handler = GetHandler(
            storage, self.query_handler, self.anonymization_utils, self.api_integration_utils
        )
        self.move_handler = MoveHandler(
            storage, self.query_handler, self.anonymization_utils, self.api_integration_utils, self.ae_config
        )
        
        # Initialize node manager for automatic forwarding
        if self.query_handler and self.api_integration_utils:
            from dicom_receiver.core.node_manager import NodeManager
            self.node_manager = NodeManager(
                str(storage.storage_dir), 
                self.query_handler, 
                self.api_integration_utils
            )
            logger.info("NodeManager initialized for automatic forwarding")
        else:
            self.node_manager = None
            logger.info("NodeManager disabled - no API access configured")
        
        # Initialize auto-upload if enabled
        if auto_upload:
            self._setup_auto_upload(
                api_url, api_username, api_password, api_token,
                zip_dir, cleanup_after_upload, max_retries, retry_delay
            )
    
    def _setup_auto_upload(self, api_url, api_username, api_password, api_token,
                          zip_dir, cleanup_after_upload, max_retries, retry_delay):
        """Setup auto-upload functionality"""
        self.zip_dir = Path(zip_dir)
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
        if cleanup_after_upload:
            logger.info("Cleanup after upload is enabled. Files will be removed after successful upload.")
        logger.info(f"Upload retry mechanism: max_retries={max_retries}, retry_delay={retry_delay}s")
    
    def _study_complete_handler(self, study_uid):
        """
        Handle study completion - zip and upload study
        
        Parameters:
        -----------
        study_uid : str
            Study UID of the completed study
        """
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
                study_dir=str(study_dir) if hasattr(self, 'api_uploader') and self.api_uploader.cleanup_after_upload else None
            )
            
            if success:
                logger.info(f"Successfully uploaded study: {study_uid} as {anonymized_name}")
                if response_data and 'id' in response_data:
                    logger.info(f"Dataset ID: {response_data.get('id')}")
                if hasattr(self, 'api_uploader') and self.api_uploader.cleanup_after_upload:
                    logger.info(f"Cleaned up files for study: {study_uid}")
            else:
                logger.error(f"Failed to upload study: {study_uid}")
                
        except Exception as e:
            logger.error(f"Error processing completed study {study_uid}: {e}")
    
    def _server_process(self):
        """Run the DICOM server in a separate thread"""
        try:
            # Configure pynetdicom to handle both ASCII and UTF-8 encodings
            # This fixes issues with OsiriX/Horos and other DICOM viewers that may send UTF-8 encoded strings
            # _config.CODECS = ("ascii", "utf-8")
            
            self.ae = AE(ae_title=self.ae_title)
            
            # Add storage presentation contexts with both SCP and SCU roles
            # This is crucial for C-GET and C-MOVE operations to work properly
            for context in StoragePresentationContexts:
                self.ae.add_supported_context(
                    context.abstract_syntax,
                    scu_role=True,  # Enable SCU role for sending files back to client during C-GET/C-MOVE
                    scp_role=True,  # Enable SCP role for receiving files during C-STORE
                    transfer_syntax=[ImplicitVRLittleEndian, ExplicitVRLittleEndian]
                )
                
            # WORKAROUND: Add storage contexts again without explicit role selection
            # This handles DICOM viewers like Horos that don't properly negotiate SCP role during C-GET
            # The default behavior (no role selection) allows both SCU and SCP roles
            for context in StoragePresentationContexts:
                self.ae.add_supported_context(
                    context.abstract_syntax,
                    transfer_syntax=[ImplicitVRLittleEndian]  # Use only Implicit VR for maximum compatibility
                )
                
            # Add storage contexts as SCU for C-MOVE operations
            # When pynetdicom handles C-MOVE, it creates a new association to send files
            # This association needs SCU contexts configured
            for context in StoragePresentationContexts:
                self.ae.add_requested_context(
                    context.abstract_syntax,
                    transfer_syntax=[ImplicitVRLittleEndian, ExplicitVRLittleEndian]
                )
            
            # Add query/retrieve presentation contexts for C-FIND
            self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelFind)
            self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelFind)
            self.ae.add_supported_context(ModalityWorklistInformationFind)
            
            # Add query/retrieve presentation contexts for C-GET
            self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelGet)
            self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelGet)
            
            # Add query/retrieve presentation contexts for C-MOVE
            self.ae.add_supported_context(StudyRootQueryRetrieveInformationModelMove)
            self.ae.add_supported_context(PatientRootQueryRetrieveInformationModelMove)
            
            # Add verification context
            self.ae.add_supported_context(Verification)
            
            # Configure transfer syntaxes for query/retrieve contexts only
            # Storage contexts already have transfer syntax configured above
            for context in self.ae.supported_contexts:
                # Only configure transfer syntax for contexts that don't have it set
                if not hasattr(context, 'transfer_syntax') or not context.transfer_syntax:
                    context.transfer_syntax = [
                        ImplicitVRLittleEndian,
                        ExplicitVRLittleEndian
                    ]
            
            # Setup event handlers using the modular handlers
            handlers = [
                (evt.EVT_C_STORE, self.store_handler.handle_store),
                (evt.EVT_C_FIND, self.find_handler.handle_find),
                (evt.EVT_C_GET, self.get_handler.handle_get),
                (evt.EVT_C_MOVE, self.move_handler.handle_move)
            ]
            
            self.ae.start_server(
                ("0.0.0.0", self.port), 
                block=False, 
                evt_handlers=handlers
            )
            
            logger.info(f"DICOM server running on port {self.port}")
            logger.info("C-FIND queries supported for browsing studies")
            logger.info("C-GET downloads enabled with Horos compatibility workaround")
            logger.info("C-MOVE downloads enabled for maximum DICOM viewer compatibility")
            logger.info("Storage contexts configured with dual role support for maximum compatibility")
            logger.info("Note: C-MOVE requires destination AE configuration for proper operation")
            
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
        
        # Start automatic forwarding if node manager is available
        if self.node_manager:
            self.node_manager.start_auto_forwarding()
        
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
        
        # Stop automatic forwarding if node manager is available
        if self.node_manager:
            self.node_manager.stop_auto_forwarding()
        
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(5.0)
            
        self.is_running = False
        logger.info("DICOM receiver stopped")
    
    def _signal_handler(self, signum, frame):
        """Handle termination signals for graceful shutdown"""
        logger.info(f"Received signal {signum}, stopping DICOM receiver")
        self.stop() 