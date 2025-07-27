# CogniFlight Edge

**CogniFlight Edge** is a real-time pilot fatigue detection and alerting system designed for aviation safety. The system utilizes computer vision, biometric monitoring, and machine learning to detect signs of pilot fatigue and provide immediate alerts through multiple channels.

This edge computing solution operates independently on embedded hardware (Raspberry Pi) with offline capabilities, making it suitable for aircraft environments where network connectivity may be intermittent.

## System Architecture

### Input Sources

- **Computer Vision**: Real-time facial landmark analysis using camera feed
- **Biometric Monitoring**: Heart rate data via Bluetooth Low Energy sensors
- **Environmental Sensors**: Temperature and humidity monitoring
- **Pilot Profiles**: Personalized thresholds and preferences

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
│   ├── inference/       # Data fusion and processing
│   ├── network_connector/# Telemetry and cloud communication
│   ├── predictor/       # Fatigue prediction and alerting
│   └── vision_processing/# Computer vision and landmark detection
├── watchdog/            # Service monitoring and auto-restart
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
