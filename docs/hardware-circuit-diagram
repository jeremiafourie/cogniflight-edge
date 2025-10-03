# CogniFlight Edge - Complete System Circuit Diagram

## Dual Raspberry Pi System Architecture

```mermaid
graph TB
    subgraph "Raspberry Pi 5 - Main Controller"
        RPI5[Raspberry Pi 5<br/>40-Pin GPIO Header<br/>Main Controller + Redis Server]
    end
    
    subgraph "Raspberry Pi 4 - Edge Unit"
        RPI4[Raspberry Pi 4B<br/>40-Pin GPIO Header<br/>Sensors + Alerts]
    end
    
    subgraph "Pi 5 Hardware"
        subgraph "Vision Input"
            CAM[Pi Camera<br/>Module v2<br/>640x360 @ 30fps]
        end
        
        subgraph "PWM Control"
            PWM[Seeed Studio<br/>PCA9685 PWM Board<br/>16 Channels @ 0x40]
        end
    end
    
    subgraph "Pi 4 Hardware"
        subgraph "Environmental Sensors"
            DHT[DHT22<br/>Temp/Humidity]
            GY91[GY-91 Board<br/>MPU9250 @ 0x68<br/>BMP280 @ 0x76]
        end
        
        subgraph "Bio Sensors"
            MQ3[MQ3<br/>Alcohol Sensor<br/>INVERTED LOGIC]
            BLE[XOSS X2<br/>Heart Rate Sensor<br/>Bluetooth LE]
        end
        
        subgraph "Alert Outputs"
            RGB[RGB LED<br/>Common Cathode]
            BUZZ[Active Buzzer<br/>INVERTED LOGIC]
            VIB[Vibration Motor]
        end
    end
    
    subgraph "Network Layer"
        REDIS_NET[Redis Network<br/>TCP Port 6379<br/>cogniflight.local]
    end
    
    %% Pi 5 Connections
    RPI5 -->|CSI Port<br/>15-pin ribbon| CAM
    
    RPI5 -->|Pin 3: GPIO2/SDA1| PWM
    RPI5 -->|Pin 5: GPIO3/SCL1| PWM
    RPI5 -->|Pin 4: 5V| PWM
    RPI5 -->|Pin 6: GND| PWM
    
    %% Pi 4 Power Connections
    RPI4 -->|Pin 1: 3.3V| GY91
    RPI4 -->|Pin 2: 5V| DHT
    RPI4 -->|Pin 2: 5V| MQ3
    
    %% Pi 4 DHT22 Connections
    RPI4 -->|Pin 31: GPIO6<br/>+ 4.7kΩ pullup| DHT
    RPI4 -->|Pin 6: GND| DHT
    
    %% Pi 4 GY-91 I2C2 Connections
    RPI4 -->|Pin 7: GPIO4/SDA2| GY91
    RPI4 -->|Pin 29: GPIO5/SCL2| GY91
    RPI4 -->|Pin 9: GND| GY91
    RPI4 -->|Pin 33: GPIO13 INT| GY91
    
    %% Pi 4 MQ3 Connections
    RPI4 -->|Pin 12: GPIO18<br/>Digital Out| MQ3
    RPI4 -->|Pin 34: GND| MQ3
    
    %% Pi 4 RGB LED Connections
    RPI4 -->|Pin 11: GPIO17<br/>+ 220Ω| RGB
    RPI4 -->|Pin 13: GPIO27<br/>+ 220Ω| RGB
    RPI4 -->|Pin 15: GPIO22<br/>+ 220Ω| RGB
    RPI4 -->|Pin 14: GND| RGB
    
    %% Pi 4 Buzzer with Transistor
    RPI4 -->|Pin 18: GPIO24<br/>+ 1kΩ → 2N2222A| BUZZ
    RPI4 -->|Pin 20: GND| BUZZ
    
    %% Pi 4 Vibrator with Transistor
    RPI4 -->|Pin 22: GPIO25<br/>+ 1kΩ → 2N2222A<br/>+ 1N4001 diode| VIB
    RPI4 -->|Pin 25: GND| VIB
    
    %% Pi 4 Bluetooth Connection
    RPI4 -.->|Bluetooth 5.0<br/>Wireless| BLE
    
    %% Network Communication
    RPI5 <-->|Network Redis<br/>Server Mode| REDIS_NET
    RPI4 <-->|Network Redis<br/>Client Mode| REDIS_NET
    
    %% Service Assignments Pi 5
    CAM -->|authenticator<br/>vision_processor| PI5_VISION[Vision Services<br/>Pi 5]
    PWM -->|motion_controller| PI5_MOTION[Motion Control<br/>Pi 5]
    REDIS_NET -->|network_connector<br/>https_client<br/>predictor| PI5_NET[Network & Fusion<br/>Services - Pi 5]
    
    %% Service Assignments Pi 4
    DHT -->|env_monitor| PI4_ENV[Environmental<br/>Pi 4]
    GY91 -->|env_monitor| PI4_ENV
    MQ3 -->|bio_monitor| PI4_BIO[Biometric<br/>Pi 4]
    BLE -->|bio_monitor| PI4_BIO
    RGB -->|alert_manager| PI4_ALERT[Alert System<br/>Pi 4]
    BUZZ -->|alert_manager| PI4_ALERT
    VIB -->|alert_manager| PI4_ALERT
    
    style RPI5 fill:#2196f3,color:#fff
    style RPI4 fill:#4caf50,color:#fff
    style DHT fill:#4caf50
    style GY91 fill:#9c27b0
    style MQ3 fill:#ff9800
    style CAM fill:#00bcd4
    style BLE fill:#f44336
    style RGB fill:#ffc107
    style BUZZ fill:#795548
    style VIB fill:#607d8b
    style PWM fill:#ff5722
    style REDIS_NET fill:#9e9e9e
```

