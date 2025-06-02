#!/usr/bin/env python
"""
Command-line interface for managing DICOM nodes and automatic forwarding

This CLI allows users to manage node configurations and monitor forwarding status.
"""

import argparse
from dicom_receiver.utils import json_utils as json
import logging
from pathlib import Path

from dicom_receiver.config import (
    DEFAULT_DATA_DIR,
    DEFAULT_STORAGE_DIR,
    DEFAULT_LOG_LEVEL,
    DEFAULT_LOG_FILE,
    DEFAULT_API_URL,
    DEFAULT_API_USERNAME,
    DEFAULT_API_PASSWORD,
    DEFAULT_API_TOKEN,
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_DELAY,
    ensure_dirs_exist
)
from dicom_receiver.utils.logging_config import configure_logging
from dicom_receiver.core.query import DicomQueryHandler
from dicom_receiver.core.utils.api_integration import ApiIntegrationUtils
from dicom_receiver.core.node_manager import NodeManager

logger = logging.getLogger('dicom_receiver.node_manager_cli')

def main():
    """Main entry point for the node manager CLI"""
    parser = argparse.ArgumentParser(description='Manage DICOM nodes and automatic forwarding')
    
    # Storage and data directories
    parser.add_argument('--data-dir', type=str, default=DEFAULT_DATA_DIR,
                        help=f'Base directory for all data (default/env: {DEFAULT_DATA_DIR})')
    parser.add_argument('--storage', type=str, default=DEFAULT_STORAGE_DIR,
                        help=f'Directory containing node configuration (default/env: {DEFAULT_STORAGE_DIR})')
    
    # API configuration
    parser.add_argument('--api-url', type=str, default=DEFAULT_API_URL,
                        help=f'URL of the API (default/env: {DEFAULT_API_URL})')
    parser.add_argument('--api-username', type=str, default=DEFAULT_API_USERNAME,
                        help='Username for API authentication (default from env variable)')
    parser.add_argument('--api-password', type=str, default=DEFAULT_API_PASSWORD,
                        help='Password for API authentication (default from env variable)')
    parser.add_argument('--api-token', type=str, default=DEFAULT_API_TOKEN,
                        help='Token for API authentication (default from env variable)')
    
    # Retry configuration
    parser.add_argument('--max-retries', type=int, default=DEFAULT_MAX_RETRIES,
                       help=f'Maximum number of retry attempts (default/env: {DEFAULT_MAX_RETRIES})')
    parser.add_argument('--retry-delay', type=int, default=DEFAULT_RETRY_DELAY,
                       help=f'Delay in seconds between retry attempts (default/env: {DEFAULT_RETRY_DELAY})')
    
    # Logging configuration
    parser.add_argument('--log-level', type=str, default=DEFAULT_LOG_LEVEL,
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                        help=f'Logging level (default/env: {DEFAULT_LOG_LEVEL})')
    parser.add_argument('--log-file', type=str, default=DEFAULT_LOG_FILE,
                        help='Log to file instead of console')
    
    # Commands
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # List nodes
    list_parser = subparsers.add_parser('list', help='List all configured nodes')
    list_parser.add_argument('--stats', action='store_true', help='Show forwarding statistics')
    
    # Add node
    add_parser = subparsers.add_parser('add', help='Add or update a node')
    add_parser.add_argument('node_id', help='Unique identifier for the node')
    add_parser.add_argument('name', help='Human-readable name for the node')
    add_parser.add_argument('ip', help='IP address of the node')
    add_parser.add_argument('port', type=int, help='Port number of the node')
    add_parser.add_argument('aet', help='AE Title of the node')
    add_parser.add_argument('--enabled', action='store_true', default=True, help='Enable the node (default: True)')
    add_parser.add_argument('--disabled', action='store_true', help='Disable the node')
    add_parser.add_argument('--description', type=str, default='', help='Description of the node')
    
    # Remove node
    remove_parser = subparsers.add_parser('remove', help='Remove a node')
    remove_parser.add_argument('node_id', help='Unique identifier for the node to remove')
    
    # Enable/disable node
    enable_parser = subparsers.add_parser('enable', help='Enable a node')
    enable_parser.add_argument('node_id', help='Unique identifier for the node to enable')
    
    disable_parser = subparsers.add_parser('disable', help='Disable a node')
    disable_parser.add_argument('node_id', help='Unique identifier for the node to disable')
    
    # Test node connection
    test_parser = subparsers.add_parser('test', help='Test connection to a node')
    test_parser.add_argument('node_id', help='Unique identifier for the node to test')
    
    # Clear tracking
    clear_parser = subparsers.add_parser('clear-tracking', help='Clear forwarding tracking data')
    clear_parser.add_argument('--node-id', type=str, help='Clear tracking for specific node only')
    clear_parser.add_argument('--all', action='store_true', help='Clear all tracking data')
    
    # Show configuration
    config_parser = subparsers.add_parser('config', help='Show nodes.json configuration file')
    
    args = parser.parse_args()
    
    # Ensure directories exist
    ensure_dirs_exist()
    
    # Configure logging
    log_level = getattr(logging, args.log_level)
    configure_logging(level=log_level, log_file=args.log_file)
    
    # Validate API URL
    if not args.api_url:
        logger.error("API URL is required. Set DICOM_RECEIVER_API_URL environment variable or use --api-url")
        return 1
    
    # Initialize components
    try:
        query_handler = DicomQueryHandler(
            api_url=args.api_url,
            storage_dir=args.storage,
            username=args.api_username,
            password=args.api_password,
            token=args.api_token,
            max_retries=args.max_retries,
            retry_delay=args.retry_delay
        )
        
        api_integration_utils = ApiIntegrationUtils(query_handler, args.api_url)
        
        node_manager = NodeManager(
            args.storage,
            query_handler,
            api_integration_utils
        )
        
    except Exception as e:
        logger.error(f"Failed to initialize components: {e}")
        return 1
    
    # Execute command
    if args.command == 'list':
        return cmd_list_nodes(node_manager, args.stats)
    elif args.command == 'add':
        enabled = args.enabled and not args.disabled
        return cmd_add_node(node_manager, args.node_id, args.name, args.ip, args.port, args.aet, enabled, args.description)
    elif args.command == 'remove':
        return cmd_remove_node(node_manager, args.node_id)
    elif args.command == 'enable':
        return cmd_enable_node(node_manager, args.node_id)
    elif args.command == 'disable':
        return cmd_disable_node(node_manager, args.node_id)
    elif args.command == 'test':
        return cmd_test_node(node_manager, args.node_id)
    elif args.command == 'clear-tracking':
        return cmd_clear_tracking(node_manager, args.node_id, args.all)
    elif args.command == 'config':
        return cmd_show_config(node_manager)
    else:
        parser.print_help()
        return 1

