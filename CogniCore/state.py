"""CogniCore State Management - Thread-safe state management with proper architecture"""

import threading
import time
import logging
from collections import deque
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Callable

logger = logging.getLogger("CogniCore.StateManager")


class SystemState(Enum):
    """System operational states for pilot fatigue detection and safety monitoring"""
    SCANNING = "scanning"                    # Looking for pilot, connecting to HR sensor, or processing
    INTRUDER_DETECTED = "intruder_detected"  # Unknown/unauthorized person detected
    MONITORING_ACTIVE = "monitoring_active"  # Actively monitoring pilot, no fatigue detected
    ALERT_MILD = "alert_mild"               # Early fatigue warning (fusion score ~0.3)
    ALERT_MODERATE = "alert_moderate"       # Escalated fatigue warning (fusion score ~0.6)
    ALERT_SEVERE = "alert_severe"           # Critical fatigue alert (fusion score ~0.8)
    ALCOHOL_DETECTED = "alcohol_detected"   # Alcohol vapor detected by MQ3 sensor - CRITICAL SAFETY ALERT
    SYSTEM_ERROR = "system_error"           # Service error or malfunction
    SYSTEM_CRASHED = "system_crashed"       # Critical system failure, watchdog unable to recover


@dataclass
class PilotProfile:
    """Pilot profile data structure"""
    username: str
    authenticated: bool
    flight_finished: bool
    flight_id: str
    personal_data: Dict[str, Any]


# Service state permission definitions for enhanced security
SERVICE_STATE_PERMISSIONS = {
    "vision_processor": [
        SystemState.SCANNING,
        SystemState.INTRUDER_DETECTED,
        SystemState.SYSTEM_ERROR
    ],
    "predictor": [
        SystemState.MONITORING_ACTIVE,
        SystemState.ALERT_MILD,
        SystemState.ALERT_MODERATE,
        SystemState.ALERT_SEVERE,
        SystemState.ALCOHOL_DETECTED
    ],
    "alert_manager": [],  # Consumer only - no state setting permissions
    "network_connector": [SystemState.SYSTEM_ERROR],
    "https_client": [SystemState.SYSTEM_ERROR],
    "bio_monitor": [SystemState.SYSTEM_ERROR],
    "env_monitor": [SystemState.SYSTEM_ERROR],
    "system_monitor": [  # Special service for system-level states
        SystemState.SYSTEM_ERROR,
        SystemState.SYSTEM_CRASHED,
        SystemState.SCANNING  # Can reset to scanning for recovery
    ],
    "state_tester": [  # Testing utility - can set all states for manual testing
        SystemState.SCANNING,
        SystemState.INTRUDER_DETECTED,
        SystemState.MONITORING_ACTIVE,
        SystemState.ALERT_MILD,
        SystemState.ALERT_MODERATE,
        SystemState.ALERT_SEVERE,
        SystemState.ALCOHOL_DETECTED,
        SystemState.SYSTEM_ERROR,
        SystemState.SYSTEM_CRASHED
    ],
    "quick_test": [  # Quick test utility - can set all states
        SystemState.SCANNING,
        SystemState.INTRUDER_DETECTED,
        SystemState.MONITORING_ACTIVE,
        SystemState.ALERT_MILD,
        SystemState.ALERT_MODERATE,
        SystemState.ALERT_SEVERE,
        SystemState.ALCOHOL_DETECTED,
        SystemState.SYSTEM_ERROR,
        SystemState.SYSTEM_CRASHED
    ]
}


@dataclass
class SystemStatusMessage:
    """System status message data structure"""
    message: str
    priority: str = "medium"  # "low", "medium", "high", "critical"
    timestamp: float = 0.0
    service: str = ""


@dataclass(frozen=True)
class StateSnapshot:
    """Immutable state snapshot for thread-safe state management"""
    state: SystemState
    message: str
    pilot_username: Optional[str]
    timestamp: float
    service: str
    data: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        return {
            'state': self.state.value,
            'message': self.message,
            'pilot_username': self.pilot_username,
            'timestamp': self.timestamp,
            'service': self.service,
            'data': self.data
        }


