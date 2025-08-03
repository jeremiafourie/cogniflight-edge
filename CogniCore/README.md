# CogniCore - Thread-Safe Redis Communication Library

CogniCore is a thread-safe Redis communication library designed for Cogniflight Edge. It provides centralized state management, real-time data sharing, and robust inter-service communication through Redis pub/sub with connection pooling and proper resource management.

## Core Features

✅ **Thread-Safe State Management** - Single global state with proper synchronization  
✅ **Redis Connection Pooling** - Optimized resource management and performance  
✅ **Real-Time Communication** - Redis pub/sub with keyspace notifications  
✅ **Configuration Management** - Environment variables with sensible defaults  
✅ **Production Ready** - Proper error handling, logging, and cleanup  
✅ **Aviation Safety** - State transition validation for safety-critical systems

## Quick Start

```python
from CogniCore import CogniCore, SystemState

# Initialize with automatic configuration
core = CogniCore("my_service")

# Publish data with automatic timestamping
core.publish_data("sensor_readings", {
    "temperature": 23.5,
    "humidity": 45.2
})

# Get data from another service
data = core.get_data("sensor_readings")
if data:
    print(f"Temperature: {data['temperature']}°C")
    print(f"Published by: {data['service']} at {data['timestamp']}")

# Thread-safe system state management
core.set_system_state(SystemState.MONITORING_ACTIVE, "System operational")
current_state = core.get_system_state()
print(f"Current state: {current_state}")

# Real-time subscriptions
def handle_update(channel, data):
    print(f"Real-time update on {channel}: {data}")

core.subscribe_to_data("sensor_readings", handle_update)

# Proper cleanup
core.shutdown()
```

## Thread-Safe State Management

CogniCore provides a **single global state** for our entire system with proper thread safety:

```python
from CogniCore.state import get_state_manager, StateSnapshot

# Get the global state manager
state_mgr = get_state_manager()

# Thread-safe state access
current_snapshot = state_mgr.get_current_state()
if current_snapshot:
    print(f"State: {current_snapshot.state}")
    print(f"Message: {current_snapshot.message}")
    print(f"Service: {current_snapshot.service}")
    print(f"Pilot: {current_snapshot.pilot_id}")

# State history tracking
history = state_mgr.get_state_history(limit=10)
for snapshot in history:
    print(f"{snapshot.timestamp}: {snapshot.state} by {snapshot.service}")
```

## Configuration Management

CogniCore supports flexible configuration through environment variables:

```bash
# Environment variables
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0
export REDIS_TIMEOUT=5
export REDIS_TTL=300
export STATE_HISTORY_LIMIT=1000
export REDIS_HEALTH_CHECK=30
```

```python
# Configuration in code
core = CogniCore(
    service_name="my_service",
    redis_host="192.168.1.100",  # Override env vars
    redis_port=6380,
    connection_timeout=10
)
```

## API Reference

### Core Initialization

```python
CogniCore(service_name: str,
          redis_host: Optional[str] = None,
          redis_port: Optional[int] = None,
          redis_db: Optional[int] = None,
          connection_timeout: Optional[int] = None)
```

- **service_name**: Unique identifier for this service
- **redis_host**: Redis host (default: localhost or REDIS_HOST env var)
- **redis_port**: Redis port (default: 6379 or REDIS_PORT env var)
- **redis_db**: Redis database (default: 0 or REDIS_DB env var)
- **connection_timeout**: Connection timeout (default: 5 or REDIS_TIMEOUT env var)

### Data Operations

```python
# Publish data with automatic metadata
core.publish_data(hash_name: str, data: Dict[str, Any])

# Retrieve latest data
core.get_data(hash_name: str) -> Optional[Dict[str, Any]]

# Real-time subscriptions
core.subscribe_to_data(hash_name: str, callback: Callable[[str, Dict], None])
core.unsubscribe_from_data(hash_name: str, callback: Callable)
```

### Thread-Safe State Management

```python
# Set global system state (thread-safe)
core.set_system_state(state: SystemState, message: str,
                     pilot_id: Optional[str] = None,
                     data: Optional[Dict[str, Any]] = None)

# Get current state (thread-safe)
core.get_system_state() -> Optional[SystemState]

# Get detailed state snapshot
core.get_system_state_snapshot() -> Optional[StateSnapshot]

# Subscribe to state changes
core.subscribe_to_state_changes(callback: Callable[[Dict], None])
```

### Pilot Profile Management

CogniCore uses a simplified pilot system with `pilot:{pilot_id}` keys and active flags:

```python
# Store and activate pilot profile
from CogniCore.state import PilotProfile

profile = PilotProfile(
    id="1234567",
    name="John Doe",
    flightHours=2500.0,
    baseline={
        "heart_rate": 72,
        "heart_rate_variability": 50
    },
    environmentPreferences={
        "cabinTemperaturePreferences": {
            "optimalTemperature": 22,
            "toleranceRange": 3
        },
        "noiseSensitivity": "medium",
        "lightSensitivity": "low"
    }
)

# Store profile and optionally activate (default: activate=True)
core.set_pilot_profile(profile, activate=True)

# Pilot activation management
core.set_pilot_active("1234567", active=True)    # Activate pilot
core.set_pilot_active("1234567", active=False)   # Deactivate pilot
core.deactivate_all_pilots()                     # Deactivate all (face recognition startup)

# Retrieve pilot information
active_pilot_id = core.get_active_pilot()        # Get active pilot ID
profile = core.get_pilot_profile("1234567")      # Get specific pilot profile
active_profile = core.get_active_pilot_profile() # Get active pilot's full profile
all_pilot_ids = core.list_pilots()               # List all pilot IDs

# Subscribe to pilot changes for reactive processing
def on_pilot_change(hash_name, data):
    pilot_id = data.get('pilot_id') if data else None
    is_active = data.get('active', False) if data else False

    if pilot_id and is_active:
        print(f"Pilot {pilot_id} activated")
    elif pilot_id and not is_active:
        print(f"Pilot {pilot_id} deactivated")

core.subscribe_to_data("pilot:1234567", on_pilot_change)
```

