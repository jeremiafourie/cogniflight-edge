# Alert Manager Service

The Alert Manager service provides centralized alert display management through I2C LCD hardware. It operates purely reactively, responding only to system state changes and displaying appropriate messages on the 16x2 character LCD display.

## Key Features

- **State-Only Reactive Design**: Only responds to system state changes
- **16x2 LCD Display**: Hardware I2C LCD with PCF8574 backpack
- **GPIO Hardware Control**: LEDs, buzzer, and vibrator motor for comprehensive alerting
- **Message Deduplication**: Prevents duplicate displays of same state/message
- **Text Wrapping**: Intelligent text wrapping for LCD constraints
- **Hardware Abstraction**: Graceful fallback when LCD unavailable

## Inputs

### CogniCore Subscriptions

- **System State Changes**: The ONLY input triggering LCD updates
  ```json
  {
    "state": "monitoring_active",
    "message": "Monitoring Active",
    "pilot_id": "pilot123",
    "timestamp": 1234567890.123
  }
  ```

### Hardware Input

- **I2C LCD Display**: 16x2 character display via I2C interface
- **I2C Address**: 0x27 (configurable)
- **Display Type**: PCF8574 I2C backpack controller
- **GPIO Hardware**: LEDs (GPIO 17, 27, 22, 23), Buzzer (GPIO 24), Vibrator (GPIO 25)

## Processing

### 1. Pure State-Based Reactivity

```python
class AlertManager:
    """Alert Manager - Only listens to system state changes"""

    def __init__(self):
        # Subscribe ONLY to state changes
        self.core.subscribe_to_state_changes(self.on_state_change)

        # Track current state to avoid duplicate displays
        self.current_state = None
        self.current_message = None
```

### 2. State Change Handling

```python
def on_state_change(self, state_data):
    """Handle system state changes - the ONLY way to update LCD"""
    state = state_data.get("state", "unknown")
    message = state_data.get("message", "")
    pilot_id = state_data.get("pilot_id")

    # Only update LCD if state or message has actually changed
    if state == self.current_state and message == self.current_message:
        return  # No change, skip update

    # Update tracking variables
    self.current_state = state
    self.current_message = message

    # Display the message that came with the state
    if message:
        self.display_on_lcd(message)
    else:
        # Fallback if no message provided with state
        self.display_on_lcd(f"State: {state}")
```

### 3. LCD Text Wrapping

```python
def wrap_text_for_lcd(self, text: str, line_width: int = 16) -> list[str]:
    """Wrap text for LCD display with newline support"""
    lines = []
    text_lines = text.split('\n')

    for line in text_lines:
        if len(line) <= line_width:
            lines.append(line)
        else:
            # Simple word wrap
            words = line.split(' ')
            current_line = ""

            for word in words:
                test_line = f"{current_line} {word}".strip()
                if len(test_line) <= line_width:
                    current_line = test_line
                else:
                    if current_line:
                        lines.append(current_line)
                    current_line = word

            if current_line:
                lines.append(current_line)

    return lines
```

### 4. LCD Hardware Control

```python
def display_on_lcd(self, message: str):
    """Display message on LCD hardware"""
    if not self.lcd:
        return  # LCD not available

    try:
        self.lcd.clear()

        # Wrap text for 16x2 display
        wrapped_lines = self.wrap_text_for_lcd(message, 16)

        # Display up to 2 lines
        for i, line in enumerate(wrapped_lines[:2]):
            self.lcd.cursor_pos = (i, 0)
            self.lcd.write_string(line)

    except Exception as e:
        self.logger.error(f"LCD display error: {e}")
```

### 5. GPIO Hardware Control

```python
def control_gpio_for_state(self, state: str):
    """Control GPIO hardware based on system state"""
    self.logger.info(f"Activating GPIO effects for state: {state}")

    if state == "scanning":
        self.start_gpio_effect(self.scanning_effect)  # Yellow LED toggle
    elif state == "intruder_detected":
        self.start_gpio_effect(self.intruder_detected_effect)  # Red/Blue alternating + buzzer/vibrator
    elif state == "monitoring_active":
        self.start_gpio_effect(self.monitoring_active_effect)  # Green LED solid
    elif state == "alert_mild":
        self.start_gpio_effect(self.alert_mild_effect)  # Green toggle + Blue solid + periodic buzzer
    elif state == "alert_severe":
        self.start_gpio_effect(self.alert_severe_effect)  # Green toggle + Red solid + buzzer/vibrator toggle
```

## Outputs

### Hardware Output

- **16x2 LCD Display**: Physical character display showing system messages
- **Display Format**: Up to 2 lines, 16 characters per line
- **Update Frequency**: Only when system state changes
- **GPIO Devices**: State-dependent LED patterns, buzzer alerts, and vibrator motor activation

### Example Display Messages

#### Normal Operation

```
Monitoring Active
```

#### Pilot Detection

```
Welcome pilot123
Fetching profile
```

#### Fatigue Alerts

```
⚠️ MILD FATIGUE
Score: 0.35
```

#### System States

```
Scanning...
Cabin Empty
```

## Hardware Integration

### LCD Configuration

```python
# I2C LCD configuration for 16x2 display
self.lcd = CharLCD(
    i2c_expander='PCF8574',
    address=0x27,           # I2C address
    port=1,                 # I2C port
    cols=16,                # 16 characters wide
    rows=2,                 # 2 rows
    dotsize=8               # 5x8 dot matrix
)
```

