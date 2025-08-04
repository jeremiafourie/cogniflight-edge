# Face Recognition Service

The Face Recognition service provides pilot identification using InsightFace deep learning models. It continuously scans for faces, identifies known pilots against stored embeddings, and triggers pilot profile loading while maintaining security through intruder detection.

## Key Features

- **InsightFace Deep Learning**: State-of-the-art face recognition with buffalo_s model
- **Real-time Identification**: 15fps face detection and recognition
- **Embedding-Based Matching**: Cosine similarity matching against stored pilot embeddings
- **Intruder Detection**: Security alerts for unknown faces
- **Resource Management**: Releases camera when pilot is active for vision processing
- **Adaptive Processing**: Frame skipping and adaptive feedback frequency

## Inputs

### Hardware Inputs

- **Camera Feed**: 640x360@15fps via rpicam-vid
- **Face Embeddings**: Pre-computed pilot face embeddings from pickle file

### Configuration

- **Recognition Threshold**: 0.4 (cosine similarity)
- **Detection Threshold**: 0.7 (face detection confidence)
- **Embedding File**: Stored pilot face embeddings

## Processing

### 1. Service Initialization with Watchdog Support

```python
def main():
    """Main face recognition service with proper systemd integration"""
    # Initialize InsightFace model with watchdog notifications
    logger.info("Initializing face analysis model - this may take up to 60 seconds for first download...")
    pilot_face_analyzer = FaceAnalysis(name=FACE_MODEL_NAME, providers=["CPUExecutionProvider"])

    # Send watchdog notifications during model preparation to prevent timeout
    logger.info("Preparing face analysis model...")
    systemd.daemon.notify('WATCHDOG=1')
    pilot_face_analyzer.prepare(ctx_id=0, det_size=(640, 640))
    systemd.daemon.notify('WATCHDOG=1')

    # Notify systemd that service is ready (after model initialization)
    systemd.daemon.notify('READY=1')
    logger.info("Notified systemd that service is ready")
```

### 2. Face Detection and Recognition

```python
def identify_pilot_from_frame(frame, face_analyzer, pilot_embeddings, recognition_threshold, detection_threshold, logger):
    """
    Identify pilot from camera frame against known pilot embeddings.
    Returns: (pilot_id or None, face_detected_boolean, confidence_score)
    """
    faces = face_analyzer.get(frame)
    if not faces:
        return None, False, 0.0

    face = faces[0]  # Use largest/first face

    # Check face detection confidence to filter false positives
    detection_score = getattr(face, 'det_score', 1.0)
    if detection_score < detection_threshold:
        return None, False, 0.0

    # Extract and normalize embedding
    emb = face.embedding
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm

    # Compare against known embeddings
    best_match = None
    best_sim = -1.0

    for pid, pilot_embedding in pilot_embeddings.items():
        sim = cosine_similarity(emb, pilot_embedding)
        if sim > best_sim:
            best_sim = sim
            best_match = pid

    if best_sim >= recognition_threshold:
        return best_match, True, best_sim

    return None, True, best_sim  # Face detected but not recognized
```

### 3. Camera Management

```python
class PilotDetectionCamera:
    """Camera capture system for pilot identification using rpicam-vid"""

    def start(self):
        cmd = [
            'rpicam-vid',
            '--codec', 'yuv420',
            '--width', str(self.width),
            '--height', str(self.height),
            '--framerate', str(self.fps),
            '--timeout', '0',
            '--output', '-',
            '--nopreview',
            '--flush'
        ]

        self.process = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, bufsize=0)
```

### 4. Pilot Detection Flow with Reactive Subscriptions