**Key Features:**

- **Single Data Structure**: Uses `pilot:{pilot_id}` keys with active flag - no separate cache needed
- **Persistent Storage**: Pilot profiles are persistent and survive service restarts
- **Reactive Updates**: Services subscribe to pilot changes for camera handover
- **Keyspace Notifications**: Maintains pilot_id in key for proper subscription notifications

### Utilities

```python
# System monitoring
core.is_connected() -> bool
core.get_stats() -> Dict[str, Any]


# Logging
logger = core.get_logger(name: Optional[str] = None) -> logging.Logger

# Cleanup
core.shutdown()  # Proper resource cleanup
```

## System States

Aviation safety states with validated transitions:

```python
class SystemState(Enum):
    SCANNING = "scanning"                    # Looking for pilot/sensors
    INTRUDER_DETECTED = "intruder_detected"  # Unauthorized person detected
    MONITORING_ACTIVE = "monitoring_active"  # Normal monitoring mode
    ALERT_MILD = "alert_mild"               # Early fatigue warning
    ALERT_MODERATE = "alert_moderate"       # Escalated warning
    ALERT_SEVERE = "alert_severe"           # Critical alert
    SYSTEM_ERROR = "system_error"           # Service malfunction
    SYSTEM_CRASHED = "system_crashed"       # Critical failure
```

**State Transition Validation**: The system enforces valid state transitions to prevent invalid states in safety-critical aviation applications.

## Error Handling

```python
from CogniCore.exceptions import CogniCoreError, ConnectionError, ValidationError

try:
    core = CogniCore("test_service")
    core.publish_data("test", {"value": 123})
    core.set_system_state(SystemState.MONITORING_ACTIVE, "All systems go")
except ValidationError as e:
    logger.error(f"Invalid input: {e}")
except ConnectionError as e:
    logger.error(f"Redis connection failed: {e}")
except CogniCoreError as e:
    logger.error(f"CogniCore error: {e}")
```

## Connection Pooling & Resource Management

CogniCore automatically manages Redis connections with:

- **Connection Pooling**: Reuses connections for better performance
- **Health Checks**: Automatic connection monitoring
- **Proper Cleanup**: Resource cleanup on shutdown
- **Error Recovery**: Automatic reconnection handling

```python
# Connection pooling is automatic
core = CogniCore("my_service")

# Check connection status
if core.is_connected():
    print("Redis connection healthy")

# Get connection statistics
stats = core.get_stats()
print(f"Memory used: {stats['memory_used']}")
print(f"Total keys: {stats['total_keys']}")

# Always cleanup when done
core.shutdown()
```

## Production Deployment

### Environment Setup

```bash
# Redis Configuration
export REDIS_HOST=redis.internal
export REDIS_PORT=6379
export REDIS_DB=0
export REDIS_TTL=300

# Performance Tuning
export REDIS_HEALTH_CHECK=30
export STATE_HISTORY_LIMIT=1000

# Systemd Integration (no manual setup required)
# Services use systemd.daemon for native watchdog functionality
```

### Service Integration

```python
# Production service template
import signal
import sys
import systemd.daemon
from CogniCore import CogniCore, SystemState

class MyService:
    def __init__(self):
        self.core = CogniCore("my_service")
        self.logger = self.core.get_logger()
        self.running = True

    def start(self):
        # Setup signal handlers
        signal.signal(signal.SIGTERM, self.shutdown)
        signal.signal(signal.SIGINT, self.shutdown)

        self.logger.info("Service starting...")

        # Notify systemd that service is ready
        systemd.daemon.notify('READY=1')

        try:
            # Main service loop
            while self.running:
                # Send systemd watchdog keepalive
                systemd.daemon.notify('WATCHDOG=1')

                # Your service logic here
                time.sleep(1)

        except Exception as e:
            self.logger.error(f"Service error: {e}")
            self.core.set_system_state(SystemState.SYSTEM_ERROR, f"Error: {e}")
        finally:
            self.cleanup()

    def shutdown(self, signum=None, frame=None):
        self.logger.info("Service shutting down...")
        self.running = False

    def cleanup(self):
        self.core.shutdown()
        self.logger.info("Service stopped")

if __name__ == "__main__":
    service = MyService()
    service.start()
```

## Requirements

- **Python 3.8+**
- **Redis Server 4.0+** with keyspace notifications enabled
- **redis-py >= 4.0.0**
- **systemd-python >= 235** for service integration

### Redis Configuration

```bash
# Enable keyspace notifications (required)
redis-cli CONFIG SET notify-keyspace-events Kh
```

## Architecture Benefits

### Thread Safety

- **Global State Manager**: Single source of truth with thread-safe operations
- **Connection Pooling**: Thread-safe Redis connection management
- **Immutable Snapshots**: State snapshots prevent race conditions

### Performance

- **Connection Pooling**: Reuses Redis connections for better performance
- **Efficient Serialization**: Optimized JSON handling for data storage
- **Configurable TTL**: Automatic cleanup of stale data

### Reliability

- **Error Recovery**: Automatic reconnection and error handling
- **Resource Cleanup**: Proper shutdown procedures prevent leaks
- **State Validation**: Aviation safety state transition validation

---

**Production-ready communication library for our Cogniflight embedded system.**
