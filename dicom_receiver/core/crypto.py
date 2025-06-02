#!/usr/bin/env python
"""
Anonymization utilities for DICOM patient information

This module handles anonymization operations for protecting patient data
"""

from dicom_receiver.utils import json_utils as json
import logging
from pathlib import Path
from typing import Dict, Optional
import threading

from pydicom import Dataset

from dicom_receiver.config import PII_TAGS, PATIENT_INFO_MAP_FILENAME

logger = logging.getLogger('dicom_receiver.crypto')

class DicomAnonymizer:
    """Handles anonymization and restoration of DICOM patient information"""
    
    def __init__(self, storage_dir: Path, map_file: Optional[str] = None):
        """
        Initialize the anonymizer
        
        Parameters:
        -----------
        storage_dir : Path
            Base directory for storing the patient info map
        map_file : str, optional
            Custom path for the patient info map file
        """
        self.storage_dir = storage_dir
        
        if map_file:
            self.patient_info_map_file = Path(map_file)
        else:
            self.patient_info_map_file = self.storage_dir / PATIENT_INFO_MAP_FILENAME
        
        self.patient_name_map = {}  # Maps original patient names to anonymized names
        self.patient_info_map = self._load_patient_info_map()
        self.patient_counter = self._get_next_patient_counter()
        
        self.patient_map_lock = threading.Lock()
    
    def _load_patient_info_map(self) -> Dict:
        """Load the patient information mapping from disk"""
        if self.patient_info_map_file.exists():
            try:
                with open(self.patient_info_map_file, 'r') as f:
                    data = json.load(f)
                    
                    if isinstance(data, dict) and 'patient_info' in data:
                        # Load patient name mapping if it exists
                        if 'patient_name_map' in data:
                            self.patient_name_map = data['patient_name_map']
                        
                        return data['patient_info']
                    else:
                        # Old format - migrate to new format
                        return data
            except json.JSONDecodeError:
                logger.error(f"Error loading patient info map, creating new one")
                return {}
        return {}
    
    def _get_next_patient_counter(self) -> int:
        """Get the next patient counter based on existing anonymized names"""
        max_counter = 0
        for anon_name in self.patient_name_map.values():
            if anon_name.startswith('sub-'):
                try:
                    counter = int(anon_name.split('-')[1])
                    max_counter = max(max_counter, counter)
                except (IndexError, ValueError):
                    continue
        return max_counter + 1
    
    def _get_anonymized_patient_name(self, original_name: str) -> str:
        """Get or create an anonymized patient name"""
        if original_name in self.patient_name_map:
            return self.patient_name_map[original_name]
        
        # Create new anonymized name
        anon_name = f"sub-{self.patient_counter:03d}"
        self.patient_name_map[original_name] = anon_name
        self.patient_counter += 1
        
        logger.info(f"Created new anonymized patient name: {original_name} -> {anon_name}")
        return anon_name
    
    def _save_patient_info_map(self):
        """Save the patient information mapping to disk"""
        with self.patient_map_lock:
            # Create the directory if it doesn't exist
            self.patient_info_map_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.patient_info_map_file, 'w') as f:
                combined_map = {
                    'patient_info': self.patient_info_map,
                    'patient_name_map': self.patient_name_map,
                    'patient_study_map': {}
                }
                
                # Build patient study map
                for study_uid, tags in self.patient_info_map.items():
                    if 'PatientID' in tags:
                        patient_id = tags['PatientID']
                        if patient_id not in combined_map['patient_study_map']:
                            combined_map['patient_study_map'][patient_id] = []
                        if study_uid not in combined_map['patient_study_map'][patient_id]:
                            combined_map['patient_study_map'][patient_id].append(study_uid)
                
                json.dump(combined_map, f, indent=2)
    
    def anonymize_dataset(self, dataset: Dataset) -> Dict:
        """
        Anonymize patient identifiable information in a DICOM dataset
        
        Parameters:
        -----------
        dataset : Dataset
            The DICOM dataset to anonymize
            
        Returns:
        --------
        Dict: Dictionary containing the original values that were anonymized
        """
        original_info = {}
        
        # Get study UID for mapping
        study_uid = dataset.StudyInstanceUID
        
        # Initialize map if needed
        if study_uid not in self.patient_info_map:
            self.patient_info_map[study_uid] = {}
        
        # Process PII fields that exist in the dataset
        for tag in PII_TAGS:
            if hasattr(dataset, tag) and getattr(dataset, tag):
                value = str(getattr(dataset, tag))
                
                # Store original value for later retrieval
                if tag not in self.patient_info_map[study_uid]:
                    self.patient_info_map[study_uid][tag] = value
                
                # Save the original value
                original_info[tag] = value
                
                # Apply anonymization based on field type
                if tag == 'PatientName':
                    # Use sequential naming for patient names
                    anonymized_value = self._get_anonymized_patient_name(value)
                elif tag == 'PatientID':
                    # Keep the original PatientID - don't anonymize it
                    # This ensures proper patient identification when sending to nodes
                    anonymized_value = value
                else:
                    # For all other PII fields, use "ANON"
                    anonymized_value = "ANON"
                
                # Replace with the anonymized value
                setattr(dataset, tag, anonymized_value)
        
        # Save updated map to disk
        self._save_patient_info_map()
        
        return original_info
    
    def get_anonymized_patient_name(self, study_uid: str) -> Optional[str]:
        """
        Get the anonymized patient name for a study
        
        Parameters:
        -----------
        study_uid : str
            Study UID
            
        Returns:
        --------
        str: Anonymized patient name (e.g., "sub-001") or None if not found
        """
        if study_uid in self.patient_info_map:
            original_name = self.patient_info_map[study_uid].get('PatientName')
            if original_name and original_name in self.patient_name_map:
                return self.patient_name_map[original_name]
        return None
    
    def restore_dataset(self, dataset: Dataset) -> bool:
        """
        Restore original patient information to a dataset
        
        Parameters:
        -----------
        dataset : Dataset
            The DICOM dataset with anonymized values
            
        Returns:
        --------
        bool: True if successful, False otherwise
        """
        study_uid = dataset.StudyInstanceUID
        
        # Check if we have information for this study
        if study_uid not in self.patient_info_map:
            logger.warning(f"No patient information found for study {study_uid}")
            return False
        
        # Restore the original patient info
        for tag, value in self.patient_info_map[study_uid].items():
            if hasattr(dataset, tag):
                setattr(dataset, tag, value)
        
        return True

    # Backward compatibility methods
    def encrypt_dataset(self, dataset: Dataset) -> Dict:
        """Backward compatibility method - calls anonymize_dataset"""
        return self.anonymize_dataset(dataset)
    
    def decrypt_dataset(self, dataset: Dataset) -> bool:
        """Backward compatibility method - calls restore_dataset"""
        return self.restore_dataset(dataset)


