# Services - Microservice Architecture

The `services` directory contains all the microservices that make up the CogniFlight Edge system. Each service is designed as an independent, specialized component that communicates with other services through the CogniCore Redis-based communication system.

## Reactive Architecture Overview

### Reactive Microservice Design Principles

- **Event-Driven Processing**: Services respond to data changes, not polling
- **Resource Efficiency**: Components only active when needed (pilot present)
- **Instant Response**: Sub-second reaction to system events via Redis keyspace notifications
- **Independent Operation**: Services can be developed, deployed, and scaled independently
- **Fault Isolation**: Service failures don't cascade to other components
- **Smart Resource Management**: Camera/sensors shared intelligently between services

### Reactive Communication Pattern

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Service A     │    │   CogniCore     │    │   Service B     │
│                 │    │ (Redis + K.N.)  │    │                 │
│  publish_data() │───▶│  Hash Storage   │◀──│  subscribe()    │
│                 │    │  Notifications  │    │  ↓ Instant      │
│                 │    │  ↓ Keyspace     │    │  Callback       │
│                 │    │  Event Trigger  │    │  Execution      │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Service Inventory

### Core Processing Services

#### **Alert Manager** (`alert_manager/`) - Pure Reactive Display

- **Function**: LCD display management via system state subscriptions only
- **Input**: System state changes only (no other data sources)
- **Output**: 16x2 LCD display with message deduplication
- **Hardware**: I2C LCD with PCF8574 backpack
- **Design**: No polling, purely event-driven LCD updates

#### **Vision Processing** (`vision_processing/`) - Reactive Camera Management

- **Function**: Real-time facial landmark analysis when pilot is present
- **Input**: Camera frames (640x360 @ 30fps), pilot presence subscriptions
- **Output**: EAR/MAR scores, blink/yawn detection
- **Technology**: MediaPipe, OpenCV, rpicam-vid
- **Reactive Design**: Camera only runs when pilot detected, automatic resource cleanup

#### **Predictor** (`predictor/`) - Integrated Data Fusion & Analysis

- **Function**: Real-time data fusion and fatigue stage prediction with pilot-specific thresholds
- **Input**: Vision data (EAR/MAR), heart rate data (when available), pilot profiles
- **Output**: Fusion scores, fatigue stage classifications, system state updates
- **Algorithm**: EAR-based fatigue (50%) + closure duration (30%) + microsleeps (15%) + blink patterns (5%) + optional HR (25%) with 2-sample sliding window
- **Processing**: 20Hz continuous fusion (0.05s sleep) with personalized sensitivity settings

### Identification and Profile Services

#### **Face Recognition** (`face_recognition/`) - Camera Owner and Pilot Detection

- **Function**: Pilot identification using facial recognition, camera resource management
- **Input**: Camera frames (640x360 @ 15fps), pilot face embeddings
- **Output**: Pilot identification requests, security alerts, camera handoff
- **Technology**: InsightFace buffalo_s model, processes every 5th frame (3fps processing)
- **Resource Management**: Releases camera to vision processing when pilot active

#### **HTTPS Client** (`https_client/`) - Reactive Profile Management

- **Function**: Pilot profile fetching with persistent storage
- **Input**: Pilot ID requests from face recognition
- **Output**: Pilot profiles published to CogniCore, persistent storage
- **Features**: Cloud API integration with persistent Redis storage, reactive profile loading

### Monitoring Services

#### **HR Monitor** (`hr_monitor/`) - Reactive BLE Connection

- **Function**: Heart rate monitoring activated only when pilot is present
- **Input**: Pilot presence subscriptions, BLE heart rate sensor data
- **Output**: Real-time heart rate measurements when pilot active
- **Technology**: Bleak async BLE library with reactive connection management
- **Reactive Design**: BLE connection only established when pilot detected, automatic cleanup

#### **Environment Monitor** (`env_monitor/`) - Guaranteed Environmental Monitoring

- **Function**: Robust environmental sensor data collection with guaranteed data publishing
- **Input**: DHT22 temperature and humidity sensor with 15-attempt retry logic
- **Output**: Environmental telemetry data via CogniCore every 2 seconds (always)
- **Hardware**: DHT22 on GPIO pin 4 with 0.5Hz sampling (2-second intervals)
- **Design**: Continuous operation with stale data fallback for 100% data availability

### Data Management Services

#### **Network Connector** (`network_connector/`) - Event-Driven Telemetry

- **Function**: Smart telemetry transmission with throttling and Redis outbox
- **Input**: Vision/HR data changes, system state changes (via subscriptions)
- **Output**: MQTT telemetry with 2-second throttling, Redis outbox for offline storage
- **Features**: Event-driven design prevents 30fps spam, comprehensive system telemetry
- **Intelligence**: Throttled data events, immediate state change transmission

## Service Communication Patterns

### Reactive Publisher-Subscriber Pattern

