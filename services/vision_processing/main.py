import cv2
import numpy as np
import mediapipe as mp
import math
import time
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# Add project root to path for imports (comment out if not needed)
# sys.path.append(str(Path(__file__).parent.parent.parent))

# Try to import CogniCore, fallback to mock if not available
try:
    from CogniCore import CogniCore
    COGNICORE_AVAILABLE = True
except ImportError:
    COGNICORE_AVAILABLE = False
    print("CogniCore not available - using mock mode")

# Configuration
SERVICE_NAME = "vision_processing"
FRAME_WIDTH = 640
FRAME_HEIGHT = 480
FPS = 30


class MockCore:
    """Mock CogniCore for testing without Redis"""

    def __init__(self, service_name):
        self.service_name = service_name
        self.active_pilot = "test_pilot_123"

    def get_logger(self, name):
        return MockLogger(name)

    def get_active_pilot(self):
        return self.active_pilot

    def get_active_pilot_profile(self):
        if self.active_pilot:
            return type('Profile', (), {
                'id': self.active_pilot,
                'name': 'Test Pilot',
                'flightHours': 1500.0,
                'baseline': {},
                'environmentPreferences': {}
            })()
        return None

    def publish_data(self, channel, data):
        print(f"[PUBLISH] {channel}: {data}")

    def subscribe_to_data(self, channel, callback):
        print(f"[SUBSCRIBE] {channel}")

    def subscribe_to_state_changes(self, callback):
        print(f"[SUBSCRIBE] State changes")

    def list_pilots(self):
        return [self.active_pilot]


class MockLogger:
    def __init__(self, name):
        self.name = name

    def info(self, msg): print(f"[INFO] {self.name}: {msg}")
    def debug(self, msg): print(f"[DEBUG] {self.name}: {msg}")
    def warning(self, msg): print(f"[WARNING] {self.name}: {msg}")
    def error(self, msg): print(f"[ERROR] {self.name}: {msg}")


