# Network Connector Service

The Network Connector service handles telemetry data transmission for the CogniFlight Edge system. It collects sensor data and predictions every 2 seconds and transmits them to an MQTT broker for monitoring and analysis.

## Overview

This service acts as the communication bridge between the CogniFlight Edge system and external monitoring infrastructure via MQTT over TLS. It provides reliable data transmission with offline buffering and retry mechanisms.

## Features

- **Real-time Data Collection**: Subscribes to all sensor and prediction data streams via Redis
- **2-Second Transmission Interval**: Sends comprehensive telemetry snapshots every 2 seconds
- **MQTT over TLS**: Secure transmission using MQTT protocol with TLS encryption
- **Offline Buffering**: Stores up to 1000 failed transmissions for later retry when connectivity is restored
- **Automatic Retry Logic**: Retries failed transmissions when connection is restored
- **Health Monitoring**: Tracks transmission success/failure rates and connection status
- **SystemD Integration**: Full systemd service lifecycle management with watchdog support

## Data Sources

The service collects data from all CogniFlight Edge components:

- **Vision Processing**: Eye tracking metrics (EAR, blink rate, microsleeps, eye closure)
- **Heart Rate Monitor**: BLE heart rate sensor data
- **Predictor Service**: Fusion scores and confidence levels for fatigue detection
- **Environmental Monitor**: Temperature and humidity readings
- **System State**: Current system state and operational status
- **Pilot Profiles**: Active pilot information

## Configuration

### Environment Variables

- `MQTT_BROKER`: MQTT broker hostname (default: cogniflight.exequtech.com)
- `MQTT_PORT`: MQTT broker port (default: 8883 for TLS)
- `MQTT_USERNAME`: MQTT authentication username and edge identifier (default: N420HH)
- `MQTT_PASSWORD`: MQTT authentication password
- `MQTT_TOPIC`: Base MQTT topic for publishing telemetry (default: cogniflight/telemetry)
  - **Note**: Actual topic includes edge username: `cogniflight/telemetry/{MQTT_USERNAME}`
- `MQTT_QOS`: MQTT Quality of Service level (default: 1 - at least once delivery)
- `DEVICE_ID`: Unique device identifier (default: cogniflight-edge-001)

### Example Configuration

Create a configuration file at `/etc/cogniflight/config.network_connector.env`:

```bash
MQTT_BROKER=cogniflight.exequtech.com
MQTT_PORT=8883
MQTT_USERNAME=N420HH
MQTT_PASSWORD=your-password-here
MQTT_TOPIC=cogniflight/telemetry
DEVICE_ID=cogniflight-edge-001
```

## Data Format

### Telemetry Payload Structure

The service sends flattened JSON payloads optimized for Telegraf/InfluxDB ingestion:

```json
{
  "collection_time": 1729462199.98,
  "predictor_version": "1.0.0",
  "connection_status": "connected",
  "edge_username": "N420HH",
  "device_id": "cogniflight-edge-001",
  "temperature": 33.6,
  "humidity": 35.3,
  "avg_ear": 0.294,
  "eyes_closed": false,
  "closure_duration": 0.0,
  "microsleep_count": 1,
  "blink_rate": 1.0,
  "fusion_score": 0.108,
  "confidence": 0.8,
  "system_state": "monitoring_active",
  "state_message": "I'm watching\n.32 1 33 35",
  "pilot_id": "pilot_123",
  "pilot_name": "John Doe"
}
```

### Field Descriptions

- **collection_time**: Unix timestamp (seconds) when data was collected
- **predictor_version**: Version of the predictor algorithm
- **connection_status**: MQTT connection status (connected/disconnected/connection_error)
- **edge_username**: Edge device identifier (typically aircraft tail number)
- **device_id**: Unique device instance identifier
- **temperature**: Temperature in Celsius
- **humidity**: Relative humidity percentage
- **avg_ear**: Average Eye Aspect Ratio (0.0-1.0, lower = more closed)
- **eyes_closed**: Boolean indicating if eyes are currently closed
- **closure_duration**: Duration of current eye closure in seconds
- **microsleep_count**: Number of microsleep events detected
- **blink_rate**: Blinks per minute
- **fusion_score**: Fatigue score from predictor (0.0-1.0, higher = more fatigued)
- **confidence**: Confidence level of the prediction (0.0-1.0)
- **system_state**: Current system state enum value
- **state_message**: Human-readable state message
- **pilot_id**: Active pilot identifier (if authenticated)
- **pilot_name**: Active pilot name (if authenticated)

## Installation

### Dependencies

```bash
cd services/network_connector
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### SystemD Service Setup

The service uses the templated systemd service:

```bash
# Enable and start service
sudo systemctl enable cogniflight@network_connector
sudo systemctl start cogniflight@network_connector