```python
# Reactive Publisher (Vision Processing)
core = CogniCore("vision_processing")
# Only publishes when pilot is active
if self.pilot_profile:
    core.publish_data("vision", {"avg_ear": 0.25, "mar": 0.05})

# Reactive Subscriber (Network Connector with Throttling)
core = CogniCore("network_connector")
last_telemetry = {"vision": 0, "hr": 0}

def on_vision_data(hash_name, data):
    if time.time() - last_telemetry["vision"] > 2:  # 2-second throttle
        send_comprehensive_telemetry()
        last_telemetry["vision"] = time.time()

core.subscribe_to_data("vision", on_vision_data)

# Pilot Activation Subscriber (HR Monitor)
def on_pilot_change(hash_name, data):
    pilot_id = data.get('pilot_id') if data else None
    is_active = data.get('active', False) if data else False

    if pilot_id and is_active and not hr_monitor_running:
        start_ble_connection()  # Immediate activation

# Subscribe to all pilot changes
existing_pilots = core.list_pilots()
for pilot_id in existing_pilots:
    core.subscribe_to_data(f"pilot:{pilot_id}", on_pilot_change)
```

### State Management Pattern

```python
# State Change Example
core.set_system_state(
    SystemState.PILOT_IDENTIFIED,
    pilot_id="pilot_001",
    data={"confidence": 0.95}
)

# State Monitoring
def on_state_change(state_data):
    if state_data['state'] == 'monitoring_active':
        start_processing()

core.subscribe_to_state_changes(on_state_change)
```

## Service Lifecycle

### Startup Sequence

1. **CogniCore Connection**: Connect to Redis communication hub
2. **Hardware Initialization**: Initialize sensors, cameras, displays
3. **Service Registration**: Register with watchdog monitoring
4. **Data Subscriptions**: Subscribe to required data streams
5. **Processing Start**: Begin main service loop

### Runtime Operation

1. **Data Processing**: Core service functionality
2. **Systemd Notifications**: Service ready and watchdog notifications
3. **Error Handling**: Graceful error recovery and logging
4. **Performance Monitoring**: Resource usage monitoring

### Shutdown Sequence

1. **Graceful Shutdown**: Clean service termination
2. **Resource Cleanup**: Hardware and connection cleanup
3. **Data Persistence**: Ensure critical data is saved
4. **Service Deregistration**: Clean exit from monitoring

## Common Service Patterns

### Service Template Structure

```python
#!/usr/bin/env python3

import sys
import time
import systemd.daemon
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from CogniCore import CogniCore

def main():
    # Initialize CogniCore (logging is handled automatically)
    core = CogniCore("service_name")
    logger = core.get_logger("service_name")

    # Service-specific initialization
    initialize_service()

    # Notify systemd that service is ready
    systemd.daemon.notify('READY=1')

    # Main processing loop
    while True:
        try:
            # Core service work
            process_data()

            # Notify systemd watchdog
            systemd.daemon.notify('WATCHDOG=1')

        except Exception as e:
            logger.error(f"Service error: {e}")

        time.sleep(service_interval)

if __name__ == "__main__":
    main()
```

### Error Handling Pattern

```python
def robust_service_operation():
    try:
        # Service operation
        result = perform_operation()

        # Publish result via CogniCore
        core.publish_data("service_result", result)

    except HardwareError as e:
        logger.error(f"Hardware error: {e}")
        core.send_alert(f"Hardware failure in {service_name}", "high")

    except CommunicationError as e:
        logger.error(f"Communication error: {e}")
        # Continue with cached/default data

    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        # Graceful degradation
```

## Service Dependencies

### Hardware Dependencies

- **Camera Services**: Raspberry Pi camera module
- **Display Services**: I2C LCD display
- **Sensor Services**: GPIO-connected sensors
- **BLE Services**: Bluetooth Low Energy capability

### Software Dependencies

- **CogniCore**: Redis-based communication (all services)
- **Common Utilities**: Shared configuration and utilities
- **Service-Specific**: Libraries for specialized functions

## Performance Characteristics

### Reactive Real-time Services

- **Vision Processing**: 30fps when pilot active (0fps when idle)
- **Predictor**: 10Hz continuous data fusion and analysis
- **Alert Manager**: <50ms state change response (LCD only)
- **HR Monitor**: Real-time BLE streaming when pilot present
- **Network Connector**: Event-driven telemetry (max 0.5Hz due to throttling)

### On-Demand Services

- **Face Recognition**: 3fps processing (15fps camera, every 5th frame)
- **HTTPS Client**: Reactive profile fetching on pilot detection
- **Predictor**: 2-second interval sliding window analysis

### Resource Usage

- **Memory**: Each service typically <50MB RAM
- **CPU**: Optimized for single-core ARM processors
- **I/O**: Minimal disk I/O except logging services
- **Network**: Minimal bandwidth requirements

## Deployment

### Service Installation

Each service includes:

- **Python Script**: Main service implementation
- **Requirements File**: Python dependencies
- **Systemd Unit**: Service configuration
- **Documentation**: Service-specific documentation

### Service Management

```bash
# Start service
sudo systemctl start service_name.service

# Enable auto-start
sudo systemctl enable service_name.service

# Check status
sudo systemctl status service_name.service

# View logs
sudo journalctl -u service_name.service -f
```

### Configuration

- **CogniCore Settings**: Redis connection parameters
- **Hardware Settings**: GPIO pins, I2C addresses
- **Performance Tuning**: Processing rates, buffer sizes
- **Alert Thresholds**: Service-specific thresholds

This microservice architecture enables scalable, maintainable, and robust operation of the CogniFlight Edge system with clear separation of concerns and reliable inter-service communication.
