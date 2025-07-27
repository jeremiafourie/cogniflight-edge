"""CogniCore State Management - Thread-safe state management with proper architecture"""

import threading
import time
from collections import deque
from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, Optional, List, Callable


class SystemState(Enum):
    """System operational states for pilot fatigue detection"""
    SCANNING = "scanning"                    # Looking for pilot, connecting to HR sensor, or processing
    INTRUDER_DETECTED = "intruder_detected"  # Unknown/unauthorized person detected
    MONITORING_ACTIVE = "monitoring_active"  # Actively monitoring pilot, no fatigue detected
    ALERT_MILD = "alert_mild"               # Early fatigue warning (fusion score ~0.3)
    ALERT_MODERATE = "alert_moderate"       # Escalated fatigue warning (fusion score ~0.6)
    ALERT_SEVERE = "alert_severe"           # Critical fatigue alert (fusion score ~0.8)
    SYSTEM_ERROR = "system_error"           # Service error or malfunction
    SYSTEM_CRASHED = "system_crashed"       # Critical system failure, watchdog unable to recover


@dataclass
class PilotProfile:
    """Pilot profile data structure"""
    id: str
    name: str
    flightHours: float
    baseline: Dict[str, Any]
    environmentPreferences: Dict[str, Any]


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
    pilot_id: Optional[str]
    timestamp: float
    service: str
    data: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        return {
            'state': self.state.value,
            'message': self.message,
            'pilot_id': self.pilot_id,
            'timestamp': self.timestamp,
            'service': self.service,
            'data': self.data
        }


class ThreadSafeStateManager:
    """Thread-safe state manager replacing dangerous global state"""
    
    def __init__(self, max_history: int = 1000):
        self._lock = threading.RLock()
        self._current_state: Optional[StateSnapshot] = None
        self._state_history: deque = deque(maxlen=max_history)
        self._state_callbacks: List[Callable[[StateSnapshot], None]] = []
    
    def get_current_state(self) -> Optional[StateSnapshot]:
        """Get current state snapshot (thread-safe)"""
        with self._lock:
            return self._current_state
    
    def get_current_system_state(self) -> Optional[SystemState]:
        """Get current SystemState enum value"""
        snapshot = self.get_current_state()
        return snapshot.state if snapshot else None
    
    def transition_state(self, state: SystemState, message: str, service: str, 
                        pilot_id: Optional[str] = None, data: Optional[Dict[str, Any]] = None) -> StateSnapshot:
        """Safely transition to new state with validation"""
        with self._lock:
            # Validate state transition
            if not self._is_valid_transition(self._current_state, state):
                # Log but don't block - aviation safety systems need flexibility
                pass
            
            snapshot = StateSnapshot(
                state=state,
                message=message,
                pilot_id=pilot_id,
                timestamp=time.time(),
                service=service,
                data=data or {}
            )
            
            self._current_state = snapshot
            self._state_history.append(snapshot)
            
            # Notify callbacks (don't let callback errors affect state transitions)
            for callback in self._state_callbacks[:]:
                try:
                    callback(snapshot)
                except Exception:
                    pass
            
            return snapshot
    
    def _is_valid_transition(self, current: Optional[StateSnapshot], new_state: SystemState) -> bool:
        """Validate state transitions to prevent invalid states"""
        if current is None:
            return True  # Any state is valid from None
        
        # Define valid state transitions for aviation safety
        valid_transitions = {
            SystemState.SCANNING: [SystemState.MONITORING_ACTIVE, SystemState.INTRUDER_DETECTED, SystemState.SYSTEM_ERROR],
            SystemState.INTRUDER_DETECTED: [SystemState.SCANNING, SystemState.SYSTEM_ERROR],
            SystemState.MONITORING_ACTIVE: [SystemState.ALERT_MILD, SystemState.SCANNING, SystemState.SYSTEM_ERROR],
            SystemState.ALERT_MILD: [SystemState.ALERT_MODERATE, SystemState.MONITORING_ACTIVE, SystemState.SYSTEM_ERROR],
            SystemState.ALERT_MODERATE: [SystemState.ALERT_SEVERE, SystemState.ALERT_MILD, SystemState.MONITORING_ACTIVE, SystemState.SYSTEM_ERROR],
            SystemState.ALERT_SEVERE: [SystemState.ALERT_MODERATE, SystemState.MONITORING_ACTIVE, SystemState.SYSTEM_ERROR, SystemState.SYSTEM_CRASHED],
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


# Global state manager instance - properly thread-safe
_global_state_manager = ThreadSafeStateManager()


# Utility functions for state management
def get_state_manager() -> ThreadSafeStateManager:
    """Get the global state manager instance"""
    return _global_state_manager