### GPIO Hardware Configuration

```python
# GPIO device initialization
self.green_led = LED(17)      # GPIO 17: Green LED (Active/Monitoring)
self.blue_led = LED(27)       # GPIO 27: Blue LED (Mild Fatigue)
self.yellow_led = LED(22)     # GPIO 22: Yellow LED (Scanning)
self.red_led = LED(23)        # GPIO 23: Red LED (Severe Fatigue/Intruder)
self.buzzer = OutputDevice(24, active_high=False)  # GPIO 24: Buzzer (inverted logic)
self.vibrator = OutputDevice(25)  # GPIO 25: Vibrator Motor
```

### I2C Interface

- **I2C Address**: 0x27 (standard for PCF8574 backpack)
- **I2C Port**: 1 (Raspberry Pi I2C port)
- **Wiring**: SDA (GPIO2), SCL (GPIO3), VCC (5V), GND

### Display Characteristics

- **Character Matrix**: 5x8 dots per character
- **Display Size**: 16 columns × 2 rows
- **Refresh Rate**: Instant (no buffering)
- **Backlight**: Controlled via PCF8574 backpack

## Service States

1. **Active**: Responding to state changes and updating LCD
2. **LCD Error**: Hardware issues with display (continues logging)
3. **Idle**: No recent state changes (display shows last message)

## Message Processing

### State-to-Message Mapping

The service displays messages provided with system state changes:

- **Scanning**: "Scanning...\nCabin Empty"
- **Monitoring Active**: "Monitoring Active"
- **Mild Fatigue**: "⚠️ MILD FATIGUE\nScore: 0.35"
- **Moderate Fatigue**: "⚠️ MODERATE FATIGUE\nScore: 0.65"
- **Severe Fatigue**: "🚨 SEVERE FATIGUE\nScore: 0.85"
- **Intruder Alert**: "WARNING\nIntruder Alert"

### Text Processing Rules

1. **Newline Support**: '\n' creates line breaks
2. **Word Wrapping**: Long lines wrapped at word boundaries
3. **Truncation**: Display limited to 2 lines maximum
4. **Character Limits**: 16 characters per line maximum

## Configuration

### LCD Hardware

```python
LCD_I2C_ADDRESS = 0x27      # PCF8574 I2C address
LCD_COLS = 16               # Display width
LCD_ROWS = 2                # Display height
LCD_PORT = 1                # I2C port number
```

### Service Parameters

```python
WATCHDOG_INTERVAL = 5      # Seconds between systemd watchdog notifications
SERVICE_NAME = "alert_manager"
```

## Error Handling

### LCD Hardware Failures

- **Initialization Failure**: Continue without LCD, log warnings
- **Display Errors**: Catch and log LCD communication errors
- **I2C Issues**: Graceful degradation, service remains operational

### State Processing Errors

- **Invalid State Data**: Log errors, continue operation
- **Message Formatting**: Handle malformed messages gracefully
- **Callback Exceptions**: Isolate errors to prevent service crash

## Performance

- **Response Time**: <50ms from state change to LCD update
- **Memory Usage**: ~8MB including LCD library
- **CPU Usage**: <1% during normal operation
- **I2C Bandwidth**: Minimal (only on state changes)

## Dependencies

- **CogniCore**: System state subscriptions
- **RPLCD**: I2C LCD control library
- **Threading**: Background heartbeat management
- **Standard Libraries**: Time, logging

### Hardware Dependencies

- **I2C Interface**: Raspberry Pi I2C enabled
- **LCD Hardware**: 16x2 LCD with PCF8574 I2C backpack
- **Wiring**: Proper I2C connections (SDA, SCL, power)

## Usage

The service runs as a systemd unit with reactive operation:

1. **Startup**: Initialize LCD hardware and CogniCore subscriptions
2. **Wait**: Listen for system state changes (no polling)
3. **Display**: Update LCD when state changes occur
4. **Heartbeat**: Background thread maintains watchdog heartbeat

## Hardware Setup

### I2C Configuration

```bash
# Enable I2C interface
sudo raspi-config
# Interfacing Options → I2C → Yes

# Verify I2C devices
sudo i2cdetect -y 1
# Should show device at address 0x27
```

### Wiring Diagram

```
LCD Backpack    Raspberry Pi
VCC       →     5V (Pin 2)
GND       →     GND (Pin 6)
SDA       →     GPIO2/SDA (Pin 3)
SCL       →     GPIO3/SCL (Pin 5)

GPIO Devices    Raspberry Pi
Green LED →     GPIO 17 (Pin 11)
Blue LED  →     GPIO 27 (Pin 13)
Yellow LED→     GPIO 22 (Pin 15)
Red LED   →     GPIO 23 (Pin 16)
Buzzer    →     GPIO 24 (Pin 18) [inverted logic]
Vibrator  →     GPIO 25 (Pin 22)
```

## Logging

Comprehensive logging includes:

- System state changes and message updates
- LCD hardware initialization and errors
- Message processing and display operations
- Hardware failures and recovery attempts

## File Structure

```
alert_manager/
├── main.py           # Main service implementation
├── README.md         # This documentation
└── systemd/          # Service configuration files
```

## Integration

### Upstream Services

- **All Services**: Provide system state changes via CogniCore

### Downstream Services

- **None**: Alert Manager is a display endpoint

### Supporting Services

- **CogniCore**: Provides state change subscriptions
- **Watchdog**: Monitors service health via heartbeat
- **Hardware**: I2C LCD display for physical output
