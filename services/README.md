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

#### **Alert Manager** (`alert_manager/`) - Pure Reactive Control

- **Function**: RGB LED and GPIO control via system state subscriptions only
- **Input**: System state changes only (no other data sources)
- **Output**: RGB LED color states and GPIO device control
- **Hardware**: RGB LED, buzzer, and vibrator motor
- **Design**: No polling, purely event-driven hardware control

#### **Vision Processor** (`vision_processor/`) - Unified Authentication & Monitoring

- **Function**: Dual-mode service for pilot authentication and fatigue monitoring in single camera stream
- **Modes**:
  - Authentication: Face recognition when no pilot active (InsightFace)
  - Monitoring: Real-time fatigue analysis when pilot authenticated (MediaPipe)
- **Input**: Camera frames (640x360 @ 30fps), pilot embeddings from Redis
- **Output**: Authentication requests, EAR/MAR scores, microsleep detection, face tracking
- **Technology**: InsightFace buffalo_s, MediaPipe face mesh, OpenCV, rpicam-vid
- **Design**: Single camera ownership, automatic mode switching between authentication and monitoring, zero handover delays
- **Deployment**: Primary device (Pi 5)

#### **Predictor** (`predictor/`) - Integrated Data Fusion & Analysis

- **Function**: Real-time data fusion and fatigue stage prediction with pilot-specific thresholds
- **Input**: Vision data (EAR/MAR), heart rate data (when available), pilot profiles
- **Output**: Fusion scores, fatigue stage classifications, system state updates
- **Algorithm**: EAR-based fatigue (50%) + closure duration (30%) + microsleeps (15%) + blink patterns (5%) + optional HR (25%) with 2-sample sliding window
- **Processing**: 20Hz continuous fusion (0.05s sleep) with personalized sensitivity settings

### Identification and Profile Services

#### **Go Client** (`go_client/`) - Reactive Profile Management

- **Function**: Pilot profile fetching with persistent storage
- **Input**: Pilot ID requests from vision processor
- **Output**: Pilot profiles published to CogniCore, face embeddings to Redis
- **Features**: Cloud API integration with persistent Redis storage, reactive profile loading
- **Technology**: Go implementation with efficient concurrent processing

### Monitoring Services

#### **Bio Monitor** (`bio_monitor/`) - Dual Sensor Biometric Monitoring

- **Function**: Heart rate monitoring (BLE) AND alcohol detection (GPIO sensor)
- **Input**: BLE heart rate sensor data (XOSS X2), MQ3 alcohol sensor via GPIO 18
- **Output**: Real-time heart rate with HRV/RMSSD metrics, immediate alcohol detection events
- **Technology**: Bleak async BLE, gpiozero GPIO library, advanced HRV analysis
- **Dual Design**:
  - **HR Monitoring**: BLE connection to XOSS X2 with baseline tracking and stress index
  - **Alcohol Detection**: Continuous GPIO monitoring (30s warmup, 2s debounce, inverted logic)
- **Data Publishing**: `hr_sensor` hash for HR data, `alcohol_detected` hash for instant alcohol events
- **Deployment**: Primary device (Pi 5) for direct BLE access to pilot

#### **Environment Monitor** (`env_monitor/`) - Guaranteed Environmental Monitoring

- **Function**: Robust environmental sensor data collection with guaranteed data publishing
- **Input**: DHT22 temperature/humidity sensor, GY-91 IMU (MPU9250 + BMP280)
- **Output**: Environmental telemetry data via CogniCore every 1 second (always)
- **Hardware**: DHT22 on GPIO pin 6, GY-91 on I2C Bus 1 with 1Hz sampling (1-second intervals)
- **Design**: Continuous operation with stale data fallback for 100% data availability
- **Deployment**: Secondary device (Pi 4)

#### **Motion Controller** (`motion_controller/`) - Servo-Based Camera Tracking

- **Function**: Automated camera positioning system that tracks pilot head movements
- **Input**: Face detection data from vision_processor (head position coordinates)
- **Output**: Servo motor control signals for pan/tilt camera positioning
- **Hardware**: PCA9685 PWM driver with dual SG90 servos (I2C Bus 1)
- **Features**: Smooth motion interpolation, angle-to-pulse width conversion, safety limits
- **Design**: Translates head position into servo movements for optimal camera angles
- **Deployment**: Primary device (Pi 5)

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
# Reactive Publisher (Vision Processor)
core = CogniCore("vision_processor")
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

# Pilot Activation Subscriber (Bio Monitor)
def on_pilot_change(hash_name, data):
    pilot_id = data.get('pilot_id') if data else None
    is_active = data.get('active', False) if data else False

    if pilot_id and is_active and not bio_monitor_running:
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

# Add project root to path for imports (deployment flexible)
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

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

- **Camera Services**: Raspberry Pi camera module (Primary device - Pi 5)
- **Alert Services**: GPIO hardware control - RGB LED, buzzer, vibrator (Secondary device - Pi 4)
- **Environmental Sensors**: DHT22 (GPIO 6), GY-91 IMU (I2C Bus 1) (Secondary device - Pi 4)
- **BLE Services**: Bluetooth Low Energy for XOSS X2 HR monitor (Primary device - Pi 5)
- **Alcohol Detection**: MQ3 sensor module via GPIO 18 (inverted logic, 5V powered) (Primary device - Pi 5)
- **Motion Control**: PCA9685 PWM driver (I2C Bus 1) with SG90 servos (Primary device - Pi 5)

### Software Dependencies

- **CogniCore**: Redis-based communication (all services)
- **Common Utilities**: Shared configuration and utilities
- **Service-Specific**: Libraries for specialized functions

## Performance Characteristics

### Reactive Real-time Services

- **Vision Processor**:
  - Authentication mode: 6fps face recognition (every 5th frame at 30fps)
  - Monitoring mode: 30fps fatigue analysis (every frame)
  - Automatic mode switching based on pilot authentication status
- **Predictor**: 10Hz continuous data fusion and analysis
- **Alert Manager**: <50ms state change response (GPIO hardware control)
- **Bio Monitor**: Real-time BLE streaming with HRV/RMSSD analysis
- **Network Connector**: Event-driven telemetry with 2-second throttling (0.5Hz max)

### On-Demand Services

- **Go Client**: Reactive profile fetching on pilot detection
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
