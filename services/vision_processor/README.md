# Vision Processor Service

## Overview
The Vision Processor is a computer vision service that handles both **pilot authentication** and **real-time fatigue monitoring** for the CogniFlight Edge system. It maintains single ownership of the camera resource throughout the service lifetime.

## Architecture Highlights

### Design
- **Single Service**: Handles authentication and fatigue monitoring
- **Persistent Camera**: Camera initialized once, never released until shutdown
- **Mode-Based Processing**: Automatically switches between authentication and monitoring modes
- **Thread-Safe**: No camera resource conflicts

### Modular Structure
```
vision_processor/
├── main.py                    # Unified service with mode switching
├── camera/
│   └── manager.py            # Thread-safe camera management
├── processors/
│   ├── authenticator.py     # InsightFace-based face recognition
│   └── fatigue_detector.py  # MediaPipe-based fatigue monitoring
└── requirements.txt          # Combined dependencies
```

## Operating Modes

### 1. Authentication Mode (Default)
Active when no pilot is authenticated. The service:
- Scans for faces using InsightFace AI model
- Identifies pilots against stored embeddings in Redis
- Detects intruders (unknown faces)
- Sends authentication requests to HTTPS client
- Processes every 5th frame (6 FPS effective)

### 2. Monitoring Mode
Automatically activated when pilot is authenticated. The service:
- Monitors fatigue using MediaPipe face mesh (468 landmarks)
- Calculates Eye Aspect Ratio (EAR) for drowsiness
- Calculates Mouth Aspect Ratio (MAR) for yawn detection
- Detects microsleeps (>1 second eye closures)
- Detects and counts yawns (MAR > 0.5 for 1.2+ seconds)
- Tracks blink rate and patterns
- Provides face position for motion controller
- Auto-deauthenticates after 10 seconds of face loss
- Processes every frame (30 FPS effective)

## Key Features

### Pilot Authentication
- **Face Recognition**: InsightFace buffalo_s model for accurate identification
- **Redis-Based Embeddings**: Face embeddings loaded from Redis, refreshed every 5 minutes
- **Intruder Detection**: Alerts on unknown faces with confidence scores
- **Automatic Profile Loading**: Triggers profile fetch from server upon recognition

### Fatigue Monitoring
- **Real-Time EAR**: Eye Aspect Ratio using standard formula (A+B)/(2*C) with MediaPipe landmarks
  - Left Eye: [362, 385, 387, 263, 373, 380]
  - Right Eye: [33, 160, 158, 133, 153, 144]
  - Closure threshold: 0.20 (eyes closed when EAR < 0.20)
- **Real-Time MAR**: Mouth Aspect Ratio for yawn detection
  - Formula: (N1+N2+N3)/(3*D) using mouth landmarks
  - Yawn threshold: 0.5 (yawning when MAR > 0.5)
- **Microsleep Detection**: Identifies dangerous lapses (>1 second closures)
- **Yawn Detection**: Tracks yawning as fatigue indicator (1.2+ seconds duration)
- **Blink Rate Analysis**: Monitors frequency as fatigue indicator
- **Face Position Tracking**: Normalized coordinates for seat adjustment
- **Face Validation**: Filters false positives (EAR range: 0.10-0.50)
- **Auto-Deauthentication**: Face loss timeout of 10 seconds
- **Hardware Acceleration**: Optimized MediaPipe with 0.75x frame scaling

## Data Flow

### Input Sources
1. **Camera Feed**: 640x360@30fps via rpicam-vid
2. **Redis Subscriptions**:
   - `pilot:{pilot_id}`: Pilot activation status
   - `pilot_id_request`: Authentication request tracking
   - System state changes

### Processing Pipeline
```
Camera Frame → Mode Check → Processor Selection → Result Publication
     ↓              ↓                ↓                    ↓
  rpicam-vid   Auth/Monitor   InsightFace/MediaPipe   Redis Hash
```

### Output Publications
- **Authentication Mode**:
  - `pilot_id_request`: Authentication requests with confidence
  - System states: SCANNING, INTRUDER_DETECTED

- **Monitoring Mode**:
  - `vision`: Fatigue metrics updated in real-time
  ```json
  {
    "timestamp": 1754160412.593,
    "avg_ear": 0.302,
    "mar": 0.275,
    "eyes_closed": false,
    "closure_duration": 0.0,
    "microsleep_count": 1,
    "blink_rate_per_minute": 14.0,
    "yawning": false,
    "yawn_count": 2,
    "yawn_duration": 0.0,
    "face_detected": true,
    "face_offset_x": 0.125,
    "face_offset_y": -0.050
  }
  ```

## Technical Implementation Details

### Eye Aspect Ratio (EAR) Calculation
The EAR formula measures eye openness using MediaPipe's 468 face landmarks:
```
EAR = (A + B) / (2.0 * C)
```
Where:
- A = Distance between landmarks P2 and P6 (vertical)
- B = Distance between landmarks P3 and P5 (vertical)
- C = Distance between landmarks P1 and P4 (horizontal)

**Thresholds:**
- Open eyes: EAR > 0.20 (typical range: 0.25-0.40)
- Closed eyes: EAR < 0.20
- Drowsy state: EAR < 0.18
- Validation range: 0.10-0.50 (filters false detections)

