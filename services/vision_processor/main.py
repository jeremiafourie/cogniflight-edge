"""
Unified Vision Processor Service
Handles both pilot authentication and fatigue monitoring without camera handover
"""
import os
import sys
import time
import json
import threading
import logging
import numpy as np
from pathlib import Path
from typing import Optional, Dict, Any
import systemd.daemon

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# Import vision processing modules
from camera.manager import CameraManager
from processors.authenticator import AuthenticatorProcessor
from processors.fatigue_detector import FatigueDetectorProcessor

# Import external dependencies
import mediapipe as mp
from insightface.app import FaceAnalysis

# Import CogniCore
from CogniCore import CogniCore, SystemState

# Configuration from environment variables
SERVICE_NAME = "vision_processor"
HEARTBEAT_INTERVAL = int(os.getenv('HEARTBEAT_INTERVAL', '5'))

# Camera Configuration
CAMERA_WIDTH = int(os.getenv('CAMERA_WIDTH', '640'))
CAMERA_HEIGHT = int(os.getenv('CAMERA_HEIGHT', '360'))
CAMERA_FPS = int(os.getenv('CAMERA_FPS', '30'))

# Authentication Configuration
RECOGNITION_THRESHOLD = float(os.getenv('RECOGNITION_THRESHOLD', '0.4'))
FACE_DETECTION_THRESHOLD = float(os.getenv('FACE_DETECTION_THRESHOLD', '0.5'))
FACE_MODEL_NAME = os.getenv('FACE_MODEL_NAME', 'buffalo_s')

# Processing Configuration
PROCESS_EVERY_NTH_FRAME_AUTH = int(os.getenv('PROCESS_EVERY_NTH_FRAME_AUTH', '5'))
PROCESS_EVERY_NTH_FRAME_FATIGUE = int(os.getenv('PROCESS_EVERY_NTH_FRAME_FATIGUE', '1'))

# Timing Configuration
EMBEDDING_REFRESH_INTERVAL = int(os.getenv('EMBEDDING_REFRESH_INTERVAL', '300'))  # 5 minutes
PILOT_REQUEST_TIMEOUT = int(os.getenv('PILOT_REQUEST_TIMEOUT', '30'))
STATUS_LOG_INTERVAL = int(os.getenv('STATUS_LOG_INTERVAL', '30'))


