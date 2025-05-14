#!/usr/bin/env python
"""
Storage module for DICOM files

Handles file storage, study tracking, and timeout monitoring
"""

import logging
import threading
import time
from pathlib import Path
from typing import Dict, Set

logger = logging.getLogger('dicom_receiver.storage')

class StudyMonitor:
    """
    Monitors study activity and detects when studies are complete
    based on a timeout since the last received file
    """
    
    def __init__(self, timeout: int):
        """
        Initialize the study monitor
        
        Parameters:
        -----------
        timeout : int
            Timeout in seconds after receiving the last file in a study
        """
        self.timeout = timeout
        self.study_last_activity = {}
        self.study_monitor_lock = threading.Lock()
        self.active_studies = set()
        self.study_complete_callbacks = []
        
        self.monitor_thread = threading.Thread(target=self._monitor_studies_timeout, daemon=True)
        self.monitor_thread.start()
    
    def register_study_complete_callback(self, callback):
        """Register a callback to be called when a study is complete"""
        self.study_complete_callbacks.append(callback)
    
    def update_study_activity(self, study_uid: str):
        """Update the last activity timestamp for a study"""
        now = time.time()
        with self.study_monitor_lock:
            self.study_last_activity[study_uid] = now
            self.active_studies.add(study_uid)
    
    def _monitor_studies_timeout(self):
        """Monitor studies for timeout since last activity"""
        while True:
            current_time = time.time()
            studies_to_finalize = []
            
            with self.study_monitor_lock:
                for study_uid, last_activity in list(self.study_last_activity.items()):
                    if current_time - last_activity > self.timeout:
                        studies_to_finalize.append(study_uid)
                        self.study_last_activity.pop(study_uid)
            
            for study_uid in studies_to_finalize:
                self._finalize_study(study_uid)
            
            time.sleep(1)
    
    def _finalize_study(self, study_uid: str):
        """Finalize a study after timeout"""
        logger.info(f"Finalizing study {study_uid} after timeout")
        
        with self.study_monitor_lock:
            if study_uid in self.active_studies:
                self.active_studies.remove(study_uid)
                logger.info(f"Study {study_uid} completed")
                
                for callback in self.study_complete_callbacks:
                    try:
                        callback(study_uid)
                    except Exception as e:
                        logger.error(f"Error in study complete callback: {e}")


class DicomStorage:
    """
    Handles storage of DICOM files in an organized directory structure
    """
    
    def __init__(self, storage_dir: str):
        """
        Initialize the DICOM storage
        
        Parameters:
        -----------
        storage_dir : str
            Base directory for storing DICOM files
        """
        self.storage_dir = Path(storage_dir)
        
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def get_file_path(self, study_uid: str, series_uid: str, instance_uid: str) -> Path:
        """
        Get the path where a DICOM file should be stored
        
        Parameters:
        -----------
        study_uid : str
            StudyInstanceUID of the DICOM dataset
        series_uid : str
            SeriesInstanceUID of the DICOM dataset
        instance_uid : str
            SOPInstanceUID of the DICOM dataset
            
        Returns:
        --------
        Path: The path where the file should be stored
        """
        study_dir = self.storage_dir / study_uid
        series_dir = study_dir / series_uid
        series_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{instance_uid}.dcm"
        return series_dir / filename
    
    def get_study_path(self, study_uid: str) -> Path:
        """Get the path to a study directory"""
        return self.storage_dir / study_uid
    
    def get_series_path(self, study_uid: str, series_uid: str) -> Path:
        """Get the path to a series directory"""
        return self.storage_dir / study_uid / series_uid 