```python
def main():
    """Main face recognition service with reactive pilot management"""

    # Deactivate all pilots on startup for proper camera handover
    core.deactivate_all_pilots()

    # Subscribe to pilot changes for reactive camera management
    def on_pilot_change(hash_name, data):
        global active_pilot_detected, camera_released
        pilot_id = data.get('pilot_id') if data else None
        is_active = data.get('active', False) if data else False

        if pilot_id and is_active and not active_pilot_detected:
            # Pilot activated - trigger camera release
            active_pilot_detected = True
            camera_released = False

    # Subscribe to existing pilots for activation detection
    existing_pilots = core.list_pilots()
    for pilot_id in existing_pilots:
        core.subscribe_to_data(f"pilot:{pilot_id}", on_pilot_change)

    while running:
        # Reactive camera handover based on pilot subscriptions
        if active_pilot_detected and not camera_released:
            logger.info("Active pilot found via subscription - releasing camera")
            camera.release()
            camera_released = True

            # Wait for pilot to be deactivated
            while active_pilot_detected:
                systemd.daemon.notify('WATCHDOG=1')
                time.sleep(5)

            # Restart camera after handover
            camera = PilotDetectionCamera(logger, ...)
            camera.start()

        ret, frame = camera.read()
        if ret and frame is not None:
            # Process every 5th frame for faster response (333ms max delay)
            if frame_count % 5 == 0:
                pilot_id, face_detected, confidence = identify_pilot_from_frame(...)

                if pilot_id:
                    # Known face recognized - send profile request
                    core.set_system_state(SystemState.SCANNING,
                                        f"Welcome {pilot_id}\nFetching profile")

                    # Send pilot ID request to HTTPS client
                    request_data = {
                        "pilot_id": pilot_id,
                        "confidence": float(confidence),
                        "timestamp": time.time(),
                        "source": "face_recognition"
                    }
                    core.publish_data("pilot_id_request", request_data)

                    # Set up subscription for this pilot if not already subscribed
                    setup_pilot_subscription(core, pilot_id, logger)

                elif face_detected:
                    # Unknown face detected
                    core.set_system_state(SystemState.INTRUDER_DETECTED,
                                        "WARNING\nIntruder Alert")
                else:
                    # No face detected
                    core.set_system_state(SystemState.SCANNING,
                                        "Scanning...\nCabin Empty")
```

## Outputs

### CogniCore Publications

#### `pilot_id_request` Data Hash

```json
{
  "pilot_id": "pilot123",
  "confidence": 0.856,
  "timestamp": 1234567890.123,
  "source": "face_recognition"
}
```

### System State Changes

- **SystemState.SCANNING**: "Scanning...\nCabin Empty" (no face)
- **SystemState.SCANNING**: "Welcome {pilot_id}\nFetching profile" (recognized pilot)
- **SystemState.INTRUDER_DETECTED**: "WARNING\nIntruder Alert" (unknown face)

## Face Recognition Pipeline

### 1. Face Detection

- **Model**: InsightFace buffalo_s with RetinaFace detector
- **Input Size**: 640x640 detection window
- **Confidence Threshold**: 0.7 minimum detection score
- **Max Faces**: 1 (largest face processed)

### 2. Face Embedding

- **Model**: ArcFace embedding network (512-dimensional)
- **Normalization**: L2 normalization for cosine similarity
- **Quality**: High-quality embeddings for accurate matching

### 3. Similarity Matching

```python
def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

# Recognition threshold: 0.4 (cosine similarity)
# Higher values = more strict matching
# Lower values = more permissive matching
```

### 4. Embedding Storage

```python
def load_known_embeddings(path, logger):
    """Load known face embeddings from pickle file"""
    with open(path, "rb") as f:
        embeddings = pickle.load(f)

    # Normalize each embedding to unit length
    for pid, emb in embeddings.items():
        norm = np.linalg.norm(emb)
        if norm > 0:
            embeddings[pid] = emb / norm

    return embeddings
```

## Performance Optimization

### Processing Efficiency

- **Frame Skipping**: Process every 5th frame (15fps → 3fps processing for faster response)
- **Adaptive Frame Rate**: Configurable camera frame rate (default 15fps)
- **Single Face**: Only process largest detected face
- **Early Exit**: Skip processing if no faces detected

### Resource Management

- **Camera Sharing**: Release camera when pilot active (for vision processing)
- **Memory Management**: Efficient embedding storage and lookup
- **CPU Usage**: ~15-20% during active scanning on Raspberry Pi 4

### Feedback Optimization

```python
# Reduce LCD update frequency to prevent conflicts
if faces_processed % 20 == 0:  # Every 20 face checks (100 frames)
    logger.debug(f"Face processing indicator: {faces_processed} faces processed")

# Periodic status updates (optimized frequency)
if time.time() - last_face_feedback > 10:  # Every 10 seconds
    core.set_system_state(SystemState.SCANNING, "Scanning...\nCabin Empty")
```

## Configuration

### Recognition Parameters

```python
RECOGNITION_THRESHOLD = 0.4        # Cosine similarity threshold
FACE_DETECTION_THRESHOLD = 0.7     # Detection confidence threshold
FACE_MODEL_NAME = 'buffalo_s'      # InsightFace model
```

### Camera Settings

