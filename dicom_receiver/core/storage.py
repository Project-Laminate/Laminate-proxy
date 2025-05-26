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
import shutil

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
    using a patient/study/series/scans hierarchy
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
        # Maps to track patient ID to study UIDs
        self.patient_study_map = {}
    
    def get_file_path(self, study_uid: str, series_uid: str, instance_uid: str, dataset=None) -> Path:
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
        dataset : Dataset, optional
            The DICOM dataset (if provided, used to get PatientID)
            
        Returns:
        --------
        Path: The path where the file should be stored
        """
        # Determine patient ID (defaults to "unknown" if not available)
        patient_id = "unknown"
        
        if dataset and hasattr(dataset, 'PatientID'):
            patient_id = str(dataset.PatientID)
            # Sanitize patient ID for safe directory names
            patient_id = "".join(c for c in patient_id if c.isalnum() or c in "._- ").strip()
            if not patient_id:
                patient_id = "unknown"
            
            # Update mapping between patient and study
            if patient_id not in self.patient_study_map:
                self.patient_study_map[patient_id] = set()
            self.patient_study_map[patient_id].add(study_uid)
        
        # Create directory structure: patient/study/series/scans
        patient_dir = self.storage_dir / patient_id
        study_dir = patient_dir / study_uid
        series_dir = study_dir / series_uid
        scans_dir = series_dir / "scans"
        scans_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{instance_uid}.dcm"
        return scans_dir / filename
    
    def get_patient_path(self, patient_id: str) -> Path:
        """Get the path to a patient directory"""
        return self.storage_dir / patient_id
    
    def get_study_path(self, patient_id: str, study_uid: str) -> Path:
        """Get the path to a study directory"""
        return self.storage_dir / patient_id / study_uid
    
    def get_series_path(self, patient_id: str, study_uid: str, series_uid: str) -> Path:
        """Get the path to a series directory"""
        return self.storage_dir / patient_id / study_uid / series_uid
    
    def get_scans_path(self, patient_id: str, study_uid: str, series_uid: str) -> Path:
        """Get the path to the scans directory within a series"""
        return self.storage_dir / patient_id / study_uid / series_uid / "scans"
    
    # Backward compatibility methods
    def get_study_path_by_uid(self, study_uid: str) -> Path:
        """Get the study path for backward compatibility"""
        # Try to find the study by checking all patient directories
        for patient_dir in self.storage_dir.iterdir():
            if patient_dir.is_dir():
                study_dir = patient_dir / study_uid
                if study_dir.exists():
                    return study_dir
        
        # Fallback to old path structure if not found
        return self.storage_dir / study_uid
    
    def migrate_to_patient_structure(self, patient_study_map=None):
        """
        Migrate existing files from study/series/instance.dcm to patient/study/series/scans/instance.dcm
        
        Parameters:
        -----------
        patient_study_map : dict, optional
            Map of PatientID to list of StudyInstanceUIDs for mapping studies to patients
        """
        # Get all top-level directories that might be studies
        for dir_path in self.storage_dir.iterdir():
            if not dir_path.is_dir():
                continue
                
            study_uid = dir_path.name
            
            # Skip directories that are already patient IDs
            if patient_study_map and study_uid not in sum(patient_study_map.values(), []):
                continue
                
            # Determine patient ID for this study
            patient_id = "unknown"
            if patient_study_map:
                for pid, studies in patient_study_map.items():
                    if study_uid in studies:
                        patient_id = pid
                        break
            
            logger.info(f"Migrating study {study_uid} to patient {patient_id}")
            
            # Create the new directory structure
            new_study_dir = self.storage_dir / patient_id / study_uid
            new_study_dir.mkdir(parents=True, exist_ok=True)
            
            # Move all series directories to the new location
            for series_dir in dir_path.iterdir():
                if not series_dir.is_dir():
                    continue
                    
                series_uid = series_dir.name
                new_series_dir = new_study_dir / series_uid
                new_scans_dir = new_series_dir / "scans"
                new_scans_dir.mkdir(parents=True, exist_ok=True)
                
                # Move all DICOM files to the scans directory
                for file_path in series_dir.glob("*.dcm"):
                    new_file_path = new_scans_dir / file_path.name
                    shutil.move(str(file_path), str(new_file_path))
                    
            # After moving all files, remove the old directory if it's empty
            if not any(dir_path.iterdir()):
                shutil.rmtree(str(dir_path))
                
        logger.info("Migration to patient/study/series/scans structure complete")
    
    def get_all_patients(self):
        """
        Get information about all patients in storage
        
        Returns:
        --------
        List[Dict]: List of patient information dictionaries
        """
        patients = []
        
        for patient_dir in self.storage_dir.iterdir():
            if not patient_dir.is_dir():
                continue
                
            patient_id = patient_dir.name
            
            # Get patient info from the first DICOM file we can find
            patient_info = {'PatientID': patient_id}
            
            # Look for any DICOM file to extract patient information
            for study_dir in patient_dir.iterdir():
                if not study_dir.is_dir():
                    continue
                    
                for series_dir in study_dir.iterdir():
                    if not series_dir.is_dir():
                        continue
                        
                    scans_dir = series_dir / "scans"
                    if scans_dir.exists():
                        for dcm_file in scans_dir.glob("*.dcm"):
                            try:
                                from pydicom import dcmread
                                ds = dcmread(dcm_file)
                                
                                if hasattr(ds, 'PatientName'):
                                    patient_info['PatientName'] = str(ds.PatientName)
                                if hasattr(ds, 'PatientBirthDate'):
                                    patient_info['PatientBirthDate'] = str(ds.PatientBirthDate)
                                if hasattr(ds, 'PatientSex'):
                                    patient_info['PatientSex'] = str(ds.PatientSex)
                                
                                patients.append(patient_info)
                                return patients  # Found one patient, return
                            except Exception as e:
                                logger.warning(f"Error reading DICOM file {dcm_file}: {e}")
                                continue
        
        return patients
    
    def get_all_studies(self):
        """
        Get information about all studies in storage
        
        Returns:
        --------
        List[Dict]: List of study information dictionaries
        """
        studies = []
        
        for patient_dir in self.storage_dir.iterdir():
            if not patient_dir.is_dir():
                continue
                
            patient_id = patient_dir.name
            
            for study_dir in patient_dir.iterdir():
                if not study_dir.is_dir():
                    continue
                    
                study_uid = study_dir.name
                study_info = {
                    'PatientID': patient_id,
                    'StudyInstanceUID': study_uid
                }
                
                # Count series and instances
                series_count = 0
                instance_count = 0
                
                # Get study info from the first DICOM file we can find
                for series_dir in study_dir.iterdir():
                    if not series_dir.is_dir():
                        continue
                        
                    series_count += 1
                    scans_dir = series_dir / "scans"
                    if scans_dir.exists():
                        dcm_files = list(scans_dir.glob("*.dcm"))
                        instance_count += len(dcm_files)
                        
                        # Extract study information from first DICOM file
                        if dcm_files and 'StudyDescription' not in study_info:
                            try:
                                from pydicom import dcmread
                                ds = dcmread(dcm_files[0])
                                
                                if hasattr(ds, 'PatientName'):
                                    study_info['PatientName'] = str(ds.PatientName)
                                if hasattr(ds, 'PatientBirthDate'):
                                    study_info['PatientBirthDate'] = str(ds.PatientBirthDate)
                                if hasattr(ds, 'PatientSex'):
                                    study_info['PatientSex'] = str(ds.PatientSex)
                                if hasattr(ds, 'StudyDescription'):
                                    study_info['StudyDescription'] = str(ds.StudyDescription)
                                if hasattr(ds, 'StudyDate'):
                                    study_info['StudyDate'] = str(ds.StudyDate)
                                if hasattr(ds, 'StudyTime'):
                                    study_info['StudyTime'] = str(ds.StudyTime)
                                if hasattr(ds, 'StudyID'):
                                    study_info['StudyID'] = str(ds.StudyID)
                                if hasattr(ds, 'AccessionNumber'):
                                    study_info['AccessionNumber'] = str(ds.AccessionNumber)
                                    
                            except Exception as e:
                                logger.warning(f"Error reading DICOM file {dcm_files[0]}: {e}")
                
                study_info['NumberOfStudyRelatedSeries'] = series_count
                study_info['NumberOfStudyRelatedInstances'] = instance_count
                studies.append(study_info)
        
        return studies
    
    def get_series_for_study(self, study_uid: str):
        """
        Get information about all series for a specific study
        
        Parameters:
        -----------
        study_uid : str
            StudyInstanceUID
            
        Returns:
        --------
        List[Dict]: List of series information dictionaries
        """
        series_list = []
        
        # Find the study directory
        study_dir = self.get_study_path_by_uid(study_uid)
        if not study_dir.exists():
            return series_list
        
        for series_dir in study_dir.iterdir():
            if not series_dir.is_dir():
                continue
                
            series_uid = series_dir.name
            series_info = {
                'StudyInstanceUID': study_uid,
                'SeriesInstanceUID': series_uid
            }
            
            scans_dir = series_dir / "scans"
            if scans_dir.exists():
                dcm_files = list(scans_dir.glob("*.dcm"))
                series_info['NumberOfSeriesRelatedInstances'] = len(dcm_files)
                
                # Extract series information from first DICOM file
                if dcm_files:
                    try:
                        from pydicom import dcmread
                        ds = dcmread(dcm_files[0])
                        
                        if hasattr(ds, 'PatientName'):
                            series_info['PatientName'] = str(ds.PatientName)
                        if hasattr(ds, 'PatientID'):
                            series_info['PatientID'] = str(ds.PatientID)
                        if hasattr(ds, 'SeriesDescription'):
                            series_info['SeriesDescription'] = str(ds.SeriesDescription)
                        if hasattr(ds, 'SeriesNumber'):
                            series_info['SeriesNumber'] = str(ds.SeriesNumber)
                        if hasattr(ds, 'Modality'):
                            series_info['Modality'] = str(ds.Modality)
                        if hasattr(ds, 'SeriesDate'):
                            series_info['SeriesDate'] = str(ds.SeriesDate)
                        if hasattr(ds, 'SeriesTime'):
                            series_info['SeriesTime'] = str(ds.SeriesTime)
                            
                    except Exception as e:
                        logger.warning(f"Error reading DICOM file {dcm_files[0]}: {e}")
            
            series_list.append(series_info)
        
        return series_list
    
    def get_images_for_series(self, study_uid: str, series_uid: str):
        """
        Get information about all images for a specific series
        
        Parameters:
        -----------
        study_uid : str
            StudyInstanceUID
        series_uid : str
            SeriesInstanceUID
            
        Returns:
        --------
        List[Dict]: List of image information dictionaries
        """
        images = []
        
        # Find the series directory
        study_dir = self.get_study_path_by_uid(study_uid)
        if not study_dir.exists():
            return images
        
        series_dir = study_dir / series_uid
        if not series_dir.exists():
            return images
        
        scans_dir = series_dir / "scans"
        if not scans_dir.exists():
            return images
        
        for dcm_file in scans_dir.glob("*.dcm"):
            try:
                from pydicom import dcmread
                ds = dcmread(dcm_file)
                
                image_info = {
                    'StudyInstanceUID': study_uid,
                    'SeriesInstanceUID': series_uid,
                    'SOPInstanceUID': str(ds.SOPInstanceUID),
                    'SOPClassUID': str(ds.SOPClassUID)
                }
                
                if hasattr(ds, 'PatientName'):
                    image_info['PatientName'] = str(ds.PatientName)
                if hasattr(ds, 'PatientID'):
                    image_info['PatientID'] = str(ds.PatientID)
                if hasattr(ds, 'InstanceNumber'):
                    image_info['InstanceNumber'] = str(ds.InstanceNumber)
                
                images.append(image_info)
                
            except Exception as e:
                logger.warning(f"Error reading DICOM file {dcm_file}: {e}")
                continue
        
        return images
    
    def get_images_for_study(self, study_uid: str):
        """
        Get file paths for all images in a specific study
        
        Parameters:
        -----------
        study_uid : str
            StudyInstanceUID
            
        Returns:
        --------
        List[str]: List of file paths to DICOM files in the study
        """
        image_files = []
        
        # Find the study directory
        study_dir = self.get_study_path_by_uid(study_uid)
        if not study_dir.exists():
            return image_files
        
        # Iterate through all series in the study
        for series_dir in study_dir.iterdir():
            if not series_dir.is_dir():
                continue
            
            scans_dir = series_dir / "scans"
            if scans_dir.exists():
                # Add all DICOM files in this series
                for dcm_file in scans_dir.glob("*.dcm"):
                    image_files.append(str(dcm_file))
        
        return image_files