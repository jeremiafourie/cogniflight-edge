# Motion Controller Service

Controls a pan/tilt servo bracket for camera tracking using the Seeed Studio PWM Driver Board (PCA9685).

## Features

- **Real-time Face Tracking**: Subscribes to vision processor data and adjusts servos to keep pilot's face centered
- **Adaptive Speed Control**: Fast movement for large errors, slow precise movement for small errors
- **Advanced PID Control**: Optimized for stable convergence without overshoot
- **Convergence Detection**: Recognizes when face is properly centered and reduces unnecessary movement
- **Smooth Movement**: Exponential smoothing prevents jerky servo movements
- **Safety Limits**: Prevents mechanical damage with configurable angle limits
- **Auto-Center**: Returns to center position when face is lost
- **State-Aware**: Only tracks when a pilot is active in the system
- **Feedback Loop**: Continuous error correction for precise face centering

## Hardware Setup

### Required Components

1. **Seeed Studio Grove 16-Channel PWM Driver (PCA9685)**
   - Default I2C Address: 0x40 (configurable to 0x7F via jumpers)
   - Connected to I2C Bus 1 (GPIO 2 SDA, GPIO 3 SCL)
   - External 5V power supply connected to V+ terminal

2. **2x SG90 Micro Servos**
   - Channel 0: Pan (horizontal) servo
   - Channel 1: Tilt (vertical) servo
   - Operating voltage: 4.8-6V
   - Rotation range: 0-180 degrees

3. **Pan/Tilt Bracket**
   - Standard camera pan/tilt bracket kit
   - Mounted with Pi Camera Module

### Wiring Connections

```
Raspberry Pi 5          PCA9685 Board
--------------          --------------
Pin 3 (GPIO 2)  ------> SDA
Pin 5 (GPIO 3)  ------> SCL
Pin 4 (5V)      ------> VCC
Pin 6 (GND)     ------> GND

External 5V PSU ------> V+ (servo power)
External GND    ------> GND (servo ground)

PCA9685 Board           Servos
--------------          ------
Channel 0       ------> Pan Servo (Orange wire)
Channel 1       ------> Tilt Servo (Orange wire)
V+              ------> Servo Red wires
GND             ------> Servo Brown wires
```

## Configuration

### I2C Setup

Enable I2C bus in `/boot/config.txt`:
```
dtparam=i2c_arm=on
```

Verify PCA9685 detection:
```bash
i2cdetect -y 1
```

You should see device at address 0x40 or 0x7F.

### Service Parameters

Edit parameters in `main.py`:

```python
# Servo Configuration
SERVO_MIN_ANGLE = 10   # Minimum safe angle
SERVO_MAX_ANGLE = 170  # Maximum safe angle
SERVO_CENTER = 90      # Center position

# Tracking Configuration
DEAD_ZONE = 0.03       # Ignore movements < 3% of frame (stability)
UPDATE_RATE = 0.05     # 20Hz update rate (50ms between updates)
CENTERING_TOLERANCE = 0.01  # Face considered centered within 1% of frame
TRACKING_SMOOTHNESS = 0.15  # Smoothing factor (0.0 = instant, 1.0 = no movement)

# Adaptive PID Tuning (optimized for stable convergence)
PID_KP = 20.0          # Proportional gain - moderate for stability
PID_KI = 2.0           # Integral gain - low to prevent windup
PID_KD = 5.0           # Derivative gain - higher to reduce overshoot
PID_OUTPUT_LIMIT = 15.0  # Maximum degrees to move per update

# Adaptive Speed Control
MAX_SPEED_THRESHOLD = 0.3   # Use max speed when error > 30% of frame
MIN_SPEED_THRESHOLD = 0.05  # Use min speed when error < 5% of frame
MAX_SPEED_MULTIPLIER = 2.0  # Speed multiplier for large errors
MIN_SPEED_MULTIPLIER = 0.3  # Speed multiplier for small errors
```

## Installation

1. Create virtual environment:
```bash
cd services/motion_controller
python3 -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Enable systemd service:
```bash
sudo systemctl enable cogniflight@motion_controller
sudo systemctl start cogniflight@motion_controller
```

## Operation

### Normal Operation

1. Service starts and centers servos at 90° position
2. Waits for active pilot detection
3. When pilot is active and face is detected:
   - Tracks face position to keep it centered
   - Uses PID control for smooth movements
   - Applies dead zone to prevent jitter

### Face Loss Behavior

- When face is lost for >3 seconds, servos auto-center
- Tracking resumes immediately when face is redetected

### Data Flow

```
Vision Processor -> Redis "vision" hash -> Motion Controller
                                              |
                                              v
                                         PID Controllers
                                              |
                                              v
                                         PCA9685 Board
                                              |
                                              v
                                         Pan/Tilt Servos
```

## Monitoring

Check service status:
```bash
sudo systemctl status cogniflight@motion_controller
journalctl -u cogniflight@motion_controller -f
```

Monitor servo positions via Redis:
```bash
redis-cli hgetall cognicore:data:motion
```

## Troubleshooting

### Servos Not Moving

1. Check I2C connection:
```bash
i2cdetect -y 1
```

2. Verify external 5V power supply is connected to V+ terminal

3. Check servo wiring (signal on correct channels)

### Jerky Movement

- Increase `DEAD_ZONE` value
- Reduce PID gains (especially `PID_KP`)
- Increase `UPDATE_RATE` for slower updates

### Limited Range

- Adjust `SERVO_MIN_ANGLE` and `SERVO_MAX_ANGLE`
- Calibrate servo pulse widths:
```python
kit.servo[0].set_pulse_width_range(500, 2400)  # Adjust as needed
```

## Integration

The service integrates with:
- **Vision Processor**: Receives face position data
- **CogniCore**: Redis-based communication
- **System State**: Responds to pilot activation/deactivation

## Performance

- Update rate: 20Hz (configurable)
- Latency: <50ms from face detection to servo movement
- CPU usage: ~5% on Raspberry Pi 5
- Memory usage: ~50MB