# Cogniflight Edge

**CogniFlight Edge** is a real-time pilot fatigue detection and alerting system designed for aviation safety. The system utilizes computer vision, biometric monitoring, and machine learning to detect signs of pilot fatigue and provide immediate alerts through multiple channels.

This edge computing solution operates independently on embedded hardware (Raspberry Pi) with offline capabilities, making it suitable for aircraft environments where network connectivity may be intermittent.

## System Architecture

### Input Sources

- **Computer Vision**: Real-time facial landmark analysis using camera feed
- **Biometric Monitoring**: Heart rate data via Bluetooth Low Energy sensors
- **Environmental Sensors**: Temperature and humidity monitoring
- **Pilot Profiles**: Personalized thresholds and preferences

### Output Systems

- **LCD Display**: 16x2 character display for immediate visual alerts
- **Audio/Visual Alerts**: Multi-priority alert system
- **Data Logging**: Integrated Redis-based logging system
- **Telemetry**: MQTT-based cloud reporting (when connected)

## Core Technologies

- **CogniCore**: Redis-based communication library for service coordination
- **Computer Vision**: MediaPipe for facial landmark detection
- **Face Recognition**: InsightFace for pilot identification
- **Biometrics**: Bluetooth Low Energy heart rate monitoring
- **Edge Computing**: Raspberry Pi with optimized Python services

## System States

The system operates through well-defined states managed by CogniCore:

1. **SCANNING** - Looking for pilot, connecting to HR sensor, or processing
2. **INTRUDER_DETECTED** - Unknown/unauthorized person detected
3. **MONITORING_ACTIVE** - Actively monitoring pilot, no fatigue detected
4. **ALERT_MILD** - Early fatigue warning (fusion score ~0.3)
5. **ALERT_MODERATE** - Escalated fatigue warning (fusion score ~0.6)
6. **ALERT_SEVERE** - Critical fatigue alert (fusion score ~0.8)
7. **SYSTEM_ERROR** - Service error or malfunction
8. **SYSTEM_CRASHED** - Critical system failure, watchdog unable to recover

## Fatigue Detection Algorithm

### Vision Processing

- **Eye Aspect Ratio (EAR)**: Calculated from 6 eye landmarks per eye
- **Mouth Aspect Ratio (MAR)**: Calculated from 6 mouth landmarks
- **Real-time Analysis**: 30fps camera processing with MediaPipe

### Fatigue Classification

- **Active** (< 0.3): Normal alertness level
- **Mild** (0.3-0.6): Early fatigue indicators
- **Moderate** (0.6-0.8): Significant fatigue detected
- **Severe** (> 0.8): Critical fatigue requiring immediate attention

Thresholds are personalized based on pilot alert sensitivity preferences.

## Directory Structure

```
cogniflight-edge/
├── CogniCore/           # Redis-based communication library
├── docs/                # Project documentation
├── services/            # Microservices for specific functions
│   ├── alert_manager/   # LCD display and alert coordination
│   ├── env_monitor/     # Environmental sensor monitoring
│   ├── face_recognition/# Pilot identification system
│   ├── hr_monitor/      # Heart rate monitoring via BLE
│   ├── https_client/    # Pilot profile management
│   ├── network_connector/# Telemetry and cloud communication
│   ├── predictor/       # Data fusion, fatigue prediction and alerting
│   └── vision_processing/# Computer vision and landmark detection
└── scripts/             # Utility scripts and test programs
```

## Key Features

### Real-time Reactive Processing

- **30fps Vision Processing**: MediaPipe-based facial landmark detection (only when pilot active)
- **Event-Driven Fusion**: Immediate processing on vision/HR data changes
- **Instant Alerts**: Sub-second response via Redis keyspace notifications
- **Zero-Latency Activation**: Services respond to pilot changes within milliseconds
- **Robust Error Recovery**: Watchdog mechanisms prevent silent service failures
- **Camera Resource Management**: Automatic handover between face recognition and vision processing

