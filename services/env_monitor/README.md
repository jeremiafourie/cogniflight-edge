# Environmental Monitor Service

## Overview

The Environmental Monitor service continuously monitors cabin environmental conditions using DHT22 sensors. It provides temperature and humidity data for comprehensive situational awareness and potential correlation with pilot fatigue indicators.

## Key Features

- **DHT22 Sensor Integration**: High-precision temperature and humidity monitoring
- **Continuous Monitoring**: 1Hz sampling rate for real-time environmental data
- **Data Validation**: Quality checks and range validation for sensor readings
- **CogniCore Integration**: Real-time data publishing via Redis
- **Robust Error Handling**: Graceful sensor failure recovery

## Inputs

### Hardware Inputs

- **DHT22 Sensor**: Digital temperature and humidity sensor
  - **Temperature Range**: -40°C to +80°C (±0.5°C accuracy)
  - **Humidity Range**: 0-100% RH (±2-5% accuracy)
  - **Interface**: Single-wire digital interface (GPIO pin)

### Configuration

- **GPIO Pin**: BCM Pin 4 (configurable)
- **Poll Interval**: 1.0 seconds
- **Retry Logic**: Built-in sensor retry mechanism

## Outputs

### CogniCore Publications

#### `env_sensor` Data Hash

```json
{
  "temp": 23.5,
  "humidity": 45.2,
  "t_sensor": 1234567890.123
}
```

**Fields:**

- `temp`: Temperature in degrees Celsius (°C)
- `humidity`: Relative humidity percentage (% RH)
- `t_sensor`: Timestamp of sensor reading acquisition

## Sensor Specifications

### DHT22 Technical Details

- **Temperature Range**: -40°C to +80°C
- **Temperature Accuracy**: ±0.5°C
- **Humidity Range**: 0-100% RH
- **Humidity Accuracy**: ±2-5% RH
- **Resolution**: 0.1°C / 0.1% RH
- **Power Supply**: 3.3-6V DC
- **Current**: 2.5mA max during measurement

### GPIO Interface

```python
# DHT22 Configuration
DHT_SENSOR = Adafruit_DHT.DHT22  # Sensor type
DHT_PIN = 4                      # BCM GPIO pin number
```

### Wiring Diagram

```
DHT22 Sensor    Raspberry Pi
VCC       →     3.3V (Pin 1)
DATA      →     GPIO4 (Pin 7)
GND       →     GND (Pin 9)

Note: 10kΩ pull-up resistor between VCC and DATA (often built into breakout boards)
```

## Configuration

### Service Parameters

```python
POLL_INTERVAL = 1.0           # 1 Hz sampling rate
SERVICE_NAME = "env_monitor"
HEARTBEAT_INTERVAL = 10       # Watchdog heartbeat frequency
```

### Sensor Settings

```python
DHT_SENSOR = Adafruit_DHT.DHT22  # DHT22 sensor type
DHT_PIN = 4                      # BCM GPIO pin
RETRY_ATTEMPTS = 3               # Built into Adafruit_DHT.read_retry()
```

## Performance

- **Sampling Rate**: 1 Hz (every second)
- **Response Time**: ~2 seconds for sensor stabilization
- **CPU Usage**: <1% on Raspberry Pi 4
- **Memory Usage**: ~5MB minimal footprint
- **Power Consumption**: 2.5mA max during measurement

## Error Handling

### Sensor Read Failures

```python
def main():
    if sensor_data:
        # Successful reading - publish data
        core.publish_data("env_sensor", sensor_data)
        logger.info(f"DHT22 reading: {sensor_data['temp']}°C, {sensor_data['humidity']}%")
    else:
        # Failed reading - log warning and continue
        logger.warning("Failed to read DHT22 sensor")
```

### Common Issues

1. **Sensor Not Found**: Check wiring and GPIO pin configuration
2. **Intermittent Readings**: Normal DHT22 behavior; retry mechanism handles this
3. **Out of Range Values**: Sensor may need replacement or recalibration
4. **Power Issues**: Verify 3.3V power supply stability

### Recovery Strategies

- **Automatic Retry**: `Adafruit_DHT.read_retry()` handles transient failures
- **Continuous Operation**: Service continues despite individual read failures
- **Error Logging**: Comprehensive error tracking for diagnostics
- **Graceful Degradation**: System continues with last known values

## Dependencies

- **Adafruit_DHT**: DHT sensor library for Raspberry Pi
- **CogniCore**: Redis communication for data publishing
- **GPIO Access**: Raspberry Pi GPIO interface
- **Standard Libraries**: Time, logging, system libraries

### System Requirements

```bash
# Enable GPIO access
sudo raspi-config
# Advanced Options → GPIO → Enable

# Install DHT sensor library
pip install Adafruit_DHT

# Verify GPIO pin availability
gpio readall
```

## Usage

The service runs as a systemd unit with continuous monitoring:

1. **Startup**: Initialize CogniCore connection and DHT sensor interface
2. **Monitor**: Continuously read temperature and humidity every second
3. **Publish**: Send sensor data to CogniCore for system integration
4. **Heartbeat**: Maintain watchdog heartbeat for service monitoring

## Integration Flow

```
DHT22 Sensor → GPIO Interface → Environmental Monitor
                                        ↓
                               Data Validation & Formatting
                                        ↓
                                 CogniCore Publication
                                        ↓
                            System Integration (Telemetry)
```

## Environmental Data Applications

### System Integration

- **Telemetry Data**: Environmental conditions included in system telemetry
- **Correlation Analysis**: Potential correlation with fatigue indicators
- **System Health**: Monitor equipment operating conditions
- **Data Logging**: Historical environmental data for analysis

### Operational Insights

- **Cabin Comfort**: Ensure optimal environmental conditions
- **Trend Analysis**: Track environmental changes over flight duration
- **Alert Thresholds**: Potential alerts for extreme conditions
- **Performance Impact**: Understand environmental effects on system performance

## Logging

Comprehensive logging includes:

- Successful sensor readings with values
- Sensor read failures and error conditions
- CogniCore publication status
- Service startup and shutdown events
- Heartbeat status and errors

## Troubleshooting

### Sensor Issues

1. **No Readings**: Check wiring, power supply, and GPIO configuration
2. **Erratic Values**: Verify sensor placement and environmental stability
3. **Consistent Errors**: Sensor may need replacement
4. **Slow Response**: Normal DHT22 behavior; readings may take 1-2 seconds

### Service Issues

1. **High CPU Usage**: Unusual; check for excessive error retry loops
2. **Memory Leaks**: Monitor service memory usage over time
3. **CogniCore Connection**: Verify Redis connectivity for data publishing

## File Structure

```
env_monitor/
├── main.py           # Main service implementation
├── README.md         # This documentation
├── Adafruit_DHT.py   # Local DHT library fallback (if needed)
└── systemd/          # Service configuration files
```

## Integration

### Upstream Services

- **None**: Environmental monitoring is independent

### Downstream Services

- **Network Connector**: Receives environmental data for telemetry
- **Data Analysis**: Environmental data for correlation studies

### Supporting Services

- **CogniCore**: Provides data publishing and system integration
- **Watchdog**: Monitors service health via heartbeat
