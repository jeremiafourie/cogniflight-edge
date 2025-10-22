"""
CogniCore Exceptions - Simple and essential error handling
"""


class CogniCoreError(Exception):
    """Base exception for CogniCore errors."""
    pass


class ConnectionError(CogniCoreError):
    """Redis connection failed."""
    pass


class ValidationError(CogniCoreError):
    """Data validation failed."""
    pass


class InvalidStateTransitionError(CogniCoreError):
    """Invalid system state transition attempted."""
    pass


class StatePermissionError(CogniCoreError):
    """Service attempted to set state it doesn't have permission for."""
    pass