import os
import time
import cv2
import numpy as np
import subprocess
import threading
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import systemd.daemon

# Add project root to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

import mediapipe as mp

from CogniCore import CogniCore, SystemState

# Configuration
FRAME_WIDTH = 640
FRAME_HEIGHT = 360
FPS = 30
SERVICE_NAME = "vision_processing"
HEARTBEAT_INTERVAL = 5  # seconds

# MediaPipe setup
mp_face_mesh = mp.solutions.face_mesh

# Face landmark indices for EAR and MAR calculations
LEFT_EYE_LANDMARKS = [33, 160, 158, 133, 153, 144]   # outer, top-outer, top-inner, inner, bottom-inner, bottom-outer
RIGHT_EYE_LANDMARKS = [263, 387, 385, 362, 380, 373]  # same pattern for right eye

# Mouth landmarks for MediaPipe 468-point face mesh - standard academic approach
# Using proven landmarks from drowsiness detection research papers
MOUTH_LANDMARKS = [61, 291, 39, 181, 13, 14]          # Standard 6-point mouth landmarks for MAR


class LibCameraCapture:
    """Camera capture for Raspberry Pi using rpicam-vid"""
    
    def __init__(self, core, width=640, height=360, fps=30):
        self.core = core
        self.logger = core.get_logger("LibCameraCapture")
        self.width = width
        self.height = height
        self.fps = fps
        self.process = None
        self.running = False
        self.frame_data = None
        self.frame_lock = threading.Lock()
        self.frames_read = 0
        
    def start(self):
        """Start camera capture process"""
        try:
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
            
            self.logger.info(f"Starting camera: {self.width}x{self.height} at {self.fps}fps")
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.width * self.height * 3  # Larger buffer for better performance
            )
            
            self.running = True
            self.read_thread = threading.Thread(target=self._read_frames, daemon=True)
            self.read_thread.start()
            
            time.sleep(2)
            return True
            
        except Exception as e:
            self.logger.error(f"Camera start failed: {e}")
            return False
    
    def _read_frames(self):
        """Read frames from camera process"""
        frame_size = self.width * self.height * 3 // 2
        buffer = b''
        
        while self.running and self.process and self.process.poll() is None:
            try:
                chunk = self.process.stdout.read(8192)  # Larger chunks for better threading performance
                if not chunk:
                    time.sleep(0.01)
                    continue
                
                buffer += chunk
                
                while len(buffer) >= frame_size:
                    frame_data = buffer[:frame_size]
                    buffer = buffer[frame_size:]
                    
                    try:
                        yuv_array = np.frombuffer(frame_data, dtype=np.uint8)
                        yuv_frame = yuv_array.reshape((self.height * 3 // 2, self.width))
                        bgr_frame = cv2.cvtColor(yuv_frame, cv2.COLOR_YUV2BGR_I420)
                        
                        with self.frame_lock:
                            self.frame_data = bgr_frame.copy()
                            self.frames_read += 1
                            
                    except Exception as e:
                        continue
                        
            except Exception as e:
                if self.running:
                    time.sleep(0.01)
    
    def read(self):
        """Read current frame"""
        with self.frame_lock:
            if self.frame_data is not None:
                return True, self.frame_data.copy()
            else:
                return False, None
    
    def get_frame_count(self):
        """Get total frames read"""
        return self.frames_read
    
    def release(self):
        """Release camera resources"""
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

class VisionProcessor:
    """Advanced fatigue detection service with prolonged eye closure and rate-based metrics"""
    
    def __init__(self):
        # Initialize CogniCore
        self.core = CogniCore(SERVICE_NAME)
        self.logger = self.core.get_logger(SERVICE_NAME)
        
        self.camera = None
        self.face_mesh = None
        self.running = False
        self.pilot_profile = None
        self.last_heartbeat = 0
        
        # Eye closure detection thresholds
        self.eye_closure_threshold = 0.20  # EAR threshold for closed eyes
        self.drowsy_closure_threshold = 0.15  # Lower threshold for drowsiness
        self.microsleep_threshold = 1.0  # Seconds for microsleep detection
        self.prolonged_closure_threshold = 3.0  # Seconds for prolonged closure
        
        # Eye state tracking
        self.eyes_closed_start = None
        self.current_closure_duration = 0.0
        self.total_closure_time = 0.0  # Total time eyes closed in window
        self.microsleep_count = 0
        self.prolonged_closure_count = 0
        
        # Blink detection and rate calculation
        self.blink_count = 0
        self.last_blink_time = 0
        self.blink_timestamps = []  # Track blink times for rate calculation
        self.eye_state = "open"  # "open", "closing", "closed"
        self.last_ear_state = "open"
        
        # Yawn detection - simplified
        self.yawn_threshold = 0.6  # MAR threshold for yawn detection
        
        
        # Baseline values
        self.baseline_ear = 0.25
        self.baseline_mar = 0.03
        
        # Face detection quality
        self.face_detected_count = 0
        self.face_lost_count = 0
        
        # Face detection tracking
        self.face_width = 100
        self.face_height = 100
        
        # Watchdog and recovery mechanisms - FIXED TIMEOUT
        self.last_frame_time = 0
        self.last_processing_time = 0
        self.processing_watchdog_timeout = 30  # INCREASED from 10 to 30 seconds to prevent restart loop
        self.consecutive_errors = 0
        self.max_consecutive_errors = 15  # Increased tolerance
        
        # Initialize timing
        self.session_start_time = time.time()
        self.last_reset_time = time.time()
        self.reset_interval = 300.0  # Reset counters every 5 minutes
        
        # Setup reactive subscriptions
        self.setup_subscriptions()
    
    def setup_subscriptions(self):
        """Setup CogniCore subscriptions for reactive pilot detection and state management"""
        try:
            # Subscribe to pilot changes - will set up subscriptions for specific pilots
            # For now, subscribe to any pilot changes we find
            existing_pilots = self.core.list_pilots()
            self.logger.info(f"Found {len(existing_pilots)} existing pilots: {existing_pilots}")
            for pilot_id in existing_pilots:
                try:
                    self.core.subscribe_to_data(f"pilot:{pilot_id}", self.handle_pilot_change)
                    self.logger.debug(f"Subscribed to pilot:{pilot_id} changes")
                except Exception as e:
                    self.logger.warning(f"Failed to subscribe to pilot {pilot_id}: {e}")
            
            # Subscribe to system state changes (for error handling and face recognition restart detection)
            self.core.subscribe_to_state_changes(self.handle_state_change)
            
            self.logger.info("Subscribed to pilot profile and state changes for reactive processing")
            
        except Exception as e:
            self.logger.error(f"Failed to setup subscriptions: {e}")
    
    def handle_pilot_change(self, hash_name: str, data: Dict[str, Any]):
        """
        Reactive handler for pilot changes via CogniCore subscriptions.
        Starts vision processing when pilot becomes active, stops when deactivated.
        """
        try:
            pilot_id = data.get('pilot_id') if data else None
            is_active = data.get('active', False) if data else False
            
            if pilot_id and is_active and not self.running:
                # Pilot activated - start vision processing
                self.logger.info(f"🚀 Pilot activated: {pilot_id} - starting vision processing")
                self.start_processing_for_pilot(pilot_id)
                
            elif pilot_id and not is_active and self.running:
                # Pilot deactivated - handover camera to face recognition
                self.logger.info(f"✋ Pilot deactivated: {pilot_id} - handing camera to face recognition")
                self.handover_camera_to_face_recognition()
                
            elif pilot_id and is_active and self.running:
                # Check if active pilot changed to different pilot
                current_pilot = self.pilot_profile.get('pilot_id') if self.pilot_profile else None
                if pilot_id != current_pilot:
                    self.logger.info(f"🔄 Active pilot changed: {current_pilot} → {pilot_id}")
                    self.stop_processing()
                    self.start_processing_for_pilot(pilot_id)
                
        except Exception as e:
            self.logger.error(f"Error handling pilot change: {e}")
    
    def handle_state_change(self, state_data: Dict[str, Any]):
        """Handle system state changes for intelligent processing management during errors"""
        try:
            state = state_data.get('state')
            
            # Pause processing during system errors
            if state in ['system_error', 'system_crashed'] and self.running:
                self.logger.warning(f"System state {state} - pausing vision processing")
                self.running = False
                
            # Resume processing when back to normal (if pilot still active)
            elif state in ['monitoring_active', 'scanning'] and not self.running:
                active_pilot = self.core.get_active_pilot()
                if active_pilot and self.pilot_profile:
                    self.logger.info(f"System recovered - resuming vision processing")
                    self.running = True
                    
        except Exception as e:
            self.logger.error(f"Error handling state change: {e}")
    
    def handover_camera_to_face_recognition(self):
        """
        Hand over camera to face recognition service when active profile is cleared.
        This ensures face recognition can immediately start scanning for pilots.
        """
        try:
            self.logger.info("🔄 Active profile cleared - handing camera to face recognition")
            
            # Stop processing immediately when no active profile
            if self.running:
                self.logger.info("Stopping vision processing - no active profile")
                self.running = False
                
                # Release camera for face recognition with improved resource management
                if self.camera:
                    try:
                        self.camera.release()
                        self.logger.info("Camera released for face recognition to scan")
                    except Exception as e:
                        self.logger.warning(f"Error releasing camera during handover: {e}")
                    finally:
                        self.camera = None
                        # Longer delay to ensure camera resources are fully released
                        import time
                        time.sleep(1.5)
                
                # Clear pilot profile reference
                self.pilot_profile = None
                
                self.logger.info("✅ Camera handover completed - face recognition can scan")
                
        except Exception as e:
            self.logger.error(f"Error during camera handover: {e}")
    
    def start_processing_for_pilot(self, pilot_id: str):
        """Activate vision processing for the specified pilot with profile loading"""
        try:
            # Load pilot profile
            profile = self.load_pilot_profile()
            if not profile:
                self.logger.error(f"Failed to load profile for pilot: {pilot_id}")
                return False
            
            self.pilot_profile = profile
            self.running = True
            
            self.logger.info(f"✅ Vision processing started for pilot: {pilot_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start processing for pilot {pilot_id}: {e}")
            return False
    
    def stop_processing(self):
        """Stop vision processing and cleanup resources (camera, processing state)"""
        try:
            self.running = False
            self.pilot_profile = None
            
            # Stop camera
            if self.camera:
                self.camera.release()
                self.camera = None
            
            # Reset watchdog counters
            self.consecutive_errors = 0
            self.last_frame_time = 0
            self.last_processing_time = 0
            
            self.logger.info("🛑 Vision processing stopped and cleaned up")
            
        except Exception as e:
            self.logger.error(f"Error stopping processing: {e}")
    
    def _restart_camera(self):
        """Restart camera when it appears stuck or failed"""
        try:
            self.logger.info("🔄 Restarting camera due to issues...")
            
            # Release current camera with better resource management
            if self.camera:
                try:
                    self.camera.release() 
                except Exception as e:
                    self.logger.warning(f"Error releasing camera: {e}")
                finally:
                    self.camera = None
                    time.sleep(2.0)  # Longer wait for resources to be fully freed
            
            # Create new camera instance with retry logic
            retry_count = 0
            max_retries = 3
            
            while retry_count < max_retries:
                self.camera = LibCameraCapture(self.core, width=FRAME_WIDTH, height=FRAME_HEIGHT, fps=FPS)
                if self.camera.start():
                    self.logger.info("✅ Camera restart successful")
                    # Reset error counters
                    if hasattr(self, '_camera_error_count'):
                        self._camera_error_count = 0
                    if hasattr(self, '_no_frame_count'):
                        self._no_frame_count = 0
                    return True
                else:
                    retry_count += 1
                    self.logger.warning(f"Camera restart attempt {retry_count}/{max_retries} failed")
                    self.camera = None
                    if retry_count < max_retries:
                        time.sleep(2.0)
            
            self.logger.error("❌ Camera restart failed after multiple attempts")
            return False
            
        except Exception as e:
            self.logger.error(f"Error during camera restart: {e}")
            return False
    
    def _check_processing_watchdog(self, current_time):
        """Check if processing has stalled and attempt recovery"""
        try:
            # Check if we've processed any frames recently
            if self.last_processing_time > 0:
                time_since_processing = current_time - self.last_processing_time
                if time_since_processing > self.processing_watchdog_timeout:
                    self.logger.warning(f"Processing watchdog: No frames processed for {time_since_processing:.1f}s")
                    
                    # Attempt recovery
                    if self._restart_camera():
                        self.logger.info("Watchdog recovery: Camera restarted successfully")
                        self.last_processing_time = current_time
                    else:
                        self.logger.error("Watchdog recovery: Camera restart failed")
                        self.consecutive_errors += 1
                        
                        if self.consecutive_errors >= self.max_consecutive_errors:
                            self.logger.error("Too many consecutive errors - stopping processing")
                            self.running = False
            
        except Exception as e:
            self.logger.error(f"Watchdog check failed: {e}")
        
    def initialize_mediapipe(self):
        """Initialize MediaPipe face mesh with hardware acceleration while maintaining quality"""
        try:
            self.face_mesh = mp_face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,  # Keep full quality landmarks
                min_detection_confidence=0.5,  # Keep for good detection
                min_tracking_confidence=0.5   # Keep for good tracking
            )
            self.logger.info("MediaPipe face mesh initialized with hardware acceleration - full quality maintained")
            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize MediaPipe: {e}")
            return False
    
    def extract_landmarks(self, frame: np.ndarray) -> Optional[Dict[str, List[Tuple[float, float]]]]:
        """
        Extract facial landmarks from frame using MediaPipe.
        
        Args:
            frame: Input frame from camera
            
        Returns:
            Dictionary containing landmark coordinates for eyes and mouth
        """
        try:
            # Resize frame for faster processing while maintaining accuracy
            h, w = frame.shape[:2]
            scale_factor = 0.75  # Process at 75% size for speed
            small_h, small_w = int(h * scale_factor), int(w * scale_factor)
            small_frame = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_LINEAR)
            
            # Convert BGR to RGB for MediaPipe
            rgb_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            rgb_frame.flags.writeable = False  # Mark as read-only for performance
            results = self.face_mesh.process(rgb_frame)
            
            if not results.multi_face_landmarks:
                return None
            
            # Check if we have good detection quality
            face_landmarks = results.multi_face_landmarks[0]
            if len(face_landmarks.landmark) < 468:
                self.logger.warning("Incomplete face mesh detected")
                return None
            
            # Get first face landmarks
            face_landmarks = results.multi_face_landmarks[0]
            # Use original frame dimensions for accurate coordinate mapping
            
            # Calculate face dimensions for relative thresholds (scale back to original size)
            face_box = self._get_face_bounding_box(face_landmarks, w, h, scale_factor)
            if face_box:
                self.face_width = face_box[2] - face_box[0]
                self.face_height = face_box[3] - face_box[1]
            
            # Extract landmark coordinates
            landmarks = {}
            
            # Left eye landmarks
            left_eye = []
            for idx in LEFT_EYE_LANDMARKS:
                lm = face_landmarks.landmark[idx]
                x = int(lm.x * w)
                y = int(lm.y * h)
                left_eye.append((x, y))
            landmarks['left_eye'] = left_eye
            
            # Right eye landmarks
            right_eye = []
            for idx in RIGHT_EYE_LANDMARKS:
                lm = face_landmarks.landmark[idx]
                x = int(lm.x * w)
                y = int(lm.y * h)
                right_eye.append((x, y))
            landmarks['right_eye'] = right_eye
            
            # Mouth landmarks
            mouth = []
            for idx in MOUTH_LANDMARKS:
                lm = face_landmarks.landmark[idx]
                x = int(lm.x * w)
                y = int(lm.y * h)
                mouth.append((x, y))
            landmarks['mouth'] = mouth
            
            return landmarks
            
        except Exception as e:
            self.logger.error(f"Landmark extraction failed: {e}")
            return None
    
    def _get_face_bounding_box(self, face_landmarks, w, h, scale_factor=1.0):
        """Calculate face bounding box for relative thresholds, scaled back to original size"""
        try:
            # Scale coordinates back to original frame size
            x_coords = [lm.x * w / scale_factor for lm in face_landmarks.landmark]
            y_coords = [lm.y * h / scale_factor for lm in face_landmarks.landmark]
            
            min_x, max_x = min(x_coords), max(x_coords)
            min_y, max_y = min(y_coords), max(y_coords)
            
            return (min_x, min_y, max_x, max_y)
        except:
            return None
    
    
    
    
    def fast_ear_approximation(self, eye_landmarks: List[Tuple[float, float]]) -> float:
        """Fast EAR approximation - only essential calculations for speed"""
        try:
            if len(eye_landmarks) != 6:
                return self.baseline_ear
            
            points = eye_landmarks
            
            # Simple vertical/horizontal ratio (much faster than full EAR)
            vertical_dist = abs(points[1][1] - points[5][1]) + abs(points[2][1] - points[4][1])
            horizontal_dist = abs(points[0][0] - points[3][0])
            
            if horizontal_dist > 0:
                ear = vertical_dist / (2.0 * horizontal_dist)
                # Simple bounds check
                return max(0.05, min(0.6, ear))
            else:
                return self.baseline_ear
                
        except Exception:
            return self.baseline_ear
    
    def reset_counters_if_needed(self, current_time: float):
        """Simple counter reset every 5 minutes"""
        if current_time - self.last_reset_time >= self.reset_interval:
            self.microsleep_count = 0
            self.blink_count = 0
            self.last_reset_time = current_time

    
    
    def process_frame(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Advanced frame processing with fatigue detection metrics for predictor service.
        
        Args:
            frame: Input frame from camera
            
        Returns:
            Dictionary containing advanced fatigue metrics for predictor fusion
        """
        current_time = time.time()
        
        # Reset counters periodically to prevent infinite accumulation
        self.reset_counters_if_needed(current_time)
        
        landmarks = self.extract_landmarks(frame)
        if not landmarks:
            self.face_lost_count += 1
            self.face_detected_count = 0
            
            # Show face lost message after a few consecutive failures
            if self.face_lost_count == 5:
                self.logger.info("Face detection lost - please position yourself in front of camera")
            
            return None
        else:
            self.face_detected_count += 1
            # If we just recovered face detection, show confirmation
            if self.face_lost_count >= 5:
                self.logger.info("Face detection recovered")
            self.face_lost_count = 0
        
        # Extract eye landmark coordinates only (LEAN - focus on highest value)
        left_eye = landmarks.get("left_eye", [])
        right_eye = landmarks.get("right_eye", [])
        
        if not left_eye or not right_eye:
            return None
        
        # LEAN CALCULATIONS - Fast approximations instead of complex formulas
        
        # Fast EAR approximation (sufficient for fatigue detection)
        left_ear = self.fast_ear_approximation(left_eye)
        right_ear = self.fast_ear_approximation(right_eye)
        avg_ear = (left_ear + right_ear) / 2.0
        
        # Validate EAR
        if avg_ear < 0 or avg_ear > 1:
            avg_ear = self.baseline_ear
        
        # LEAN APPROACH - Only highest-value indicators
        
        # 1. EAR-based eye state (most reliable indicator)
        eyes_closed = avg_ear < self.eye_closure_threshold
        
        # 2. Simple blink counting
        if not eyes_closed and self.eye_state == "closed":
            self.blink_count += 1
            self.last_blink_time = current_time
        
        # 3. Eye closure duration tracking (critical for microsleeps)
        if eyes_closed:
            if self.eye_state == "open":
                self.eyes_closed_start = current_time
            self.eye_state = "closed"
            self.current_closure_duration = (current_time - self.eyes_closed_start) if self.eyes_closed_start else 0.0
            # Count microsleeps
            if self.current_closure_duration >= 1.0 and not hasattr(self, '_microsleep_detected'):
                self.microsleep_count += 1
                self._microsleep_detected = True
        else:
            self.eye_state = "open"
            self.current_closure_duration = 0.0
            if hasattr(self, '_microsleep_detected'):
                delattr(self, '_microsleep_detected')
        
        # 4. Basic blink rate (simple calculation)
        blink_rate = self.blink_count * 2.0 if current_time - self.session_start_time > 30 else 0.0
        
        # LEAN OUTPUT - Only highest-value measurements
        processed_data = {
            "timestamp": current_time,
            
            # Primary fatigue indicator (most reliable)
            "avg_ear": float(round(avg_ear, 3)),
            
            # Critical safety indicators
            "eyes_closed": bool(eyes_closed),
            "closure_duration": float(round(self.current_closure_duration, 1)),
            "microsleep_count": int(self.microsleep_count),
            
            # Behavioral pattern (simple but effective)
            "blink_rate_per_minute": float(round(blink_rate, 0))
        }
        
        # Log critical observations only
        if self.current_closure_duration >= self.microsleep_threshold:
            self.logger.warning(f"⚠️  Extended eye closure: {self.current_closure_duration:.1f}s")
        
        if self.microsleep_count > 0 and self.microsleep_count % 3 == 0:
            self.logger.warning(f"🚨 Multiple microsleeps: {self.microsleep_count} events")
        
        return processed_data
    
    def load_pilot_profile(self):
        """Load pilot profile from CogniCore"""
        try:
            profile = self.core.get_active_pilot_profile()
            if profile:
                self.logger.info(f"Loaded pilot profile: {profile.id}")
                return {
                    "pilot_id": profile.id,
                    "name": profile.name,
                    "flightHours": profile.flightHours,
                    "baseline": profile.baseline,
                    "environmentPreferences": profile.environmentPreferences
                }
            else:
                self.logger.debug("No active pilot profile found")
                return None
            
        except Exception as e:
            self.logger.error(f"Failed to load pilot profile from CogniCore: {e}")
            return None
    
    def check_initial_pilot_state(self):
        """One-time startup check for existing active pilot to initialize processing state"""
        try:
            # Give Redis/services time to stabilize after startup
            import time
            time.sleep(2)
            
            # Check for any active pilot using new system
            active_pilot_id = self.core.get_active_pilot()
            
            if active_pilot_id:
                self.logger.info(f"🔄 Startup: Found active pilot {active_pilot_id} - initializing processing")
                
                # Verify pilot profile exists before starting
                profile = self.core.get_pilot_profile(active_pilot_id)
                if profile:
                    self.start_processing_for_pilot(active_pilot_id)
                else:
                    self.logger.warning(f"Active pilot {active_pilot_id} profile missing - requesting profile")
                    # Request profile reload
                    self.core.publish_data('pilot_id_request', {
                        'pilot_id': active_pilot_id,
                        'source': 'vision_startup'
                    })
            else:
                self.logger.info("No active pilot found on startup - waiting for pilot changes")
                
        except Exception as e:
            self.logger.error(f"Error checking initial pilot state: {e}")
            # Continue running even if initial check fails
            self.logger.info("Continuing with reactive mode - will detect pilot changes")
    
    def handle_system_commands(self):
        """Handle system commands - currently unused, reactive subscriptions handle coordination"""
        pass
    
    def run(self):
        """Main vision processing service loop with reactive pilot detection and efficient resource usage"""
        self.logger.info("Vision Processing service starting...")
        
        # Initialize MediaPipe
        if not self.initialize_mediapipe():
            self.logger.error("Failed to initialize MediaPipe")
            return
        
        # Notify systemd that service is ready
        systemd.daemon.notify('READY=1')
        self.logger.info("Notified systemd that service is ready")
        
        # Check for existing pilot on startup (one-time initialization)
        self.check_initial_pilot_state()
        
        # Main service loop - reactive design, events drive processing activation
        while True:
            try:
                current_time = time.time()
                
                # Send watchdog notification
                if current_time - self.last_heartbeat >= HEARTBEAT_INTERVAL:
                    systemd.daemon.notify('WATCHDOG=1')
                    self.last_heartbeat = current_time
                
                # Check processing watchdog
                if self.running:
                    self._check_processing_watchdog(current_time)
                
                if self.running:
                    # Start camera if not already started
                    if not self.camera:
                        self.logger.info("Creating camera capture instance...")
                        
                        # Add retry logic for camera startup robustness
                        retry_count = 0
                        max_retries = 3
                        camera_started = False
                        
                        while retry_count < max_retries and not camera_started:
                            self.camera = LibCameraCapture(self.core, width=FRAME_WIDTH, height=FRAME_HEIGHT, fps=FPS)
                            self.logger.info(f"Attempting to start camera (attempt {retry_count + 1}/{max_retries})...")
                            
                            if self.camera.start():
                                self.logger.info("Camera started successfully")
                                camera_started = True
                            else:
                                retry_count += 1
                                self.logger.warning(f"Camera start attempt {retry_count}/{max_retries} failed")
                                self.camera = None
                                if retry_count < max_retries:
                                    self.logger.info("Waiting before retry...")
                                    time.sleep(2.0)  # Wait before retry
                        
                        if not camera_started:
                            self.logger.error("Failed to start camera after multiple attempts")
                            self.running = False
                            continue
                    
                    # Process frames with improved timing and error handling
                    try:
                        ret, frame = self.camera.read()
                        if ret and frame is not None:
                            self.logger.debug("Frame received from camera")
                            # Update last frame received time for watchdog
                            self.last_frame_time = current_time
                            
                            # Process frame and compute EAR/MAR with timeout protection
                            try:
                                processed_data = self.process_frame(frame)
                            except Exception as e:
                                self.logger.error(f"Frame processing failed: {e}")
                                processed_data = None
                                # Try to recover by reinitializing MediaPipe
                                self.logger.info("Attempting to recover by reinitializing MediaPipe...")
                                if self.initialize_mediapipe():
                                    self.logger.info("MediaPipe recovery successful")
                                else:
                                    self.logger.error("MediaPipe recovery failed")
                                continue
                        
                        if processed_data:
                            # Only log significant fatigue events, not every frame
                            
                            # Update processing watchdog - successful processing
                            self.last_processing_time = current_time
                            self.consecutive_errors = 0  # Reset error counter on success
                            
                            # Publish vision data to CogniCore
                            try:
                                self.core.publish_data("vision", processed_data)
                                self.logger.debug("Vision data published to CogniCore")
                            except Exception as e:
                                self.logger.error(f"Failed to publish vision data: {e}")
                                self.logger.debug("Failed to publish vision data to CogniCore Redis")
                        else:
                            # Update processing counters for watchdog
                            if not hasattr(self, '_no_face_count'):
                                self._no_face_count = 0
                            self._no_face_count += 1
                            if self._no_face_count % 150 == 0:  # Log every 150 frames (~5 seconds) - less verbose
                                self.logger.debug(f"No face detected in frame (count: {self._no_face_count})")
                        
                    except Exception as e:
                        self.logger.error(f"Camera read failed: {e}")
                        # Camera error - attempt recovery
                        if not hasattr(self, '_camera_error_count'):
                            self._camera_error_count = 0
                        self._camera_error_count += 1
                        
                        if self._camera_error_count >= 5:
                            self.logger.error("Multiple camera errors - attempting camera restart")
                            self._restart_camera()
                            self._camera_error_count = 0
                        
                        time.sleep(0.5)  # Wait before retry
                        continue
                        
                    else:
                        # No frame received - camera might be stuck
                        if not hasattr(self, '_no_frame_count'):
                            self._no_frame_count = 0
                        self._no_frame_count += 1
                        
                        if self._no_frame_count % 30 == 0:  # Log every 30 frames
                            self.logger.debug(f"No frame received from camera (count: {self._no_frame_count})")
                        
                        # If we haven't received frames for too long, restart camera
                        if self._no_frame_count >= 450:  # 15 seconds at 30fps - much more tolerant
                            self.logger.error("Camera appears stuck - attempting restart")
                            self._restart_camera()
                            self._no_frame_count = 0
                    
                    # Minimal delay for real-time responsiveness
                    if self.face_lost_count > 10:
                        time.sleep(0.01)  # Very fast processing when no face
                    else:
                        time.sleep(0.005)  # Ultra-fast processing for real-time response
                    
                else:
                    # Not running - release camera if active
                    if self.camera:
                        self.camera.release()
                        self.camera = None
                    
                    time.sleep(0.1)  # Small delay when not processing
                    
            except KeyboardInterrupt:
                self.logger.info("Vision Processing service stopping...")
                break
            except Exception as e:
                self.logger.exception(f"Vision Processing error: {e}")
                self.consecutive_errors += 1
                
                # Graceful recovery attempt
                if self.consecutive_errors <= 3:
                    self.logger.info(f"Attempting graceful recovery (attempt {self.consecutive_errors}/3)...")
                    try:
                        # Try to restart camera and reinitialize MediaPipe
                        if self.camera:
                            self.camera.release()
                            self.camera = None
                        
                        if self.initialize_mediapipe():
                            self.logger.info("MediaPipe reinitialized successfully")
                        
                        # Reset some error counters
                        if hasattr(self, '_camera_error_count'):
                            self._camera_error_count = 0
                        if hasattr(self, '_no_frame_count'):
                            self._no_frame_count = 0
                            
                        time.sleep(2)  # Wait before retry
                        
                    except Exception as recovery_error:
                        self.logger.error(f"Recovery attempt failed: {recovery_error}")
                        time.sleep(5)
                else:
                    self.logger.error("Too many consecutive errors - stopping service gracefully")
                    self.running = False
                    break
        
        # Cleanup
        if self.camera:
            self.camera.release()

def main():
    """Main vision processing entry point"""
    processor = VisionProcessor()
    processor.run()

if __name__ == "__main__":
    main()