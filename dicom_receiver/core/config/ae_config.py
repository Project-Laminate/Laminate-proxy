#!/usr/bin/env python
"""
DICOM AE Configuration

Configuration for mapping AE titles to network addresses for C-MOVE operations
"""

import logging

logger = logging.getLogger('dicom_receiver.config.ae')

# Default AE configuration
# Maps AE titles to (IP, Port) tuples
DEFAULT_AE_CONFIG = {
    'HOROS': ('127.0.0.1', 11113),
    'OSIRIX': ('127.0.0.1', 11113),
    'DICOMRCV': ('127.0.0.1', 11112),
    'WORKSTATION': ('127.0.0.1', 11113),
    'VIEWER': ('127.0.0.1', 11113),
    # Common Mac computer names
    'AMRS-MACBOOK-PRO': ('127.0.0.1', 11113),
    'MACBOOK-PRO': ('127.0.0.1', 11113),
    'MACBOOK-AIR': ('127.0.0.1', 11113),
}

class AEConfiguration:
    """
    Configuration manager for DICOM Application Entities
    
    Manages the mapping between AE titles and their network addresses
    for C-MOVE operations.
    """
    
    def __init__(self, config_dict=None):
        """
        Initialize AE configuration
        
        Parameters:
        -----------
        config_dict : dict, optional
            Custom AE configuration dictionary
        """
        self.ae_config = config_dict or DEFAULT_AE_CONFIG.copy()
        logger.info(f"AE Configuration initialized with {len(self.ae_config)} entries")
    
    def get_ae_address(self, ae_title):
        """
        Get the network address for an AE title
        
        Parameters:
        -----------
        ae_title : str
            The AE title to look up
            
        Returns:
        --------
        tuple or None
            (IP, Port) tuple if found, None otherwise
        """
        ae_title = ae_title.upper().strip()
        address = self.ae_config.get(ae_title)
        
        if address:
            logger.info(f"Found AE configuration for '{ae_title}': {address[0]}:{address[1]}")
        else:
            logger.warning(f"No AE configuration found for '{ae_title}', using default")
            # Return default localhost configuration
            address = ('127.0.0.1', 11113)
        
        return address
    
    def add_ae(self, ae_title, ip, port):
        """
        Add or update an AE configuration
        
        Parameters:
        -----------
        ae_title : str
            The AE title
        ip : str
            IP address
        port : int
            Port number
        """
        ae_title = ae_title.upper().strip()
        self.ae_config[ae_title] = (ip, port)
        logger.info(f"Added/updated AE configuration: '{ae_title}' -> {ip}:{port}")
    
    def remove_ae(self, ae_title):
        """
        Remove an AE configuration
        
        Parameters:
        -----------
        ae_title : str
            The AE title to remove
        """
        ae_title = ae_title.upper().strip()
        if ae_title in self.ae_config:
            del self.ae_config[ae_title]
            logger.info(f"Removed AE configuration for '{ae_title}'")
        else:
            logger.warning(f"AE configuration for '{ae_title}' not found")
    
    def list_aes(self):
        """
        List all configured AEs
        
        Returns:
        --------
        dict
            Dictionary of AE configurations
        """
        return self.ae_config.copy()
    
    def is_ae_configured(self, ae_title):
        """
        Check if an AE is configured
        
        Parameters:
        -----------
        ae_title : str
            The AE title to check
            
        Returns:
        --------
        bool
            True if configured, False otherwise
        """
        ae_title = ae_title.upper().strip()
        return ae_title in self.ae_config 