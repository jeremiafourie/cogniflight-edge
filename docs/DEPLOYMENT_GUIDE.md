# CogniFlight Edge - Deployment Guide

## Quick Start

### Primary Device (Pi 5 - Main Processing Unit)

```bash
cd /home/jeremia/Projects/cogniflight-edge
sudo ./scripts/deploy.sh install --primary
```

**What it does:**
- Installs system dependencies (Python, Go, Redis, I2C tools)
- Configures Redis for network access with authentication
- Builds Go client binary from source
- Creates Python virtual environments for all services
- Installs all Python dependencies
- Enables I2C hardware for motion controller
- Validates PCA9685 PWM controller detection
- Configures and starts systemd services
- Sets up primary device as `primary.local`

**Services deployed:**
- `go_client` - Pilot profile management
- `predictor` - Data fusion and fatigue analysis
- `vision_processor` - Authentication and fatigue monitoring
- `network_connector` - MQTT telemetry to cloud
- `motion_controller` - Camera pan/tilt servo control
- `bio_monitor` - Heart rate and alcohol detection

---

### Secondary Device (Pi 4 - Sensors & Alerts)

```bash
cd /home/jeremia/Projects/cogniflight-edge
sudo ./scripts/deploy.sh install --secondary
```

**What it does:**
- Installs system dependencies
- Disables local Redis (connects to primary's Redis)
- Tests connection to primary device at `primary.local`
- Creates Python virtual environments
- Installs Python dependencies
- Configures and starts systemd services

**Services deployed:**
- `env_monitor` - Temperature, humidity, IMU sensors
- `alert_manager` - RGB LED, buzzer, vibrator alerts

---

## Service Management

### Check Status
```bash
sudo ./scripts/deploy.sh status
```

Shows current state of all services with running/stopped indicators.

### Start All Services
```bash
sudo ./scripts/deploy.sh start
```

### Stop All Services
```bash
sudo ./scripts/deploy.sh stop
```

### Restart All Services
```bash
sudo ./scripts/deploy.sh restart
```

### Update Configuration
```bash
sudo ./scripts/deploy.sh update
```

Rebuilds services and updates configuration without reinstalling dependencies.

---

## System Validation

### Run Health Checks
```bash
sudo ./scripts/validate.sh
```

**What it checks:**
- System dependencies (Python, Go, Redis, I2C tools)
- Redis connectivity and version
- Network connectivity (primary/secondary communication)
- Hardware detection (I2C devices, GPIO, camera)
- Service file integrity (venvs, binaries, requirements)
- Systemd service status (enabled/running state)
- Service health (restart counts, memory usage)
- Configuration files

**Output:**
- ✅ Pass count
- ⚠️  Warning count
- ❌ Failure count
- Detailed report of each check

---

## Architecture

### Two-Device Deployment

**Primary Device (Pi 5):**
- Runs Redis server (network accessible)
- Handles all processing-intensive tasks
- Camera for vision processing
- BLE for heart rate monitoring
- I2C for servo control

**Secondary Device (Pi 4):**
- Connects to primary's Redis at `primary.local:6379`
- Handles environmental sensing
- GPIO hardware for alerts

---

## Configuration

All configuration is automatically generated at:
- `/etc/cogniflight/config.env` - Main system config
- `/etc/cogniflight/config.<service>.env` - Service-specific overrides

**Key settings:**
- Redis host/port/password
- Deployment mode (primary/secondary/full)
- Resource limits (memory, CPU)
- Hardware access groups

---

## Troubleshooting

### View Service Logs
```bash
sudo journalctl -u cogniflight@<service_name> -f
```

Examples:
```bash
sudo journalctl -u cogniflight@predictor -f
sudo journalctl -u cogniflight-go@go_client -f
sudo journalctl -u cogniflight@vision_processor -f
```

### Check Redis Connection
```bash
redis-cli -h primary.local -a '13MyFokKaren79.' ping
```

### Verify I2C Devices
```bash
sudo i2cdetect -y 1
```

### Test Camera
```bash
rpicam-hello
```

---

## Uninstall

```bash
sudo ./scripts/deploy.sh uninstall
```

Removes all systemd services, configuration files, and disables services.

**Note:** Does not remove virtual environments or source code.

---

## Requirements

**Hardware:**
- Raspberry Pi 5 (primary) + Pi 4 (secondary)
- GY-91 IMU sensor (I2C)
- PCA9685 PWM controller (I2C)
- MQ3 alcohol sensor (GPIO)
- DHT22 temperature/humidity sensor (GPIO)
- RGB LED, buzzer, vibrator (GPIO)
- Camera module
- XOSS X2 heart rate monitor (BLE)

**Network:**
- Both devices on same local network
- Primary device accessible as `primary.local`
- Internet connection for cloud telemetry (optional)

**Software:**
- Raspberry Pi OS (Debian-based)
- Python 3.11+
- Go 1.21+ (auto-installed)
- Redis server (auto-installed)