def cmd_list_nodes(node_manager: NodeManager, show_stats: bool = False):
    """List all configured nodes"""
    nodes = node_manager.nodes
    
    if not nodes:
        print("No nodes configured.")
        print(f"Configuration file: {node_manager.nodes_file}")
        return 0
    
    print(f"Configured DICOM Nodes ({len(nodes)} total):")
    print("=" * 60)
    
    for node_id, config in nodes.items():
        status = "✅ ENABLED" if config.get('enabled', True) else "❌ DISABLED"
        print(f"ID: {node_id}")
        print(f"  Name: {config['name']}")
        print(f"  Address: {config['ip']}:{config['port']}")
        print(f"  AE Title: {config['aet']}")
        print(f"  Status: {status}")
        if config.get('description'):
            print(f"  Description: {config['description']}")
        print()
    
    if show_stats:
        print("Forwarding Statistics:")
        print("=" * 60)
        stats = node_manager.get_forwarding_stats()
        print(f"Auto-forwarding: {'🟢 RUNNING' if stats['is_running'] else '🔴 STOPPED'}")
        print(f"Total nodes: {stats['total_nodes']}")
        print(f"Enabled nodes: {stats['enabled_nodes']}")
        print()
        
        for node_id, node_stats in stats['nodes'].items():
            status = "✅" if node_stats['enabled'] else "❌"
            print(f"{status} {node_stats['name']}: {node_stats['series_sent']} series forwarded")
    
    return 0

def cmd_add_node(node_manager: NodeManager, node_id: str, name: str, ip: str, port: int, aet: str, enabled: bool, description: str):
    """Add or update a node"""
    try:
        node_manager.add_node(node_id, name, ip, port, aet, enabled, description)
        status = "enabled" if enabled else "disabled"
        print(f"✅ Successfully added/updated node '{node_id}' ({status})")
        print(f"   Name: {name}")
        print(f"   Address: {ip}:{port}")
        print(f"   AE Title: {aet}")
        if description:
            print(f"   Description: {description}")
        return 0
    except Exception as e:
        print(f"❌ Error adding node: {e}")
        return 1