```python
CAMERA_WIDTH = 640                 # Camera resolution width
CAMERA_HEIGHT = 360                # Camera resolution height
CAMERA_FPS = 15                    # Camera frame rate
```

### Processing Parameters

```python
FRAME_SKIP = 5                     # Process every Nth frame (optimized for faster response)
HEARTBEAT_INTERVAL = 5             # Seconds between heartbeats
INTRUDER_ALERT_INTERVAL = 3        # Seconds between intruder alert updates
EMPTY_CABIN_FEEDBACK_INTERVAL = 10 # Seconds between empty cabin status updates
```

### Systemd Service Configuration

```ini
[Service]
Type=notify                        # Service notifies systemd when ready
WatchdogSec=30                    # 30-second watchdog timeout
Restart=on-failure                # Automatic restart on failure
RestartSec=5                      # Wait 5 seconds before restart
```

## Error Handling

### Camera Failures

- **Initialization Errors**: Retry camera startup with error logging
- **Frame Read Errors**: Continue processing, skip failed frames
- **Process Termination**: Clean shutdown and restart attempts

### Recognition Errors

- **Model Loading**: Fatal error if InsightFace model fails to load
- **Embedding Errors**: Log errors, continue with reduced functionality
- **Memory Issues**: Graceful degradation with error reporting

### Profile Integration

- **HTTPS Client Communication**: Send pilot ID requests and continue recognition if profile requests fail
- **Pilot Subscription System**: React to pilot activation/deactivation via CogniCore subscriptions
- **Camera Handover**: Automatic camera release when pilot becomes active for vision processing

### Systemd Watchdog Issues

- **Model Download Timeout**: Service sends `WATCHDOG=1` notifications during InsightFace model initialization to prevent 30s timeout
- **Startup Sequence**: Service reports `READY=1` only after model is fully loaded and operational
- **Watchdog Recovery**: Automatic service restart if watchdog timeout occurs during operation
- **Initialization Logging**: Clear status messages about potential model download delays (up to 60 seconds)

### Performance Optimizations (2024)

- **Response Time**: Reduced from 1000ms to 333ms maximum delay (3x faster)
- **Frame Processing**: Optimized from every 15th to every 5th frame
- **Redis Operations**: Eliminated unnecessary Redis calls for immediate pilot detection
- **Status Updates**: More frequent intruder alerts (3s vs 10s) and cabin status (10s vs 15s)
- **Camera Processing**: Reduced thread sleep delays for better frame availability

## Security Features

### Intruder Detection

- **Unknown Face Alert**: Immediate security alert for unrecognized faces
- **Confidence Logging**: Log recognition confidence for security analysis
- **Persistent Alerts**: Continue alerting while unknown face present

### Privacy Protection

- **Local Processing**: All face recognition performed on-device
- **No Image Storage**: Frames processed in memory only
- **Embedding Security**: Pilot embeddings stored locally

## Dependencies

- **InsightFace**: Deep learning face recognition models
- **OpenCV**: Image processing and camera interface
- **NumPy**: Mathematical operations and embedding processing
- **CogniCore**: System communication and state management
- **Pickle**: Embedding file storage and loading

### Hardware Dependencies

- **Raspberry Pi Camera**: Camera module or USB camera
- **GPU Acceleration**: Optional, CPU-only operation supported
- **Memory**: Minimum 2GB RAM for model loading

## Usage

The service runs as a systemd unit with continuous operation:

1. **Startup**: Initialize InsightFace models and load pilot embeddings
2. **Scan**: Continuously scan for faces using camera feed
3. **Recognize**: Compare detected faces against known pilot embeddings
4. **Alert**: Trigger appropriate system states based on recognition results
5. **Handoff**: Release camera to vision processing when pilot detected

## Logging

Comprehensive logging includes:

- Face detection and recognition results
- Pilot identification events and confidence scores
- Camera operations and status changes
- Intruder detection alerts
- System state changes and integration events

## File Structure

```
face_recognition/
├── main.py           # Main service implementation
├── README.md         # This documentation
├── embeddings.pkl    # Pilot face embeddings (if present)
└── systemd/          # Service configuration files
```

## Integration

### Upstream Services

- **None**: Face Recognition is the entry point for pilot detection

### Downstream Services

- **HTTPS Client**: Receives pilot ID requests for profile loading
- **Vision Processing**: Receives camera after pilot detection

### Supporting Services

- **Alert Manager**: Receives system state changes for display
- **CogniCore**: Provides system communication and state management
- **Watchdog**: Monitors service health via heartbeat