class SimplifiedVisionProcessor:
    """Simplified, fast vision processing service"""

    def __init__(self):
        # Initialize core system
        if COGNICORE_AVAILABLE:
            self.core = CogniCore(SERVICE_NAME)
        else:
            self.core = MockCore(SERVICE_NAME)

        self.logger = self.core.get_logger(SERVICE_NAME)

        # MediaPipe setup
        self.mp_face_mesh = mp.solutions.face_mesh
        self.face_mesh = self.mp_face_mesh.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )

        # Landmark points (from your working code)
        self.LEFT_EYE_POINTS = [33, 160, 158, 133, 153, 144]
        self.RIGHT_EYE_POINTS = [263, 387, 385, 362, 380, 373]
        # Your working mouth points
        self.MOUTH_POINTS = [78, 38, 268, 308, 316, 86]

        # Thresholds (from your working code)
        self.EAR_THRESHOLD = 0.25
        self.EAR_CONSECUTIVE_FRAMES = 3
        self.MAR_THRESHOLD = 0.5
        self.MAR_CONSECUTIVE_FRAMES = 10

        # State tracking
        self.running = False
        self.pilot_profile = None
        self.camera = None

        # Counters
        self.blink_count = 0
        self.yawn_count = 0
        self.microsleep_count = 0
        self.eyes_closed_count = 0
        self.mouth_open_count = 0

        # Timing
        self.session_start_time = time.time()
        self.last_reset_time = time.time()
        self.reset_interval = 300.0  # Reset every 5 minutes

        # Eye state tracking for microsleeps
        self.eyes_closed_start = None
        self.current_closure_duration = 0.0
        self.eye_state = "open"

        # Setup subscriptions
        self.setup_subscriptions()

        self.logger.info("✅ Simplified Vision Processor initialized")

    def setup_subscriptions(self):
        """Setup CogniCore subscriptions"""
        try:
            # Subscribe to pilot changes
            existing_pilots = self.core.list_pilots()
            self.logger.info(
                f"Found {len(existing_pilots)} pilots: {existing_pilots}")

            for pilot_id in existing_pilots:
                self.core.subscribe_to_data(
                    f"pilot:{pilot_id}", self.handle_pilot_change)

            self.core.subscribe_to_state_changes(self.handle_state_change)
            self.logger.info("Subscriptions setup complete")

        except Exception as e:
            self.logger.error(f"Subscription setup failed: {e}")

    def handle_pilot_change(self, hash_name: str, data: Dict[str, Any]):
        """Handle pilot activation/deactivation"""
        try:
            pilot_id = data.get('pilot_id') if data else None
            is_active = data.get('active', False) if data else False

            if pilot_id and is_active and not self.running:
                self.logger.info(f"🚀 Pilot activated: {pilot_id}")
                self.start_processing_for_pilot(pilot_id)
            elif pilot_id and not is_active and self.running:
                self.logger.info(f"✋ Pilot deactivated: {pilot_id}")
                self.stop_processing()

        except Exception as e:
            self.logger.error(f"Error handling pilot change: {e}")

    def handle_state_change(self, state_data: Dict[str, Any]):
        """Handle system state changes"""
        try:
            state = state_data.get('state')
            self.logger.debug(f"State change: {state}")
        except Exception as e:
            self.logger.error(f"Error handling state change: {e}")

    def start_processing_for_pilot(self, pilot_id: str):
        """Start processing for specific pilot"""
        try:
            profile = self.load_pilot_profile()
            if not profile:
                self.logger.error(f"No profile for pilot: {pilot_id}")
                return False

            self.pilot_profile = profile
            self.running = True
            self.logger.info(f"✅ Processing started for pilot: {pilot_id}")
            return True

        except Exception as e:
            self.logger.error(f"Failed to start processing: {e}")
            return False

    def stop_processing(self):
        """Stop processing and cleanup"""
        self.running = False
        self.pilot_profile = None
        if self.camera:
            self.camera.release()
            self.camera = None
        self.logger.info("🛑 Processing stopped")

    def load_pilot_profile(self):
        """Load pilot profile"""
        try:
            profile = self.core.get_active_pilot_profile()
            if profile:
                return {
                    "pilot_id": profile.id,
                    "name": profile.name,
                    "flightHours": profile.flightHours,
                    "baseline": profile.baseline,
                    "environmentPreferences": profile.environmentPreferences
                }
            return None
        except Exception as e:
            self.logger.error(f"Failed to load profile: {e}")
            return None

    def calculate_ear(self, landmarks, eye_points, frame_shape):
        """Calculate EAR (from your working code)"""
        try:
            h, w = frame_shape[:2]
            points = []

            for i in eye_points:
                if i < len(landmarks.landmark):
                    lm = landmarks.landmark[i]
                    x = int(lm.x * w)
                    y = int(lm.y * h)
                    points.append((x, y))
                else:
                    return 0.0

            if len(points) != 6:
                return 0.0

            p1, p2, p3, p4, p5, p6 = points
            vertical_1 = self.distance(p2, p6)
            vertical_2 = self.distance(p3, p5)
            horizontal = self.distance(p1, p4)

            if horizontal > 0:
                ear = (vertical_1 + vertical_2) / (2 * horizontal)
                return max(0.0, min(1.0, ear))
            return 0.0

        except Exception:
            return 0.0

    def calculate_mar(self, landmarks, mouth_points, frame_shape):
        """Calculate MAR (from your working code with your modifications)"""
        try:
            h, w = frame_shape[:2]
            points = []

            for i in mouth_points:
                if i < len(landmarks.landmark):
                    lm = landmarks.landmark[i]
                    x = int(lm.x * w)
                    y = int(lm.y * h)
                    points.append((x, y))
                else:
                    return 0.0

            if len(points) != 6:
                return 0.0

            p1, p2, p3, p4, p5, p6 = points
            vertical_1 = self.distance(p2, p6)
            vertical_2 = self.distance(p3, p5)
            horizontal = self.distance(p1, p4)

            if horizontal > 0:
                # Your modified MAR formula
                mar = ((vertical_1 + vertical_2) / (horizontal * 2.0)) - 0.4
                return max(0.0, min(1.0, mar))
            return 0.0

        except Exception:
            return 0.0

    def distance(self, point1, point2):
        """Calculate distance between two points"""
        return math.sqrt((point1[0] - point2[0])**2 + (point1[1] - point2[1])**2)

    def reset_counters_if_needed(self, current_time):
        """Reset counters periodically"""
        if current_time - self.last_reset_time >= self.reset_interval:
            self.microsleep_count = 0
            self.blink_count = 0
            self.yawn_count = 0
            self.last_reset_time = current_time

    def process_frame(self, frame):
        """Process single frame for fatigue detection"""
        current_time = time.time()
        self.reset_counters_if_needed(current_time)

        # Convert to RGB for MediaPipe
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        rgb_frame.flags.writeable = False
        results = self.face_mesh.process(rgb_frame)

        if not results.multi_face_landmarks:
            return None

        face_landmarks = results.multi_face_landmarks[0]

        # Calculate EAR and MAR
        left_ear = self.calculate_ear(
            face_landmarks, self.LEFT_EYE_POINTS, frame.shape)
        right_ear = self.calculate_ear(
            face_landmarks, self.RIGHT_EYE_POINTS, frame.shape)
        avg_ear = (left_ear + right_ear) / 2.0
        mar = self.calculate_mar(
            face_landmarks, self.MOUTH_POINTS, frame.shape)

        # Eye state detection (blinks and microsleeps)
        eyes_closed = avg_ear < self.EAR_THRESHOLD

        if eyes_closed:
            if self.eye_state == "open":
                self.eyes_closed_start = current_time
            self.eye_state = "closed"
            self.eyes_closed_count += 1
            self.current_closure_duration = (
                current_time - self.eyes_closed_start) if self.eyes_closed_start else 0.0

            # Detect microsleeps (eyes closed > 1 second)
            if self.current_closure_duration >= 1.0 and not hasattr(self, '_microsleep_detected'):
                self.microsleep_count += 1
                self._microsleep_detected = True
                self.logger.warning(
                    f"🚨 Microsleep detected! (#{self.microsleep_count})")
        else:
            # Eyes opened
            if self.eyes_closed_count >= self.EAR_CONSECUTIVE_FRAMES:
                self.blink_count += 1

            self.eyes_closed_count = 0
            self.eye_state = "open"
            self.current_closure_duration = 0.0
            if hasattr(self, '_microsleep_detected'):
                delattr(self, '_microsleep_detected')

        # Yawn detection
        if mar > self.MAR_THRESHOLD:
            self.mouth_open_count += 1
            if self.mouth_open_count >= self.MAR_CONSECUTIVE_FRAMES:
                if not hasattr(self, '_yawn_detected'):
                    self.yawn_count += 1
                    self._yawn_detected = True
                    self.logger.warning(
                        f"🥱 Yawn detected! (#{self.yawn_count})")
        else:
            self.mouth_open_count = 0
            if hasattr(self, '_yawn_detected'):
                delattr(self, '_yawn_detected')

        # Calculate blink rate
        session_duration = current_time - self.session_start_time
        blink_rate = (self.blink_count * 60 /
                      session_duration) if session_duration > 30 else 0.0

        # Return data in project's expected format
        return {
            "timestamp": current_time,
            "avg_ear": float(round(avg_ear, 3)),
            "left_ear": float(round(left_ear, 3)),
            "right_ear": float(round(right_ear, 3)),
            "mar": float(round(mar, 3)),
            "eyes_closed": bool(eyes_closed),
            "closure_duration": float(round(self.current_closure_duration, 1)),
            "microsleep_count": int(self.microsleep_count),
            "blink_rate_per_minute": float(round(blink_rate, 1)),
            "yawn_count": int(self.yawn_count),
            "is_yawning": bool(mar > self.MAR_THRESHOLD),
            "blink_count": int(self.blink_count),
            "service": "vision_processing"
        }

    def run(self):
        """Main processing loop"""
        self.logger.info("🚀 Vision Processing Service starting...")

        # For testing, auto-start processing
        if not COGNICORE_AVAILABLE:
            self.logger.info("Mock mode - auto-starting processing")
            self.start_processing_for_pilot("test_pilot_123")

        while True:
            try:
                if self.running:
                    # Initialize camera if needed
                    if not self.camera:
                        self.camera = cv2.VideoCapture(0)
                        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
                        self.camera.set(
                            cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
                        self.camera.set(cv2.CAP_PROP_FPS, FPS)

                        if not self.camera.isOpened():
                            self.logger.error("Cannot open camera")
                            time.sleep(5)
                            continue

                    # Read and process frame
                    ret, frame = self.camera.read()
                    if ret:
                        processed_data = self.process_frame(frame)

                        if processed_data:
                            # Publish data via CogniCore
                            try:
                                self.core.publish_data(
                                    "vision", processed_data)
                                self.logger.debug("Vision data published")
                            except Exception as e:
                                self.logger.error(
                                    f"Failed to publish data: {e}")

                        # Optional: Display for testing
                        if not COGNICORE_AVAILABLE:
                            self.display_frame_for_testing(
                                frame, processed_data)

                    time.sleep(0.005)  # Fast loop for real-time processing

                else:
                    # Not processing - cleanup camera
                    if self.camera:
                        self.camera.release()
                        self.camera = None
                    time.sleep(0.1)

            except KeyboardInterrupt:
                self.logger.info("Shutting down...")
                break
            except Exception as e:
                self.logger.error(f"Processing error: {e}")
                time.sleep(1)

        # Cleanup
        if self.camera:
            self.camera.release()
        cv2.destroyAllWindows()
        self.logger.info("✅ Vision Processing Service stopped")

    def display_frame_for_testing(self, frame, data):
        """Display frame with data overlay for testing"""
        if data:
            # Add text overlay
            cv2.putText(frame, f"EAR: {data['avg_ear']:.3f}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            cv2.putText(frame, f"MAR: {data['mar']:.3f}", (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(frame, f"Blinks: {data['blink_count']}", (10, 90),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            cv2.putText(frame, f"Yawns: {data['yawn_count']}", (10, 120),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 255), 2)
            cv2.putText(frame, f"Microsleeps: {data['microsleep_count']}", (10, 150),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

        cv2.imshow('Vision Processing Test', frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            self.running = False


def main():
    """Entry point"""
    try:
        processor = SimplifiedVisionProcessor()
        processor.run()
    except Exception as e:
        print(f"Failed to start vision processor: {e}")


if __name__ == "__main__":
    main()