def cmd_remove_node(node_manager: NodeManager, node_id: str):
    """Remove a node"""
    if node_id not in node_manager.nodes:
        print(f"❌ Node '{node_id}' not found")
        return 1
    
    try:
        node_name = node_manager.nodes[node_id]['name']
        node_manager.remove_node(node_id)
        print(f"✅ Successfully removed node '{node_id}' ({node_name})")
        return 0
    except Exception as e:
        print(f"❌ Error removing node: {e}")
        return 1

def cmd_enable_node(node_manager: NodeManager, node_id: str):
    """Enable a node"""
    if node_id not in node_manager.nodes:
        print(f"❌ Node '{node_id}' not found")
        return 1
    
    try:
        config = node_manager.nodes[node_id]
        node_manager.add_node(
            node_id, config['name'], config['ip'], config['port'], 
            config['aet'], True, config.get('description', '')
        )
        print(f"✅ Enabled node '{node_id}' ({config['name']})")
        return 0
    except Exception as e:
        print(f"❌ Error enabling node: {e}")
        return 1

def cmd_disable_node(node_manager: NodeManager, node_id: str):
    """Disable a node"""
    if node_id not in node_manager.nodes:
        print(f"❌ Node '{node_id}' not found")
        return 1
    
    try:
        config = node_manager.nodes[node_id]
        node_manager.add_node(
            node_id, config['name'], config['ip'], config['port'], 
            config['aet'], False, config.get('description', '')
        )
        print(f"❌ Disabled node '{node_id}' ({config['name']})")
        return 0
    except Exception as e:
        print(f"❌ Error disabling node: {e}")
        return 1

def cmd_test_node(node_manager: NodeManager, node_id: str):
    """Test connection to a node"""
    if node_id not in node_manager.nodes:
        print(f"❌ Node '{node_id}' not found")
        return 1
    
    config = node_manager.nodes[node_id]
    print(f"🔍 Testing connection to '{config['name']}'...")
    print(f"   Address: {config['ip']}:{config['port']}")
    print(f"   AE Title: {config['aet']}")
    
    try:
        from pynetdicom import AE
        from pynetdicom.sop_class import Verification
        
        # Create AE and add verification context
        ae = AE()
        ae.add_requested_context(Verification)
        
        # Try to establish association
        assoc = ae.associate(config['ip'], config['port'], ae_title=config['aet'])
        
        if assoc.is_established:
            print("✅ Connection successful!")
            
            # Send C-ECHO to test
            status = assoc.send_c_echo()
            if status:
                print("✅ C-ECHO successful!")
            else:
                print("⚠️ C-ECHO failed")
            
            assoc.release()
            return 0
        else:
            print("❌ Failed to establish association")
            return 1
            
    except Exception as e:
        print(f"❌ Connection test failed: {e}")
        return 1

def cmd_clear_tracking(node_manager: NodeManager, node_id: str = None, clear_all: bool = False):
    """Clear forwarding tracking data"""
    if clear_all:
        try:
            node_manager.clear_all_tracking()
            print("✅ Cleared all tracking data")
            return 0
        except Exception as e:
            print(f"❌ Error clearing tracking data: {e}")
            return 1
    elif node_id:
        if node_id not in node_manager.nodes:
            print(f"❌ Node '{node_id}' not found")
            return 1
        try:
            node_manager.clear_tracking_for_node(node_id)
            print(f"✅ Cleared tracking data for node '{node_id}'")
            return 0
        except Exception as e:
            print(f"❌ Error clearing tracking data: {e}")
            return 1
    else:
        print("❌ Must specify either --node-id or --all")
        return 1

def cmd_show_config(node_manager: NodeManager):
    """Show the nodes.json configuration file"""
    try:
        if node_manager.nodes_file.exists():
            with open(node_manager.nodes_file, 'r') as f:
                config = json.load(f)
            print(f"Configuration file: {node_manager.nodes_file}")
            print("=" * 60)
            print(json.dumps(config, indent=2))
        else:
            print(f"Configuration file not found: {node_manager.nodes_file}")
        return 0
    except Exception as e:
        print(f"❌ Error reading configuration: {e}")
        return 1

if __name__ == '__main__':
    exit(main()) 