# Backward compatibility alias
DicomEncryptor = DicomAnonymizer


def restore_file(anonymized_file: str, original_file: str, map_file: Optional[str] = None):
    """
    Restore original patient information to a DICOM file
    
    Parameters:
    -----------
    anonymized_file : str
        Path to the anonymized DICOM file
    original_file : str
        Path to save the restored DICOM file
    map_file : str, optional
        Path to the patient info map file
    
    Returns:
    --------
    bool: True if successful, False otherwise
    """
    from pydicom import dcmread
    
    if map_file is None:
        file_path = Path(anonymized_file)
        if len(file_path.parts) >= 3:
            storage_dir = file_path.parent.parent.parent
            map_file = storage_dir / PATIENT_INFO_MAP_FILENAME
        else:
            raise ValueError("Cannot infer patient info map location, please specify map_file")
    else:
        map_file = Path(map_file)
    
    with open(map_file, 'r') as f:
        data = json.load(f)
        
        # Check if it's the new format
        if isinstance(data, dict) and 'patient_info' in data:
            patient_map = data['patient_info']
        else:
            # Old format
            patient_map = data
    
    dataset = dcmread(anonymized_file)
    
    study_uid = dataset.StudyInstanceUID
    
    if study_uid in patient_map:
        for tag, value in patient_map[study_uid].items():
            if hasattr(dataset, tag):
                setattr(dataset, tag, value)
        
        dataset.save_as(original_file)
        logger.info(f"Restored original patient information to {original_file}")
        return True
    else:
        logger.warning(f"No patient information found for study {study_uid}")
        return False 