## Pin Connection Tables

### Raspberry Pi 5 - Main Controller

| Pin | GPIO | Device | Function | Service |
|-----|------|--------|----------|---------|
| **PWM Control** |
| 3 | GPIO2/SDA1 | Seeed PWM Board | I2C Data | motion_controller |
| 4 | 5V | Seeed PWM Board | Power | motion_controller |
| 5 | GPIO3/SCL1 | Seeed PWM Board | I2C Clock | motion_controller |
| 6 | GND | Seeed PWM Board | Ground | motion_controller |
| **Vision** |
| CSI | - | Pi Camera v2 | Camera Interface | authenticator, vision_processor |

### Raspberry Pi 4 - Edge Unit

| Pin | GPIO | Device | Function | Service |
|-----|------|--------|----------|---------|
| **Environmental Sensors** |
| 1 | 3.3V | GY-91 | Power | env_monitor |
| 2 | 5V | DHT22, MQ3 | Power | env_monitor, bio_monitor |
| 6 | GND | DHT22 | Ground | env_monitor |
| 7 | GPIO4/SDA2 | GY-91 | I2C2 Data | env_monitor |
| 9 | GND | GY-91 | Ground | env_monitor |
| 29 | GPIO5/SCL2 | GY-91 | I2C2 Clock | env_monitor |
| 31 | GPIO6 | DHT22 | Data + 4.7kΩ pullup | env_monitor |
| 33 | GPIO13 | GY-91 | MPU9250 Interrupt | env_monitor |
| **Bio Sensors** |
| 12 | GPIO18 | MQ3 | Digital Out (Inverted) | bio_monitor |
| 34 | GND | MQ3 | Ground | bio_monitor |
| BLE | - | XOSS X2 HR Sensor | Wireless | bio_monitor |
| **Alert Outputs** |
| 11 | GPIO17 | RGB LED | Red Channel | alert_manager |
| 13 | GPIO27 | RGB LED | Green Channel | alert_manager |
| 14 | GND | RGB LED | Common Cathode | alert_manager |
| 15 | GPIO22 | RGB LED | Blue Channel | alert_manager |
| 18 | GPIO24 | Buzzer | Control (Inverted) | alert_manager |
| 20 | GND | Buzzer | Ground | alert_manager |
| 22 | GPIO25 | Vibrator | Control | alert_manager |
| 25 | GND | Vibrator | Ground | alert_manager |

## Service Distribution Summary

### Raspberry Pi 5 Services
1. **Redis Server** - Central data hub at cogniflight.local:6379
2. **authenticator** - Facial recognition using camera
3. **vision_processor** - Real-time eye tracking (EAR/MAR) using camera
4. **network_connector** - MQTT telemetry to cloud
5. **https_client** - Cloud API communication
6. **predictor** - Data fusion and fatigue calculation
7. **motion_controller** - Future servo control via PWM board

### Raspberry Pi 4 Services
1. **env_monitor** - DHT22 + GY-91 sensor monitoring
2. **bio_monitor** - Heart rate (BLE) + Alcohol detection (MQ3)
3. **alert_manager** - RGB LED, buzzer, vibrator control

## System Data Flow

```
1. Pi 5 Camera → authenticator/vision_processor → Vision data
2. Pi 4 Sensors → env_monitor/bio_monitor → Sensor data
3. All data → Redis Network (TCP 6379) → Central hub
4. predictor (Pi 5) → Fatigue calculation → System state
5. System state → Redis Network → Pi 4
6. alert_manager (Pi 4) → Hardware alerts based on state
7. network_connector (Pi 5) → MQTT telemetry to cloud
8. https_client (Pi 5) → Pilot profiles from cloud
```

## Key Hardware Notes

- **Camera on Pi 5**: Shared between authenticator and vision_processor
- **Seeed PWM Board on Pi 5**: I2C1 bus for future servo control
- **All alerts on Pi 4**: RGB LED, buzzer, vibrator controlled by alert_manager
- **All environmental sensors on Pi 4**: DHT22, GY-91, MQ3, XOSS X2 BLE HR
- **Network Redis**: Pi 5 hosts server, Pi 4 connects as client
- **Inverted Logic**: MQ3 (HIGH=Clean), Buzzer (HIGH=OFF)
- **Heart Rate Sensor**: XOSS X2 replaces Magene H64 (both use BLE)