### Mouth Aspect Ratio (MAR) Calculation
The MAR formula detects yawning using mouth landmarks:
```
MAR = (N1 + N2 + N3) / (3 * D)
```
Where:
- N1, N2, N3 = Three vertical distances (upper to lower lip)
- D = Horizontal distance (mouth width)

**Thresholds:**
- Normal: MAR < 0.50 (typical range: 0.25-0.35)
- Yawning: MAR > 0.50
- Yawn duration: 1.2-6.0 seconds
- Cooldown: 3 seconds between yawns

## Configuration

Environment variables (set in `/etc/cogniflight/config.env`):
```bash
# Camera Configuration
CAMERA_WIDTH=640
CAMERA_HEIGHT=360
CAMERA_FPS=30

# Authentication Settings
RECOGNITION_THRESHOLD=0.4         # Face recognition confidence
FACE_DETECTION_THRESHOLD=0.5     # Face detection sensitivity
FACE_MODEL_NAME=buffalo_s        # InsightFace model

# Processing Rates
PROCESS_EVERY_NTH_FRAME_AUTH=5      # Authentication: every 5th frame
PROCESS_EVERY_NTH_FRAME_FATIGUE=1   # Monitoring: every frame

# Timing Configuration
EMBEDDING_REFRESH_INTERVAL=300      # Refresh embeddings every 5 min
PILOT_REQUEST_TIMEOUT=30           # Authentication request timeout
STATUS_LOG_INTERVAL=30              # Status logging frequency
```

## Performance Metrics

### Authentication Mode
- **Recognition Speed**: ~200ms per frame
- **Effective FPS**: 6 FPS (every 5th frame)
- **Memory Usage**: ~500MB (with InsightFace models)
- **CPU Usage**: 10-15% on Raspberry Pi 5

### Monitoring Mode
- **Processing Latency**: 10-20ms per frame
- **Update Frequency**: 30 FPS (real-time)
- **Memory Usage**: ~400MB (with MediaPipe)
- **CPU Usage**: 35-57% on Raspberry Pi 5
- **EAR Accuracy**: >95% with proper MediaPipe landmarks
- **MAR Accuracy**: >90% for yawn detection

### Overall
- **Mode Switch Time**: <100ms
- **Camera Stability**: Zero restarts during normal operation
- **Total Memory**: ~500MB typical, 3GB max
- **Service Uptime**: Continuous without interruption

## State Management

The service can set these system states:
- **SCANNING**: Looking for pilots (authentication mode)
- **INTRUDER_DETECTED**: Unknown face detected
- **SYSTEM_ERROR**: Service malfunction

State transitions are managed by CogniCore with proper permissions.

## Installation & Deployment

### Initial Setup
```bash
# Dependencies installed automatically during deployment
cd services/vision_processor
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Service Management
```bash
# Start the service
sudo systemctl start cogniflight@vision_processor

# Check status
sudo systemctl status cogniflight@vision_processor

# View real-time logs
sudo journalctl -u cogniflight@vision_processor -f

# Restart if needed
sudo systemctl restart cogniflight@vision_processor
```

## Dependencies

### Python Packages
- **opencv-python-headless**: Image processing
- **numpy**: Numerical computations
- **mediapipe**: Facial landmark detection
- **insightface**: Face recognition
- **onnxruntime**: AI model inference
- **Pillow**: Image manipulation
- **scipy**: Scientific computing
- **scikit-learn**: ML utilities
- **redis**: Data communication
- **systemd-python**: Service integration

### System Requirements
- Raspberry Pi 5 (recommended) or Pi 4
- Raspberry Pi Camera Module (v2 or v3)
- 4GB+ RAM recommended
- Active cooling recommended

## Troubleshooting

### Camera Issues
```bash
# Test camera hardware
rpicam-hello

# Check camera process
ps aux | grep rpicam-vid

# Verify no conflicts
sudo fuser /dev/video0
```

### Model Loading Issues
```bash
# InsightFace models location
ls ~/.insightface/models/buffalo_s/

# Clear corrupted cache
rm -rf ~/.insightface/models/

# Models auto-download on next start
```

### Performance Optimization
```bash
# Monitor CPU temperature
vcgencmd measure_temp

# Check resource usage
htop

# Verify GPU memory split (if applicable)
vcgencmd get_mem arm && vcgencmd get_mem gpu
```

## Integration Points

### Upstream Services
- **HTTPS Client**: Provides pilot profiles and embeddings
- **Predictor**: Triggers mode changes via pilot activation

### Downstream Services
- **Predictor**: Consumes vision data for fatigue fusion
- **Motion Controller**: Uses face position for seat adjustment
- **Network Connector**: Transmits vision telemetry
- **Alert Manager**: Displays visual alerts

### Redis Keys
- **Subscriptions**: `pilot:{id}`, `pilot_id_request`, state changes
- **Publications**: `vision` (monitoring data), `pilot_id_request` (auth requests)

## Security Considerations

- Face embeddings stored securely in Redis with authentication
- Unknown faces trigger immediate intruder alerts
- Service runs with restricted systemd permissions
- No network exposure of raw camera feed
- Embeddings refreshed periodically from secure server


## Authors & License

Part of the CogniFlight Edge system.
Developed for enhanced aviation safety through AI-powered fatigue detection.