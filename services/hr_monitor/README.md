# HR Monitor Service

The HR Monitor service provides continuous Bluetooth Low Energy (BLE) heart rate monitoring with advanced physiological analysis. It connects to configured heart rate sensors and publishes comprehensive heart rate metrics to CogniCore for system-wide use.

## Key Features

- **Advanced HR Analysis**: Provides HRV metrics, baseline deviation, and stress indexing
- **Intelligent BLE Management**: Automatic system Bluetooth disconnection to prevent conflicts
- **Comprehensive Logging**: Complete sensor data visibility with all calculated metrics
- **Real-time Publishing**: Streams enhanced heart rate data via CogniCore Redis
- **Robust Connection Handling**: Automatic retry with improved error recovery
- **Standard BLE Protocol**: Compatible with BLE Heart Rate Profile devices
- **Systemd Integration**: Proper watchdog handling prevents service timeouts

## Architecture

The service follows a continuous monitoring pattern with intelligent connection management:
1. Initialize CogniCore connection and logging
2. Automatically disconnect any existing system Bluetooth connections to prevent conflicts
3. Attempt BLE connection to the configured heart rate sensor
4. Stream heart rate notifications when connected with full data logging
5. Automatically retry on connection failures with improved error handling
6. Publish comprehensive heart rate metrics to CogniCore for system-wide availability

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

## Data Processing

### Heart Rate Data Parsing
```python
def parse_hr_data(data: bytearray) -> int:
    """Parse heart rate data from BLE heart rate measurement."""
    flags = data[0]
    if flags & 0x01:  # 16-bit HR value
        hr = int.from_bytes(data[1:3], byteorder='little')
    else:  # 8-bit HR value
        hr = int(data[1])
    return max(0, min(255, hr))  # Clamp to valid range
```

### Connection Management
- **Connection Attempts**: Continuous retry with 5-second intervals
- **Stay Connected**: Maintains connection while receiving notifications
- **Automatic Recovery**: Reconnects automatically after connection loss
- **Heartbeat Monitoring**: Regular heartbeat signals for service health

## Data Output

### CogniCore Publications

The service publishes enhanced heart rate data to the `hr_sensor` hash in CogniCore:

```json
{
  "hr": 72,
  "t_hr": 1234567890.123,
  "rr_interval": 0.85,
  "baseline_deviation": 0.15,
  "rmssd": 42.5,
  "hr_trend": 1.2,
  "stress_index": 0.25,
  "baseline_hr": 72,
  "baseline_hrv": 45
}
```

**Fields:**
- `hr`: Heart rate in beats per minute (BPM, 0-255)
- `t_hr`: Unix timestamp of measurement
- `rr_interval`: RR interval in seconds for HRV analysis (optional)
- `baseline_deviation`: HR deviation from baseline (0-1)
- `rmssd`: Root Mean Square of Successive Differences in ms
- `hr_trend`: Heart rate trend in BPM per minute
- `stress_index`: Calculated stress level (0-1)
- `baseline_hr`: Individual baseline heart rate
- `baseline_hrv`: Individual baseline HRV

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
Services can consume HR data via CogniCore Redis:
- Physiological monitoring systems
- Telemetry and data logging
- Health alerting systems
- Any service requiring heart rate metrics

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

The service provides comprehensive logging with complete data visibility:
- **Full Sensor Data**: All 8 calculated HR metrics logged in real-time
  - Format: `HR: 72 BPM | RR: 0.850s | Dev: 0.042 | RMSSD: 45.2ms | Trend: 1.50 BPM/min | Stress: 0.025 | Baseline HR: 72 | Baseline HRV: 45`
- **Connection Management**: BLE connection attempts, system disconnections, and status changes
- **Error Recovery**: Detailed error handling and automatic retry information
- **Performance Metrics**: Data processing times and sensor reliability
- **Configuration Issues**: Setup and hardware problems

All logging integrates with systemd journald and can be viewed with `journalctl -u hr_monitor -f`.

## File Structure

```
hr_monitor/
├── main.py              # Main service implementation
├── requirements.txt     # Python dependencies
├── hr_monitor.service   # Systemd service configuration
└── README.md           # This documentation
```