class ThreadSafeStateManager:
    """Thread-safe state manager with enhanced validation and error handling"""
    
    def __init__(self, max_history: int = 1000, enforce_permissions: bool = True):
        self._lock = threading.RLock()
        self._current_state: Optional[StateSnapshot] = None
        self._state_history: deque = deque(maxlen=max_history)
        self._state_callbacks: List[Callable[[StateSnapshot], None]] = []
        self._enforce_permissions = enforce_permissions
        self._callback_failures = {}  # Track callback failure counts
    
    def get_current_state(self) -> Optional[StateSnapshot]:
        """Get current state snapshot (thread-safe)"""
        with self._lock:
            return self._current_state
    
    def get_current_system_state(self) -> Optional[SystemState]:
        """Get current SystemState enum value"""
        snapshot = self.get_current_state()
        return snapshot.state if snapshot else None
    
    def transition_state(self, state: SystemState, message: str, service: str,
                        pilot_username: Optional[str] = None, data: Optional[Dict[str, Any]] = None,
                        force: bool = False) -> StateSnapshot:
        """Safely transition to new state with enhanced validation"""
        with self._lock:
            # Check service permissions
            if self._enforce_permissions and not force:
                self._validate_service_permission(service, state)
            
            # Validate state transition
            if not self._is_valid_transition(self._current_state, state):
                if not force:  # Allow forced transitions for emergency recovery
                    current_state_name = self._current_state.state.value if self._current_state else 'None'
                    from .exceptions import InvalidStateTransitionError
                    raise InvalidStateTransitionError(
                        f"Invalid state transition from {current_state_name} to {state.value} "
                        f"requested by service '{service}'"
                    )
                else:
                    logger.warning(f"FORCED state transition from {current_state_name} to {state.value} by {service}")
            
            snapshot = StateSnapshot(
                state=state,
                message=message,
                pilot_username=pilot_username,
                timestamp=time.time(),
                service=service,
                data=data or {}
            )
            
            # Log state transition
            old_state = self._current_state.state.value if self._current_state else 'None'
            logger.info(f"State transition: {old_state} -> {state.value} by {service}")
            
            self._current_state = snapshot
            self._state_history.append(snapshot)
            
            # Notify callbacks with enhanced error handling
            self._notify_callbacks(snapshot)
            
            return snapshot
    
    def _validate_service_permission(self, service: str, state: SystemState):
        """Validate that service has permission to set this state"""
        allowed_states = SERVICE_STATE_PERMISSIONS.get(service, [])
        if state not in allowed_states:
            from .exceptions import StatePermissionError
            raise StatePermissionError(
                f"Service '{service}' does not have permission to set state '{state.value}'. "
                f"Allowed states: {[s.value for s in allowed_states]}"
            )
    
    def _notify_callbacks(self, snapshot: StateSnapshot):
        """Notify callbacks with robust error handling"""
        failed_callbacks = []
        
        for callback in self._state_callbacks[:]:
            try:
                callback(snapshot)
            except Exception as e:
                callback_name = getattr(callback, '__name__', str(callback))
                logger.error(f"State callback '{callback_name}' failed: {e}")
                
                # Track callback failures
                if callback not in self._callback_failures:
                    self._callback_failures[callback] = 0
                self._callback_failures[callback] += 1
                
                # Remove callbacks that fail repeatedly (after 5 failures)
                if self._callback_failures[callback] >= 5:
                    logger.error(f"Removing callback '{callback_name}' after {self._callback_failures[callback]} failures")
                    failed_callbacks.append(callback)
        
        # Remove failed callbacks
        for callback in failed_callbacks:
            try:
                self._state_callbacks.remove(callback)
                del self._callback_failures[callback]
            except (ValueError, KeyError):
                pass
    
    def _is_valid_transition(self, current: Optional[StateSnapshot], new_state: SystemState) -> bool:
        """Validate state transitions to prevent invalid states"""
        if current is None:
            return True  # Any state is valid from None

        # Allow transitioning to the same state (idempotent operation)
        if current.state == new_state:
            return True

        # Define valid state transitions for aviation safety
        valid_transitions = {
            SystemState.SCANNING: [SystemState.MONITORING_ACTIVE, SystemState.INTRUDER_DETECTED, SystemState.ALCOHOL_DETECTED, SystemState.SYSTEM_ERROR],
            SystemState.INTRUDER_DETECTED: [SystemState.SCANNING, SystemState.ALCOHOL_DETECTED, SystemState.SYSTEM_ERROR],
            SystemState.MONITORING_ACTIVE: [SystemState.ALERT_MILD, SystemState.ALCOHOL_DETECTED, SystemState.SCANNING, SystemState.SYSTEM_ERROR],
            SystemState.ALERT_MILD: [SystemState.ALERT_MODERATE, SystemState.MONITORING_ACTIVE, SystemState.ALCOHOL_DETECTED, SystemState.SYSTEM_ERROR],
            SystemState.ALERT_MODERATE: [SystemState.ALERT_SEVERE, SystemState.ALERT_MILD, SystemState.MONITORING_ACTIVE, SystemState.ALCOHOL_DETECTED, SystemState.SYSTEM_ERROR],
            SystemState.ALERT_SEVERE: [SystemState.ALERT_MODERATE, SystemState.MONITORING_ACTIVE, SystemState.ALCOHOL_DETECTED, SystemState.SYSTEM_ERROR, SystemState.SYSTEM_CRASHED],
            SystemState.ALCOHOL_DETECTED: [SystemState.MONITORING_ACTIVE, SystemState.ALERT_MILD, SystemState.ALERT_MODERATE, SystemState.ALERT_SEVERE, SystemState.SYSTEM_ERROR],  # Can transition back to any operational state
            SystemState.SYSTEM_ERROR: [SystemState.SCANNING, SystemState.SYSTEM_CRASHED],
            SystemState.SYSTEM_CRASHED: [SystemState.SCANNING]  # Recovery possible
        }

        return new_state in valid_transitions.get(current.state, [])
    
    def add_state_callback(self, callback: Callable[[StateSnapshot], None]):
        """Add callback for state changes"""
        with self._lock:
            if callback not in self._state_callbacks:
                self._state_callbacks.append(callback)
    
    def remove_state_callback(self, callback: Callable[[StateSnapshot], None]):
        """Remove state change callback"""
        with self._lock:
            if callback in self._state_callbacks:
                self._state_callbacks.remove(callback)
    
    def get_state_history(self, limit: Optional[int] = None) -> List[StateSnapshot]:
        """Get state history (thread-safe)"""
        with self._lock:
            history = list(self._state_history)
            return history[-limit:] if limit else history
    
    def clear_history(self):
        """Clear state history (for testing)"""
        with self._lock:
            self._state_history.clear()
    
    def set_permission_enforcement(self, enforce: bool):
        """Enable or disable permission enforcement (for testing/emergency)"""
        with self._lock:
            self._enforce_permissions = enforce
            if enforce:
                logger.info("State permission enforcement ENABLED")
            else:
                logger.warning("State permission enforcement DISABLED")
    
    def get_callback_stats(self) -> Dict[str, int]:
        """Get statistics about callback failures"""
        with self._lock:
            return {
                getattr(callback, '__name__', str(callback)): failures 
                for callback, failures in self._callback_failures.items()
            }
    
    def force_state_transition(self, state: SystemState, message: str, service: str,
                             pilot_username: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> StateSnapshot:
        """Force state transition bypassing all validation (emergency use only)"""
        logger.warning(f"EMERGENCY: Forcing state transition to {state.value} by {service}")
        return self.transition_state(state, message, service, pilot_username, data, force=True)


# Global state manager instance - properly thread-safe
_global_state_manager = ThreadSafeStateManager()


# Utility functions for state management
def get_state_manager() -> ThreadSafeStateManager:
    """Get the global state manager instance"""
    return _global_state_manager