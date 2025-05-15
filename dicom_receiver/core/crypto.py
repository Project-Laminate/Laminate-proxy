#!/usr/bin/env python
"""
Encryption/decryption utilities for DICOM patient information

This module handles cryptographic operations for protecting patient data
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional
import threading

from cryptography.fernet import Fernet
from pydicom import Dataset

from dicom_receiver.config import PII_TAGS, PATIENT_INFO_MAP_FILENAME

logger = logging.getLogger('dicom_receiver.crypto')

class DicomEncryptor:
    """Handles encryption and decryption of DICOM patient information"""
    
    def __init__(self, storage_dir: Path, key_file: str):
        """
        Initialize the encryptor
        
        Parameters:
        -----------
        storage_dir : Path
            Base directory for storing the patient info map
        key_file : str
            File to store/load the encryption key
        """
        self.storage_dir = storage_dir
        self.key_file = key_file
        self.encryption_key = self._load_or_create_key()
        self.fernet = Fernet(self.encryption_key)
        
        # Map to store original patient info for later retrieval
        self.patient_info_map_file = self.storage_dir / PATIENT_INFO_MAP_FILENAME
        self.patient_info_map = self._load_patient_info_map()
        
        # Store encrypted values to ensure consistency
        self.encrypted_values_map = {}
        self._extract_encrypted_values()
        
        self.patient_map_lock = threading.Lock()
    
    def _extract_encrypted_values(self):
        """Extract encrypted values from the patient info map for consistency"""
        for study_uid, tags in self.patient_info_map.items():
            if study_uid not in self.encrypted_values_map:
                self.encrypted_values_map[study_uid] = {}
                
    def _load_or_create_key(self) -> bytes:
        """Load existing encryption key or create a new one"""
        key_path = Path(self.key_file)
        if key_path.exists():
            with open(key_path, 'rb') as key_file:
                return key_file.read()
        else:
            key = Fernet.generate_key()
            with open(key_path, 'wb') as key_file:
                key_file.write(key)
            logger.info(f"Created new encryption key at {key_path}")
            return key
    
    def _load_patient_info_map(self) -> Dict:
        """Load the patient information mapping from disk"""
        if self.patient_info_map_file.exists():
            try:
                with open(self.patient_info_map_file, 'r') as f:
                    data = json.load(f)
                    
                    # Check if it's the new format (dictionary with patient_info and encrypted_values)
                    if isinstance(data, dict) and 'patient_info' in data:
                        self.encrypted_values_map = data.get('encrypted_values', {})
                        return data['patient_info']
                    else:
                        # It's the old format (just patient info)
                        return data
            except json.JSONDecodeError:
                logger.error(f"Error loading patient info map, creating new one")
                return {}
        return {}
    
    def _save_patient_info_map(self):
        """Save the patient information mapping to disk"""
        with self.patient_map_lock:
            # Save both the original info and encrypted values
            with open(self.patient_info_map_file, 'w') as f:
                combined_map = {
                    'patient_info': self.patient_info_map,
                    'encrypted_values': self.encrypted_values_map
                }
                json.dump(combined_map, f, indent=2)
    
    def encrypt_dataset(self, dataset: Dataset) -> Dict:
        """
        Encrypt patient identifiable information in a DICOM dataset
        
        Parameters:
        -----------
        dataset : Dataset
            The DICOM dataset to encrypt
            
        Returns:
        --------
        Dict: Dictionary containing the original values that were encrypted
        """
        original_info = {}
        
        # Get study UID for mapping
        study_uid = dataset.StudyInstanceUID
        
        # Initialize maps if needed
        if study_uid not in self.patient_info_map:
            self.patient_info_map[study_uid] = {}
        
        if study_uid not in self.encrypted_values_map:
            self.encrypted_values_map[study_uid] = {}
        
        # Encrypt PII fields that exist in the dataset
        for tag in PII_TAGS:
            if hasattr(dataset, tag) and getattr(dataset, tag):
                value = str(getattr(dataset, tag))
                
                # Store original value for later retrieval
                if tag not in self.patient_info_map[study_uid]:
                    self.patient_info_map[study_uid][tag] = value
                
                # Check if we've already encrypted this value
                if tag in self.encrypted_values_map[study_uid]:
                    # Reuse the existing encrypted value for consistency
                    encrypted_value = self.encrypted_values_map[study_uid][tag]
                else:
                    # New value to encrypt - generate and store it
                    encrypted_value = self.fernet.encrypt(value.encode()).decode()
                    self.encrypted_values_map[study_uid][tag] = encrypted_value
                
                # Save the original value before anonymizing
                original_info[tag] = value
                
                # Replace with the encrypted value
                setattr(dataset, tag, encrypted_value)
        
        # Save updated map to disk
        self._save_patient_info_map()
        
        return original_info
    
    def decrypt_dataset(self, dataset: Dataset) -> bool:
        """
        Restore original patient information to a dataset
        
        Parameters:
        -----------
        dataset : Dataset
            The DICOM dataset with encrypted values
            
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


def restore_file(encrypted_file: str, original_file: str, key_file: str, map_file: Optional[str] = None):
    """
    Restore original patient information to a DICOM file
    
    Parameters:
    -----------
    encrypted_file : str
        Path to the encrypted DICOM file
    original_file : str
        Path to save the restored DICOM file
    key_file : str
        Path to the encryption key file
    map_file : str, optional
        Path to the patient info map file
    
    Returns:
    --------
    bool: True if successful, False otherwise
    """
    from pydicom import dcmread
    
    with open(key_file, 'rb') as f:
        key = f.read()
    
    fernet = Fernet(key)
    
    if map_file is None:
        file_path = Path(encrypted_file)
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
    
    dataset = dcmread(encrypted_file)
    
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