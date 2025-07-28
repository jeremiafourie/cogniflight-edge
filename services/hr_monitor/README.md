# HR Monitor Service

## Overview

The HR Monitor service provides continuous Bluetooth Low Energy (BLE) heart rate monitoring for the CogniFlight Edge system. It connects to a configured heart rate sensor and publishes real-time heart rate data to CogniCore for use by other services in the system.

## Key Features

- **Continuous Operation**: Always attempts to connect and monitor the configured heart rate sensor
- **Automatic Reconnection**: Handles BLE connection failures gracefully with automatic retry logic
- **Real-time Publishing**: Immediate heart rate data publication via CogniCore Redis
- **Standard BLE Protocol**: Compatible with standard BLE heart rate monitors
- **Robust Error Handling**: Continues operation despite connection issues

## Architecture

The service follows a simple continuous monitoring pattern:

1. Initialize CogniCore connection and logging
2. Continuously attempt to connect to the configured heart rate sensor
3. Stream heart rate notifications when connected
4. Automatically retry on connection failures
5. Publish all heart rate data to CogniCore for system-wide availability

## Hardware Requirements

### BLE Heart Rate Sensor

- **Service**: Heart Rate Service (UUID: 0x180D)
- **Characteristic**: Heart Rate Measurement (UUID: 0x2A37)
- **Notifications**: Must support heart rate measurement notifications
- **Configuration**: MAC address specified in `config.DEFAULT_HR_SENSOR_MAC`

### Compatible Devices

- Standard BLE heart rate monitors
- Chest strap monitors (Polar, Garmin, etc.)
- Wrist-based HR monitors with BLE support
- Any device implementing the standard BLE Heart Rate Profile

### Connection Management

- **Connection Attempts**: Continuous retry with 5-second intervals
- **Stay Connected**: Maintains connection while receiving notifications
- **Automatic Recovery**: Reconnects automatically after connection loss
- **Heartbeat Monitoring**: Regular heartbeat signals for service health

## Data Output

### CogniCore Publications

The service publishes heart rate data to the `hr_sensor` hash in CogniCore:

```json
{
  "hr": 72,
  "t_hr": 1234567890.123
}
```

**Fields:**

- `hr`: Heart rate in beats per minute (BPM) - clamped to 0-255 range
- `t_hr`: Unix timestamp of measurement acquisition

## Configuration

### Service Parameters

- **HR_UUID**: `"00002a37-0000-1000-8000-00805f9b34fb"` (Heart Rate Measurement)
- **HR_SENSOR_MAC**: `config.DEFAULT_HR_SENSOR_MAC` from CogniCore configuration
- **RETRY_DELAY**: 5 seconds between connection attempts
- **HEARTBEAT_INTERVAL**: 10 seconds for watchdog monitoring

### CogniCore Integration

The service uses CogniCore for:

- Configuration management (`DEFAULT_HR_SENSOR_MAC`)
- Logging infrastructure
- Data publication via Redis
- Service heartbeat monitoring

## Error Handling

### Connection Failures

- **Automatic Retry**: Continuous retry with 5-second delay
- **Logging**: Warning messages for failed connections
- **No Service Interruption**: Other system services continue operating

### Data Validation

- **Range Clamping**: HR values limited to 0-255 BPM
- **Parse Error Recovery**: Invalid data packets logged and skipped
- **Zero Filtering**: Only publishes valid (non-zero) heart rate readings

### Exception Handling

- **BLE Exceptions**: Handled gracefully with retry logic
- **Publication Errors**: Logged but don't interrupt monitoring
- **Service Crashes**: Clean shutdown on unrecoverable errors

## Performance Characteristics

- **Connection Time**: 2-3 seconds for initial BLE connection
- **Data Latency**: <100ms from sensor notification to CogniCore publication
- **CPU Usage**: Minimal (~1-2% during active monitoring)
- **Memory Usage**: ~10MB for BLE stack and service overhead
- **Network Impact**: Low (local Redis publications only)

## Dependencies

### Required Libraries

- **CogniCore**: System integration and Redis communication
- **Bleak**: Cross-platform Bluetooth Low Energy library
- **asyncio**: Asynchronous I/O operations
- **logging**: Service logging
- **time**: Timestamp generation

### System Requirements

- Python 3.7+
- Bluetooth hardware support
- Linux with BlueZ stack (typical on Raspberry Pi)

## Service Lifecycle

### Startup Sequence

1. Initialize CogniCore connection
2. Create logger instance
3. Configure BLE notification handler
4. Enter continuous monitoring loop

### Operation

1. Attempt BLE connection to configured heart rate sensor
2. Start heart rate measurement notifications
3. Process and publish heart rate data in real-time
4. Send periodic heartbeat signals
5. Handle connection drops with automatic retry

### Shutdown

- Clean BLE disconnection
- CogniCore cleanup
- Graceful service termination

## Integration Points

### CogniCore Redis

- **Publishes**: `hr_sensor` hash with heart rate data
- **Configuration**: Reads `DEFAULT_HR_SENSOR_MAC` from config
- **Heartbeat**: Regular service health signals
- **Logging**: Centralized logging infrastructure

### Downstream Services

- **Inference Service**: Consumes HR data for physiological state analysis
- **Network Connector**: Transmits HR data in telemetry streams
- **Alert Manager**: May use HR data for alerting conditions
- **Any Service**: HR data available system-wide via CogniCore

## Troubleshooting

### No Heart Rate Data

1. Verify heart rate sensor is powered and in range
2. Check `DEFAULT_HR_SENSOR_MAC` configuration
3. Ensure Bluetooth is enabled on the system
4. Verify sensor is in pairing/advertising mode

### Connection Issues

1. Check BLE signal strength and interference
2. Verify sensor battery level
3. Restart Bluetooth service if needed
4. Check sensor compatibility with BLE Heart Rate Profile

### Service Not Starting

1. Verify CogniCore configuration is valid
2. Check Redis connectivity
3. Ensure Python dependencies are installed
4. Review service logs for specific error messages

## Logging

The service provides comprehensive logging:

- Connection attempts and status
- Heart rate data reception
- BLE errors and recovery attempts
- Configuration issues
- Performance metrics

Logs are managed through CogniCore's logging infrastructure.

## File Structure

```
hr_monitor/
├── main.py              # Main service implementation
├── requirements.txt     # Python dependencies
├── hr_monitor.service   # Systemd service configuration
└── README.md           # This documentation
```
