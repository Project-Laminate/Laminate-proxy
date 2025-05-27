#!/usr/bin/env python
"""
Node Manager for automatic DICOM forwarding

Manages node configurations and automatically forwards new series from API
to configured DICOM nodes with duplicate prevention.
"""

import json
import logging
import threading
import time
from pathlib import Path
from typing import Dict, List, Set, Optional
from datetime import datetime

from pynetdicom import AE, debug_logger
from pynetdicom.sop_class import CTImageStorage, MRImageStorage, XRayAngiographicImageStorage
from pydicom import dcmread
from io import BytesIO

logger = logging.getLogger('dicom_receiver.node_manager')

class NodeManager:
    """
    Manages DICOM nodes and automatic forwarding of new series
    """
    
    def __init__(self, storage_dir: str, query_handler, api_integration_utils):
        """
        Initialize the Node Manager
        
        Parameters:
        -----------
        storage_dir : str
            Storage directory path
        query_handler : DicomQueryHandler
            Query handler for API operations
        api_integration_utils : ApiIntegrationUtils
            API integration utilities
        """
        self.storage_dir = Path(storage_dir)
        self.query_handler = query_handler
        self.api_integration_utils = api_integration_utils
        
        # File paths
        self.nodes_file = self.storage_dir / "nodes.json"
        self.tracking_file = self.storage_dir / "forwarding_tracking.json"
        
        # State
        self.nodes = {}
        self.sent_tracking = {}  # {node_name: {series_uid: timestamp}}
        self.is_running = False
        self.polling_thread = None
        self.stop_event = threading.Event()
        
        # Load existing configuration
        self._load_nodes()
        self._load_tracking()
        
        logger.info(f"NodeManager initialized with {len(self.nodes)} nodes")
    
    def _load_nodes(self):
        """Load node configuration from nodes.json"""
        try:
            if self.nodes_file.exists():
                with open(self.nodes_file, 'r') as f:
                    data = json.load(f)
                    self.nodes = data.get('nodes', {})
                logger.info(f"Loaded {len(self.nodes)} nodes from {self.nodes_file}")
            else:
                # Create default nodes.json file
                self._create_default_nodes_file()
        except Exception as e:
            logger.error(f"Error loading nodes configuration: {e}")
            self.nodes = {}
    
    def _create_default_nodes_file(self):
        """Create a default nodes.json file with example configuration"""
        default_config = {
            "nodes": {
                "horos_workstation": {
                    "name": "Horos Workstation",
                    "ip": "127.0.0.1",
                    "port": 11113,
                    "aet": "HOROS",
                    "enabled": True,
                    "description": "Local Horos DICOM viewer"
                },
                "pacs_server": {
                    "name": "PACS Server",
                    "ip": "192.168.1.100",
                    "port": 104,
                    "aet": "PACS",
                    "enabled": False,
                    "description": "Main PACS server"
                }
            },
            "settings": {
                "polling_interval": 60,
                "max_retry_attempts": 3,
                "retry_delay": 5,
                "auto_forward_enabled": True
            }
        }
        
        try:
            with open(self.nodes_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            
            self.nodes = default_config['nodes']
            logger.info(f"Created default nodes configuration at {self.nodes_file}")
            
        except Exception as e:
            logger.error(f"Error creating default nodes file: {e}")
    
    def _load_tracking(self):
        """Load forwarding tracking data"""
        try:
            if self.tracking_file.exists():
                with open(self.tracking_file, 'r') as f:
                    self.sent_tracking = json.load(f)
                logger.info(f"Loaded forwarding tracking data for {len(self.sent_tracking)} nodes")
            else:
                self.sent_tracking = {}
        except Exception as e:
            logger.error(f"Error loading tracking data: {e}")
            self.sent_tracking = {}
    
    def _save_tracking(self):
        """Save forwarding tracking data"""
        try:
            with open(self.tracking_file, 'w') as f:
                json.dump(self.sent_tracking, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving tracking data: {e}")
    
    def get_enabled_nodes(self) -> Dict:
        """Get all enabled nodes"""
        return {k: v for k, v in self.nodes.items() if v.get('enabled', True)}
    
    def add_node(self, node_id: str, name: str, ip: str, port: int, aet: str, enabled: bool = True, description: str = ""):
        """Add or update a node configuration"""
        self.nodes[node_id] = {
            "name": name,
            "ip": ip,
            "port": port,
            "aet": aet,
            "enabled": enabled,
            "description": description
        }
        
        # Save to file
        try:
            # Load current file to preserve settings
            config = {"nodes": self.nodes}
            if self.nodes_file.exists():
                with open(self.nodes_file, 'r') as f:
                    existing = json.load(f)
                    config["settings"] = existing.get("settings", {})
            
            with open(self.nodes_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            logger.info(f"Added/updated node '{node_id}': {name} ({ip}:{port}, AET: {aet})")
            
        except Exception as e:
            logger.error(f"Error saving node configuration: {e}")
    
    def remove_node(self, node_id: str):
        """Remove a node configuration"""
        if node_id in self.nodes:
            del self.nodes[node_id]
            
            # Remove from tracking as well
            if node_id in self.sent_tracking:
                del self.sent_tracking[node_id]
                self._save_tracking()
            
            # Save nodes file
            try:
                config = {"nodes": self.nodes}
                if self.nodes_file.exists():
                    with open(self.nodes_file, 'r') as f:
                        existing = json.load(f)
                        config["settings"] = existing.get("settings", {})
                
                with open(self.nodes_file, 'w') as f:
                    json.dump(config, f, indent=2)
                
                logger.info(f"Removed node '{node_id}'")
                
            except Exception as e:
                logger.error(f"Error saving node configuration: {e}")
    
    def start_auto_forwarding(self):
        """Start the automatic forwarding service"""
        if self.is_running:
            logger.warning("Auto-forwarding is already running")
            return
        
        self.is_running = True
        self.stop_event.clear()
        
        self.polling_thread = threading.Thread(target=self._polling_loop, daemon=True)
        self.polling_thread.start()
        
        logger.info("🚀 Started automatic DICOM forwarding service")
    
    def stop_auto_forwarding(self):
        """Stop the automatic forwarding service"""
        if not self.is_running:
            return
        
        self.is_running = False
        self.stop_event.set()
        
        if self.polling_thread:
            self.polling_thread.join(timeout=5)
        
        logger.info("🛑 Stopped automatic DICOM forwarding service")
    
    def _polling_loop(self):
        """Main polling loop that runs every minute"""
        logger.info("📡 Starting API polling loop (every 60 seconds)")
        
        while not self.stop_event.wait(60):  # Wait 60 seconds or until stop event
            try:
                self._check_and_forward_new_series()
            except Exception as e:
                logger.error(f"Error in polling loop: {e}")
    
    def _check_and_forward_new_series(self):
        """Check API for new series and forward to nodes"""
        try:
            logger.debug("🔍 Checking API for new series...")
            
            # Query API for all metadata
            api_data = self.query_handler.query_all_metadata()
            if not api_data or 'results' not in api_data:
                logger.debug("No API data available")
                return
            
            enabled_nodes = self.get_enabled_nodes()
            if not enabled_nodes:
                logger.debug("No enabled nodes for forwarding")
                return
            
            new_series_count = 0
            
            # Process each result
            for result_item in api_data['results']:
                if 'dicom_data' not in result_item or 'studies' not in result_item['dicom_data']:
                    continue
                
                result_id = result_item['result']['id']
                studies_data = result_item['dicom_data']['studies']
                
                # Process each study
                for study_uid, study_info in studies_data.items():
                    if 'series' not in study_info:
                        continue
                    
                    # Process each series
                    for series_uid in study_info['series'].keys():
                        # Check if this series needs to be forwarded to any nodes
                        for node_id, node_config in enabled_nodes.items():
                            if not self._is_series_sent(node_id, series_uid):
                                logger.info(f"📤 New series found: {series_uid[:20]}... -> {node_config['name']}")
                                
                                # Forward the series
                                if self._forward_series_to_node(result_id, series_uid, study_uid, node_id, node_config):
                                    self._mark_series_sent(node_id, series_uid)
                                    new_series_count += 1
            
            if new_series_count > 0:
                logger.info(f"✅ Forwarded {new_series_count} new series to nodes")
                self._save_tracking()
            else:
                logger.debug("No new series to forward")
                
        except Exception as e:
            logger.error(f"Error checking for new series: {e}")
    
    def _is_series_sent(self, node_id: str, series_uid: str) -> bool:
        """Check if a series has already been sent to a node"""
        return (node_id in self.sent_tracking and 
                series_uid in self.sent_tracking[node_id])
    
    def _mark_series_sent(self, node_id: str, series_uid: str):
        """Mark a series as sent to a node"""
        if node_id not in self.sent_tracking:
            self.sent_tracking[node_id] = {}
        
        self.sent_tracking[node_id][series_uid] = datetime.now().isoformat()
    
    def _forward_series_to_node(self, result_id: str, series_uid: str, study_uid: str, node_id: str, node_config: Dict) -> bool:
        """Forward a series to a specific node"""
        try:
            logger.info(f"📤 Forwarding series {series_uid[:20]}... to {node_config['name']} ({node_config['ip']}:{node_config['port']})")
            
            # Download series from API
            series_files = self.api_integration_utils.download_series_from_api(result_id, series_uid)
            if not series_files:
                logger.error(f"❌ Failed to download series {series_uid} from API")
                return False
            
            logger.info(f"📥 Downloaded {len(series_files)} files for series")
            
            # Send files to node via C-STORE
            success = self._send_files_to_node(series_files, node_config)
            
            if success:
                logger.info(f"✅ Successfully forwarded series {series_uid[:20]}... to {node_config['name']}")
            else:
                logger.error(f"❌ Failed to forward series {series_uid[:20]}... to {node_config['name']}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error forwarding series {series_uid} to {node_config['name']}: {e}")
            return False
    
    def _send_files_to_node(self, file_data_list: List[bytes], node_config: Dict) -> bool:
        """Send DICOM files to a node via C-STORE"""
        try:
            # Create Application Entity
            ae = AE()
            ae.add_requested_context(CTImageStorage)
            ae.add_requested_context(MRImageStorage)
            ae.add_requested_context(XRayAngiographicImageStorage)
            
            # Add more SOP classes as needed
            from pynetdicom.sop_class import (
                ComputedRadiographyImageStorage,
                DigitalXRayImageStorageForPresentation,
                DigitalXRayImageStorageForProcessing,
                UltrasoundImageStorage,
                SecondaryCaptureImageStorage
            )
            ae.add_requested_context(ComputedRadiographyImageStorage)
            ae.add_requested_context(DigitalXRayImageStorageForPresentation)
            ae.add_requested_context(DigitalXRayImageStorageForProcessing)
            ae.add_requested_context(UltrasoundImageStorage)
            ae.add_requested_context(SecondaryCaptureImageStorage)
            
            # Connect to the node
            assoc = ae.associate(
                node_config['ip'], 
                node_config['port'], 
                ae_title=node_config['aet']
            )
            
            if not assoc.is_established:
                logger.error(f"❌ Failed to establish association with {node_config['name']}")
                return False
            
            logger.info(f"🔗 Established association with {node_config['name']}")
            
            success_count = 0
            total_files = len(file_data_list)
            
            # Send each file
            for i, file_data in enumerate(file_data_list, 1):
                try:
                    # Read DICOM dataset from bytes
                    ds = dcmread(BytesIO(file_data), force=True)
                    
                    # Send C-STORE request
                    status = assoc.send_c_store(ds)
                    
                    if status:
                        if status.Status == 0x0000:  # Success
                            success_count += 1
                            logger.debug(f"✅ Sent file {i}/{total_files}")
                        else:
                            logger.warning(f"⚠️ C-STORE failed for file {i}/{total_files}: Status 0x{status.Status:04x}")
                    else:
                        logger.warning(f"⚠️ No response for file {i}/{total_files}")
                        
                except Exception as e:
                    logger.error(f"❌ Error sending file {i}/{total_files}: {e}")
            
            # Release association
            assoc.release()
            
            logger.info(f"📊 Sent {success_count}/{total_files} files to {node_config['name']}")
            
            # Consider it successful if at least 80% of files were sent
            return success_count >= (total_files * 0.8)
            
        except Exception as e:
            logger.error(f"Error sending files to {node_config['name']}: {e}")
            return False
    
    def get_forwarding_stats(self) -> Dict:
        """Get forwarding statistics"""
        stats = {
            "total_nodes": len(self.nodes),
            "enabled_nodes": len(self.get_enabled_nodes()),
            "is_running": self.is_running,
            "nodes": {}
        }
        
        for node_id, node_config in self.nodes.items():
            sent_count = len(self.sent_tracking.get(node_id, {}))
            stats["nodes"][node_id] = {
                "name": node_config["name"],
                "enabled": node_config.get("enabled", True),
                "series_sent": sent_count
            }
        
        return stats
    
    def clear_tracking_for_node(self, node_id: str):
        """Clear tracking data for a specific node (allows re-sending)"""
        if node_id in self.sent_tracking:
            del self.sent_tracking[node_id]
            self._save_tracking()
            logger.info(f"Cleared tracking data for node '{node_id}'")
    
    def clear_all_tracking(self):
        """Clear all tracking data (allows re-sending everything)"""
        self.sent_tracking = {}
        self._save_tracking()
        logger.info("Cleared all tracking data") 