class UnifiedVisionService:
    """
    Unified vision service that handles both authentication and fatigue monitoring.
    Switches between modes based on pilot active status.
    """

    def __init__(self):
        # Initialize CogniCore
        self.core = CogniCore(SERVICE_NAME)
        self.logger = self.core.get_logger(SERVICE_NAME)

        # Service state
        self.running = False
        self.current_mode = "authentication"  # "authentication" or "monitoring"
        self.active_pilot = None
        self.pilot_request_pending = False
        self.last_pilot_request_time = 0

        # Face loss tracking for auto-deauthentication
        self.last_face_seen_time = time.time()
        self.face_loss_timeout = 10.0  # Deauthenticate after 10 seconds of no face

        # Statistics
        self.frames_processed = 0
        self.last_status_log = time.time()
        self.last_heartbeat = time.time()
        self.last_embedding_refresh = time.time()

        # Initialize components (will be created in run())
        self.camera = None
        self.authenticator = None
        self.fatigue_detector = None
        self.face_analyzer = None
        self.face_mesh = None

        # Pilot embeddings
        self.pilot_embeddings = {}

        # Setup subscriptions
        self.setup_subscriptions()

    def setup_subscriptions(self):
        """Setup CogniCore subscriptions for pilot changes"""
        try:
            # Subscribe to pilot changes
            existing_pilots = self.core.list_pilots()
            self.logger.info(f"Found {len(existing_pilots)} existing pilots")
            for pilot_username in existing_pilots:
                try:
                    self.core.subscribe_to_data(f"pilot:{pilot_username}", self.handle_pilot_change)
                    self.logger.debug(f"Subscribed to pilot:{pilot_username} changes")
                except Exception as e:
                    self.logger.warning(f"Failed to subscribe to pilot {pilot_username}: {e}")

            # Subscribe to pilot_id_request changes
            self.core.subscribe_to_data("pilot_id_request", self.handle_pilot_request_change)

            # Subscribe to system state changes
            self.core.subscribe_to_state_changes(self.handle_state_change)

            self.logger.info("Subscriptions setup complete")

        except Exception as e:
            self.logger.error(f"Failed to setup subscriptions: {e}")

    def handle_pilot_change(self, hash_name: str, data: Dict[str, Any]):
        """Handle pilot data changes - switch modes based on authenticated status"""
        try:
            pilot_username = data.get('pilot_username') if data else None
            is_authenticated = data.get('authenticated', False) if data else False

            if pilot_username and is_authenticated and self.current_mode == "authentication":
                # Pilot authenticated - switch to monitoring mode
                self.logger.info(f"Pilot {pilot_username} authenticated - switching to monitoring mode")
                self.active_pilot = pilot_username
                self.current_mode = "monitoring"
                self.pilot_request_pending = False

                # Reset fatigue detector for new session
                if self.fatigue_detector:
                    self.fatigue_detector.reset()

            elif pilot_username and not is_authenticated and self.active_pilot == pilot_username:
                # Authenticated pilot deauthenticated - switch back to authentication
                self.logger.info(f"Pilot {pilot_username} deauthenticated - switching to authentication mode")
                self.active_pilot = None
                self.current_mode = "authentication"

        except Exception as e:
            self.logger.error(f"Error handling pilot change: {e}")

    def handle_pilot_request_change(self, hash_name: str, data: Dict[str, Any]):
        """Handle pilot_id_request changes"""
        if data is None:
            # Request was cleared
            self.pilot_request_pending = False

    def handle_state_change(self, state_data: Dict[str, Any]):
        """Handle system state changes"""
        try:
            state = state_data.get('state')

            # Handle system errors
            if state in ['system_error', 'system_crashed'] and self.running:
                self.logger.warning(f"System state {state} - pausing processing")
                self.running = False

            # Resume when system recovers
            elif state in ['monitoring_active', 'scanning'] and not self.running:
                if self.active_pilot and self.current_mode == "monitoring":
                    self.logger.info("System recovered - resuming processing")
                    self.running = True

        except Exception as e:
            self.logger.error(f"Error handling state change: {e}")

    def load_pilot_embeddings(self):
        """Load pilot face embeddings from Redis"""
        try:
            embeddings = {}

            # Get all pilot usernames
            pilots = self.core.list_pilots()

            # Also check for embedding keys directly
            redis_client = self.core._redis_client
            try:
                embedding_keys = redis_client.keys("cognicore:data:embedding:*")
            except Exception as e:
                self.logger.warning(f"Failed to get embedding keys: {e}")
                embedding_keys = []

            all_pilot_usernames = set(pilots)
            for key in embedding_keys:
                if isinstance(key, bytes):
                    pilot_username = key.decode().split(":")[-1]
                else:
                    pilot_username = key.split(":")[-1]
                all_pilot_usernames.add(pilot_username)

            # Load each embedding
            for pilot_username in all_pilot_usernames:
                try:
                    # Updated to use direct Redis GET instead of HGETALL
                    # Embeddings are now stored as: SET cognicore:data:embedding:{pilot_username} <json_array>
                    embedding_key = f"cognicore:data:embedding:{pilot_username}"
                    embedding_json = redis_client.get(embedding_key)

                    if embedding_json:
                        # Decode bytes to string if necessary
                        if isinstance(embedding_json, bytes):
                            embedding_json = embedding_json.decode('utf-8')

                        # Parse JSON string to get the embedding array
                        embedding = json.loads(embedding_json)
                        embedding_array = np.array(embedding, dtype=np.float32)

                        # Normalize embedding
                        from processors.authenticator import normalize_embedding
                        embedding_array = normalize_embedding(embedding_array)

                        embeddings[pilot_username] = embedding_array
                        self.logger.debug(f"Loaded embedding for pilot {pilot_username} (shape: {embedding_array.shape})")
                except Exception as e:
                    self.logger.warning(f"Failed to load embedding for {pilot_username}: {e}")

            self.logger.info(f"Loaded {len(embeddings)} pilot embeddings")
            return embeddings

        except Exception as e:
            self.logger.error(f"Failed to load embeddings: {e}")
            return {}

    def initialize_models(self):
        """Initialize face analysis models"""
        try:
            # Initialize InsightFace for authentication
            self.logger.info("Initializing face analysis model...")
            self.face_analyzer = FaceAnalysis(name=FACE_MODEL_NAME, providers=["CPUExecutionProvider"])
            systemd.daemon.notify('WATCHDOG=1')  # Keep watchdog happy during initialization
            self.face_analyzer.prepare(ctx_id=0, det_size=(640, 640))
            self.logger.info("Face analyzer initialized")

            # Initialize MediaPipe for fatigue detection
            self.logger.info("Initializing MediaPipe face mesh...")
            self.face_mesh = mp.solutions.face_mesh.FaceMesh(
                static_image_mode=False,
                max_num_faces=1,
                refine_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
            self.logger.info("MediaPipe face mesh initialized")

            return True

        except Exception as e:
            self.logger.error(f"Failed to initialize models: {e}")
            return False

    def process_authentication_frame(self, frame, frame_count):
        """Process frame for authentication"""
        # Process every Nth frame for authentication
        if frame_count % PROCESS_EVERY_NTH_FRAME_AUTH != 0:
            return

        result = self.authenticator.process_frame(frame)

        if not result['face_detected']:
            # No face detected
            if frame_count % 150 == 0:  # Log every ~5 seconds
                self.core.set_system_state(SystemState.SCANNING, "Scanning...\nCabin Empty")

        elif result['pilot_username']:
            # Known pilot recognized
            pilot_username = result['pilot_username']
            confidence = result['confidence']
            self.logger.info(f"Pilot identified: {pilot_username} (confidence: {confidence:.3f})")

            # Check if request already pending
            if not self.pilot_request_pending:
                # Send pilot username request
                self.core.set_system_state(SystemState.SCANNING, f"Welcome {pilot_username}\nFetching profile")

                # CRITICAL FIX FOR RACE CONDITION:
                # Subscribe BEFORE publishing request to ensure we receive the event
                # This prevents missing the authentication update if HTTPS client is very fast
                self.core.subscribe_to_data(f"pilot:{pilot_username}", self.handle_pilot_change)
                self.logger.debug(f"Subscribed to pilot:{pilot_username} updates")

                # Publish request - HTTPS client will update pilot hash which triggers our subscription
                request_data = {
                    "pilot_username": pilot_username,
                    "confidence": float(confidence),
                    "timestamp": time.time(),
                    "source": "vision_processor"
                }

                self.core.publish_data("pilot_id_request", request_data)
                self.logger.info("Profile request sent to HTTPS client")

                self.pilot_request_pending = True
                self.last_pilot_request_time = time.time()

        else:
            # Unknown face detected
            if result['face_detected']:
                self.logger.info(f"Unknown face detected (confidence: {result['confidence']:.3f})")
                self.core.set_system_state(SystemState.INTRUDER_DETECTED, "WARNING\nIntruder Alert")

    def process_monitoring_frame(self, frame, frame_count):
        """Process frame for fatigue monitoring"""
        # Process every Nth frame for fatigue
        if frame_count % PROCESS_EVERY_NTH_FRAME_FATIGUE != 0:
            return

        fatigue_data = self.fatigue_detector.process_frame(frame)

        if fatigue_data:
            # Check if face is actually detected
            if fatigue_data.get('face_detected', False):
                self.last_face_seen_time = time.time()
                # Publish fatigue data
                self.core.publish_data("vision", fatigue_data)
            else:
                # No face detected - check for timeout
                time_since_face = time.time() - self.last_face_seen_time
                if time_since_face > self.face_loss_timeout and self.active_pilot:
                    # Face lost for too long - mark flight finished and deauthenticate
                    self.logger.info(f"Face lost for {time_since_face:.1f}s - marking flight finished and deauthenticating {self.active_pilot}")

                    # First mark the flight as finished
                    self.core.set_flight_finished(self.active_pilot, True, f"face_lost_after_{time_since_face:.1f}s")

                    # Then deauthenticate the pilot
                    self.core.set_pilot_authenticated(self.active_pilot, False)
                    self.current_mode = "authentication"
                    self.active_pilot = None
                    self.core.set_system_state(SystemState.SCANNING, "Scanning for\nPilot...")
                    return

            # Log vision data only when face is detected
            if fatigue_data.get('face_detected', False):
                timestamp = time.strftime("%H:%M:%S", time.localtime(fatigue_data.get('timestamp', time.time())))

                # Log every 30th frame to avoid spam (roughly once per second at 30fps)
                if self.frames_processed % 30 == 0:
                    log_msg = (f"VISION[{timestamp}]: "
                              f"EAR={fatigue_data.get('avg_ear', 0):.3f} "
                              f"MAR={fatigue_data.get('mar', 0):.3f} "
                              f"Eyes_Closed={int(fatigue_data.get('eyes_closed', False))} "
                              f"Closure_Dur={fatigue_data.get('closure_duration', 0):.1f}s "
                              f"Microsleep_Count={fatigue_data.get('microsleep_count', 0)} "
                              f"Blink_Rate={fatigue_data.get('blink_rate_per_minute', 0):.0f} "
                              f"Yawning={int(fatigue_data.get('yawning', False))} "
                              f"Yawn_Count={fatigue_data.get('yawn_count', 0)} "
                              f"Yawn_Dur={fatigue_data.get('yawn_duration', 0):.1f}s "
                              f"Face_Detected={int(fatigue_data.get('face_detected', False))} "
                              f"X={fatigue_data.get('face_offset_x', 0):.2f} "
                              f"Y={fatigue_data.get('face_offset_y', 0):.2f}")
                    self.logger.info(log_msg)

            # Log warnings for critical conditions
            if fatigue_data.get('closure_duration', 0) >= 1.0:
                self.logger.warning(f"Extended eye closure: {fatigue_data['closure_duration']:.1f}s")

            if fatigue_data.get('microsleep_count', 0) > 0 and fatigue_data['microsleep_count'] % 3 == 0:
                self.logger.warning(f"Multiple microsleeps: {fatigue_data['microsleep_count']}")

    def run(self):
        """Main service loop"""
        self.logger.info("Unified Vision Processor starting...")

        # Deauthenticate all pilots on startup (like authenticator did)
        try:
            self.core.deauthenticate_all_pilots()
            self.logger.info("Deauthenticated all pilots on startup")
        except Exception as e:
            self.logger.debug(f"Failed to deauthenticate pilots: {e}")

        # Initialize models
        if not self.initialize_models():
            self.logger.error("Failed to initialize models")
            return

        # Initialize camera manager
        self.camera = CameraManager(self.logger, CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS)
        if not self.camera.start():
            self.logger.error("Failed to start camera")
            return

        # Initialize processors
        self.authenticator = AuthenticatorProcessor(self.face_analyzer, self.logger)
        self.fatigue_detector = FatigueDetectorProcessor(self.face_mesh, self.logger)

        # Load initial embeddings
        self.pilot_embeddings = self.load_pilot_embeddings()
        self.authenticator.update_embeddings(self.pilot_embeddings)

        # Notify systemd that service is ready
        systemd.daemon.notify('READY=1')
        self.logger.info("Service ready and running")

        # Set initial state
        self.core.set_system_state(SystemState.SCANNING, "Scanning for\nPilot...")

        # Main processing loop
        self.running = True
        frame_count = 0

        while self.running:
            try:
                current_time = time.time()

                # Send watchdog notification
                if current_time - self.last_heartbeat >= HEARTBEAT_INTERVAL:
                    systemd.daemon.notify('WATCHDOG=1')
                    self.last_heartbeat = current_time

                # Refresh embeddings periodically
                if current_time - self.last_embedding_refresh > EMBEDDING_REFRESH_INTERVAL:
                    self.logger.info("Refreshing pilot embeddings...")
                    new_embeddings = self.load_pilot_embeddings()
                    if new_embeddings:
                        self.pilot_embeddings = new_embeddings
                        self.authenticator.update_embeddings(new_embeddings)
                    self.last_embedding_refresh = current_time

                # Check pilot request timeout
                if self.pilot_request_pending and current_time - self.last_pilot_request_time > PILOT_REQUEST_TIMEOUT:
                    self.logger.warning("Pilot request timed out")
                    self.pilot_request_pending = False

                # Get frame from camera
                ret, frame = self.camera.read()
                if not ret or frame is None:
                    time.sleep(0.01)
                    continue

                frame_count += 1
                self.frames_processed += 1

                # Process frame based on current mode
                if self.current_mode == "authentication":
                    self.process_authentication_frame(frame, frame_count)
                elif self.current_mode == "monitoring":
                    self.process_monitoring_frame(frame, frame_count)

                # Status logging
                if current_time - self.last_status_log > STATUS_LOG_INTERVAL:
                    camera_frames = self.camera.get_frame_count()
                    self.logger.info(f"Status - Mode: {self.current_mode}, Camera: {camera_frames}, "
                                   f"Processed: {self.frames_processed}, Active pilot: {self.active_pilot}")
                    self.last_status_log = current_time

                    # Update adaptive threshold for authentication
                    if self.current_mode == "authentication":
                        self.authenticator.update_adaptive_threshold()

                # Small delay for CPU efficiency
                time.sleep(0.005)

            except KeyboardInterrupt:
                self.logger.info("Service interrupted by user")
                break
            except Exception as e:
                self.logger.error(f"Processing error: {e}")
                time.sleep(0.1)

        # Cleanup
        self.logger.info("Shutting down service...")
        if self.camera:
            self.camera.stop()
        self.core.shutdown()
        self.logger.info("Service shutdown complete")


def main():
    """Main entry point"""
    service = UnifiedVisionService()
    service.run()


if __name__ == "__main__":
    main()