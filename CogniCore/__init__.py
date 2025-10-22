"""
CogniCore - Embedded Redis-based Communication Library

A clean, hash-based communication system where services publish data to Redis hashes
and other services subscribe to hash changes to get the latest data they need.

Key Features:
- Redis hashes for all data storage (latest values always available)
- Hash change notifications via Redis keyspace events
- System state management
- Pilot profile storage
- Automatic offline fallback

Usage:
    from CogniCore import CogniCore
    
    core = CogniCore("service_name")
    core.publish_data("vision", {"ear": 0.25, "mar": 0.3})
    data = core.get_data("vision")
"""

from .cognicore import CogniCore
from .state import SystemState, PilotProfile
from .exceptions import CogniCoreError, ConnectionError, ValidationError, InvalidStateTransitionError, StatePermissionError
from . import config

__version__ = "1.1.0"
__all__ = ["CogniCore", "SystemState", "PilotProfile", "config", "CogniCoreError", "ConnectionError", "ValidationError", "InvalidStateTransitionError", "StatePermissionError"]