# Check status
sudo systemctl status cogniflight@network_connector
```

## Monitoring

### Service Status

```bash
# Check service status
sudo systemctl status cogniflight@network_connector

# View logs
sudo journalctl -u cogniflight@network_connector -f

# Check recent telemetry samples
sudo journalctl -u cogniflight@network_connector | grep "Sample payload"
```

### Key Metrics

The service logs health information periodically:

- **Successful Transmissions**: Total number of successful MQTT publishes
- **Failed Transmissions**: Number of failed transmission attempts
- **Buffer Size**: Current number of messages waiting for retry (max 1000)
- **Connection Status**: Current MQTT connection state

## Troubleshooting

### Common Issues

1. **MQTT Connection Errors**
   - Check network connectivity to MQTT broker
   - Verify MQTT credentials (username/password)
   - Check firewall allows outbound connections on port 8883
   - Verify TLS/SSL certificates are valid

2. **High Buffer Size**
   - Indicates persistent connectivity issues
   - Check MQTT broker availability
   - Monitor retry attempts in logs
   - Buffer holds up to 1000 messages (~33 minutes of data at 2s intervals)

3. **Service Not Starting**
   - Verify Redis is running (`systemctl status redis-server`)
   - Check Python dependencies are installed in venv
   - Review systemd service configuration
   - Check logs for Python errors

4. **Fusion Score Always Null**
   - Verify predictor service is running (`systemctl status cogniflight@predictor`)
   - Check predictor service logs for errors
   - Ensure vision_processor is publishing data

### Debug Mode

Enable debug logging:

```bash
# Edit service file or create override
sudo systemctl edit cogniflight@network_connector

# Add:
[Service]
Environment=LOG_LEVEL=DEBUG
Environment=PYTHONUNBUFFERED=1
```

## MQTT Integration

### Broker Requirements

- **Protocol**: MQTT v3.1.1
- **Transport**: TLS/SSL encryption (port 8883)
- **Authentication**: Username/password
- **QoS**: Supports QoS 0, 1, and 2 (default: 1)

### Telegraf Configuration Example

```toml
[[inputs.mqtt_consumer]]
  servers = ["ssl://cogniflight.exequtech.com:8883"]
  # Topic now includes edge username for multi-edge support
  # Use wildcard to consume from all edges, or specific pattern for subset
  topics = ["cogniflight/telemetry/+"]  # + matches any single level (edge username)
  # Or for specific edges:
  # topics = ["cogniflight/telemetry/N420HH", "cogniflight/telemetry/N123AB"]
  username = "telegraf_user"
  password = "telegraf_password"

  data_format = "json"
  json_time_key = "collection_time"
  json_time_format = "unix"

  # Tag pilot_id for filtering
  json_string_fields = ["pilot_id", "pilot_name", "system_state", "state_message"]

[[outputs.influxdb_v2]]
  urls = ["http://localhost:8086"]
  token = "your-influxdb-token"
  organization = "cogniflight"
  bucket = "telemetry"
```

## Security

### Data Protection

- All transmissions use TLS encryption (MQTT over SSL)
- Username/password authentication for MQTT broker
- No sensitive data logged in plaintext
- Credentials should be stored in environment variables, not code

### Privacy Considerations

- Pilot profile data includes only operational information
- No personally identifiable information beyond pilot name
- Data retention policies should be configured on the MQTT broker/database

## Integration with CogniCore

The service integrates seamlessly with the CogniCore communication system:

- Uses Redis subscriptions for real-time data collection
- Subscribes to: `vision`, `hr`, `fusion`, `env_sensor`, `system_state`, `pilot:*`
- Follows CogniCore data format standards
- Participates in system state management

## Performance

### Resource Usage

- **Memory**: ~30-50MB typical usage
- **CPU**: <5% on Raspberry Pi 4
- **Network**: ~500-800 bytes per transmission (every 2 seconds)
- **Storage**: Minimal (buffered data only, max ~100KB)

### Scalability

- Configurable transmission intervals (default: 2 seconds)
- Automatic retry with buffer (up to 1000 messages)
- Efficient JSON serialization
- Connection pooling via paho-mqtt

## Architecture Notes

- **Fixed Retry Delay**: 5 seconds between reconnection attempts
- **Buffer Strategy**: FIFO with size limit (oldest messages dropped when full)
- **Threading**: Separate threads for MQTT connection and telemetry transmission
- **Data Freshness**: Always fetches latest data from Redis before transmission
- **Watchdog**: 30-second systemd watchdog for health monitoring

## Future Enhancements

- Exponential backoff for reconnection attempts
- Data compression for large payloads
- Multiple MQTT broker support (failover)
- Configurable buffer persistence (save to disk)
- Metrics aggregation for bandwidth optimization
