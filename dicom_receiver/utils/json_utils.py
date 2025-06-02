#!/usr/bin/env python
"""
JSON utilities with performance optimization

Provides a unified interface for JSON operations with automatic fallback
from orjson (fast) to standard json (compatible)
"""

import logging
from typing import Any, Dict, Union, IO
from pathlib import Path

logger = logging.getLogger('dicom_receiver.utils.json')

try:
    import orjson
    HAS_ORJSON = True
    logger.info("Using orjson for enhanced JSON performance")
except ImportError:
    import json
    HAS_ORJSON = False
    logger.info("Using standard json library (consider installing orjson for better performance)")

def _convert_keys_to_strings(obj: Any) -> Any:
    """
    Recursively convert dictionary keys to strings for orjson compatibility
    
    Args:
        obj: Object to process
        
    Returns:
        Object with string keys
    """
    if isinstance(obj, dict):
        return {str(k): _convert_keys_to_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_keys_to_strings(item) for item in obj]
    else:
        return obj

def loads(data: Union[str, bytes]) -> Any:
    """
    Parse JSON string/bytes to Python object
    
    Args:
        data: JSON string or bytes to parse
        
    Returns:
        Parsed Python object
    """
    if HAS_ORJSON:
        if isinstance(data, str):
            data = data.encode('utf-8')
        return orjson.loads(data)
    else:
        if isinstance(data, bytes):
            data = data.decode('utf-8')
        return json.loads(data)

def dumps(obj: Any, indent: int = None, ensure_ascii: bool = True) -> str:
    """
    Serialize Python object to JSON string
    
    Args:
        obj: Python object to serialize
        indent: Number of spaces for indentation (None for compact)
        ensure_ascii: Whether to escape non-ASCII characters
        
    Returns:
        JSON string
    """
    if HAS_ORJSON:
        # Convert non-string keys to strings for orjson compatibility
        obj = _convert_keys_to_strings(obj)
        
        option = 0  # No options by default
        if indent is not None:
            option |= orjson.OPT_INDENT_2
        
        result = orjson.dumps(obj, option=option)
        return result.decode('utf-8')
    else:
        return json.dumps(obj, indent=indent, ensure_ascii=ensure_ascii)

def load(fp: IO) -> Any:
    """
    Parse JSON from file-like object
    
    Args:
        fp: File-like object containing JSON
        
    Returns:
        Parsed Python object
    """
    if HAS_ORJSON:
        data = fp.read()
        if isinstance(data, str):
            data = data.encode('utf-8')
        return orjson.loads(data)
    else:
        return json.load(fp)

def dump(obj: Any, fp: IO, indent: int = None, ensure_ascii: bool = True) -> None:
    """
    Serialize Python object to JSON and write to file-like object
    
    Args:
        obj: Python object to serialize
        fp: File-like object to write to
        indent: Number of spaces for indentation (None for compact)
        ensure_ascii: Whether to escape non-ASCII characters
    """
    if HAS_ORJSON:
        # Convert non-string keys to strings for orjson compatibility
        obj = _convert_keys_to_strings(obj)
        
        option = 0  # No options by default
        if indent is not None:
            option |= orjson.OPT_INDENT_2
            
        result = orjson.dumps(obj, option=option)
        fp.write(result.decode('utf-8'))
    else:
        json.dump(obj, fp, indent=indent, ensure_ascii=ensure_ascii)

def load_file(file_path: Union[str, Path]) -> Any:
    """
    Load JSON from file path
    
    Args:
        file_path: Path to JSON file
        
    Returns:
        Parsed Python object
    """
    file_path = Path(file_path)
    with open(file_path, 'r', encoding='utf-8') as f:
        return load(f)

def save_file(obj: Any, file_path: Union[str, Path], indent: int = 2, ensure_ascii: bool = True) -> None:
    """
    Save Python object as JSON to file path
    
    Args:
        obj: Python object to serialize
        file_path: Path to save JSON file
        indent: Number of spaces for indentation
        ensure_ascii: Whether to escape non-ASCII characters
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        dump(obj, f, indent=indent, ensure_ascii=ensure_ascii)

# Exception handling
try:
    if HAS_ORJSON:
        JSONDecodeError = orjson.JSONDecodeError
    else:
        JSONDecodeError = json.JSONDecodeError
except AttributeError:
    # Fallback for older versions
    JSONDecodeError = ValueError

# Performance monitoring
def get_json_backend() -> str:
    """Get the current JSON backend being used"""
    return "orjson" if HAS_ORJSON else "json"

def is_orjson_available() -> bool:
    """Check if orjson is available"""
    return HAS_ORJSON 