### Offline Operation

- **Local Profile Caching**: Redis-based profile storage
- **Embedded Processing**: All computation performed on-device
- **Network-Optional**: Full functionality without internet connectivity

### Hardware Integration

- **Camera**: rpicam-vid integration with robust handover mechanisms
- **BLE Sensors**: Heart rate monitor support via Bleak
- **I2C Display**: 16x2 LCD with PCF8574 I2C backpack
- **Environmental Sensors**: DHT22 temperature/humidity monitoring
- **Resource Management**: Automatic camera resource coordination between services

### Personalization

- **Pilot Profiles**: Individual thresholds and preferences
- **Alert Sensitivity**: Adjustable detection thresholds (high/medium/low)
- **Medical Conditions**: Profile-based considerations
- **Device Pairing**: Associated BLE sensor MAC addresses

## Reactive Service Architecture

Each service operates as an independent systemd unit with **event-driven reactive design**:

- **CogniCore Subscriptions**: Redis keyspace notifications for immediate data changes
- **No Polling**: Services activate instantly when relevant data changes
- **Resource Efficiency**: Camera/sensors only active when pilot present
- **Systemd Watchdog**: Native systemd service monitoring and automatic restart
- **Error Handling**: Graceful degradation and recovery with systemd monitoring
- **Camera Handover**: Seamless transition between face recognition and vision processing
- **Robustness**: Native systemd failure detection and automatic recovery
- **Centralized Logging**: All events logged through CogniCore

### Key Reactive Features

- **Instant Activation**: Services start processing immediately when pilot detected
- **Automatic Cleanup**: Resources released when pilot leaves
- **Event Throttling**: Network telemetry throttled to prevent spam (2-second minimum)
- **Smart Scheduling**: Camera only runs during active monitoring
- **Fault Tolerance**: Watchdog mechanisms detect and recover from silent failures
- **Camera Coordination**: Proper resource timing prevents conflicts between services
- **Retry Logic**: Robust error recovery with exponential backoff

### Critical Flow Notes

- **HTTPS Client**: Sets pilot profile but does NOT automatically set `MONITORING_ACTIVE` state
- **Predictor Responsibility**: Only the predictor service sets `MONITORING_ACTIVE` based on fatigue analysis
- **Cache Dependencies**: Services may fail if Redis cache is cleared and server is offline
- **State Transitions**: System stays in `scanning` until predictor determines fatigue state

### System Services

All services are designed to run as systemd units with:

- Automatic startup on boot
- Service dependency management
- Native systemd watchdog monitoring for reliability
- Centralized logging via journald

### Configuration

- **Redis**: Central data hub for service communication
- **Device Settings**: MAC addresses and hardware configuration
- **Alert Thresholds**: Personalized fatigue detection limits
- **Network Settings**: MQTT broker and telemetry configuration

## Security & Privacy

- **Local Processing**: All facial recognition performed on-device
- **Profile Encryption**: Secure pilot profile storage in Redis
- **Access Control**: Service-based permission model
- **Audit Trails**: Comprehensive Redis-based event logging
- **Network Security**: TLS encryption for cloud communication

## Compliance & Safety

This system is designed with aviation safety standards in mind:

- **Real-time Response**: Sub-second alert capabilities
- **Reliability**: Redundant monitoring and automatic recovery
- **Offline Operation**: No dependency on network connectivity
- **Data Integrity**: Local logging and audit capabilities
- **Hardware Redundancy**: Multiple sensor inputs and alert outputs

## Contributing

This project follows defensive security practices. All code modifications should:

1. Maintain system security and privacy standards
2. Preserve real-time performance requirements
3. Include comprehensive testing
4. Follow existing architectural patterns

## License

See `LICENSE` file for licensing information.

## Support

For technical support and bug reports, refer to project documentation in the `docs/` directory.

---

**⚠️ Aviation Safety Notice**: This system is designed as a fatigue detection aid and should not replace standard aviation safety protocols and pilot judgment.
