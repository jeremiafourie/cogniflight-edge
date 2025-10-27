"""
Fatigue Detection Processor Module
Handles fatigue monitoring using MediaPipe face mesh
"""
import time
import cv2
import numpy as np
import logging
from typing import Dict, Any, Optional, List, Tuple


# Face landmark indices for EAR calculations - MediaPipe specific points
# These 6 points per eye are chosen for optimal EAR calculation
# Format: [P1, P2, P3, P4, P5, P6] where P1-P4 form corners, P2,P6 and P3,P5 form vertical pairs
LEFT_EYE_LANDMARKS = [362, 385, 387, 263, 373, 380]  # Correct MediaPipe indices
RIGHT_EYE_LANDMARKS = [33, 160, 158, 133, 153, 144]  # Correct MediaPipe indices

# MediaPipe mouth landmarks for MAR calculation (based on research)
# Format: [[horizontal], [vertical1], [vertical2], [vertical3]]
# Using proven landmarks from drowsiness detection implementations
MOUTH_LANDMARKS_PAIRS = [
    [61, 291],   # Horizontal: left corner to right corner
    [39, 181],   # Vertical 1: upper lip to lower lip (left)
    [0, 17],     # Vertical 2: upper lip to lower lip (center)
    [269, 405]   # Vertical 3: upper lip to lower lip (right)
]


class FatigueDetectorProcessor:
    """
    Handle fatigue detection using facial landmarks.
    Calculates EAR, MAR, tracks blinks, and detects microsleeps.
    """

    def __init__(self, face_mesh, logger: logging.Logger):
        self.face_mesh = face_mesh
        self.logger = logger

        # Thresholds - calibrated for standard EAR formula with MediaPipe
        self.eye_closure_threshold = 0.20  # Standard threshold: eyes closed when EAR < 0.2
        self.drowsy_closure_threshold = 0.18  # Drowsy state threshold
        self.microsleep_threshold = 1.0  # seconds
        self.prolonged_closure_threshold = 3.0  # seconds

        # Yawning detection thresholds (based on research: typical threshold is 0.5)
        self.yawn_threshold = 0.5  # MAR threshold for yawn detection
        self.min_yawn_duration = 1.2  # Minimum 1.2 seconds for valid yawn
        self.max_yawn_duration = 6.0  # Maximum 6 seconds for valid yawn (research shows 4-6s typical)
        self.yawn_cooldown = 3.0  # Cooldown period between yawns

        # Eye state tracking
        self.eyes_closed_start = None
        self.current_closure_duration = 0.0
        self.total_closure_time = 0.0
        self.microsleep_count = 0
        self.prolonged_closure_count = 0

        # Blink detection
        self.blink_count = 0
        self.last_blink_time = 0
        self.eye_state = "open"
        self.min_blink_duration = 0.08  # Minimum 80ms for a valid blink
        self.max_blink_duration = 0.4   # Maximum 400ms for a valid blink

        # Baseline values (typical for open eyes and closed mouth)
        self.baseline_ear = 0.30  # Average EAR for open eyes with MediaPipe
        self.baseline_mar = 0.25  # Average MAR for closed mouth

        # Yawn tracking
        self.yawn_count = 0
        self.yawn_start_time = None
        self.current_yawn_duration = 0.0
        self.last_yawn_end_time = 0
        self.is_yawning = False

        # Face detection tracking
        self.face_detected_count = 0
        self.face_lost_count = 0
        self.face_width = 100
        self.face_height = 100

        # Session timing
        self.session_start_time = time.time()
        self.last_reset_time = time.time()
        self.reset_interval = 300.0  # Reset every 5 minutes

    def process_frame(self, frame: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Process a frame for fatigue detection.

        Returns:
            Dictionary containing fatigue metrics or None if no face detected
        """
        current_time = time.time()

        # Reset counters periodically
        self._reset_counters_if_needed(current_time)

        # Extract facial landmarks
        landmarks = self._extract_landmarks(frame)
        if not landmarks:
            self.face_lost_count += 1
            self.face_detected_count = 0

            # Return minimal data with face_detected = False
            return {
                "timestamp": current_time,
                "face_detected": False,
                "face_offset_x": 0.0,
                "face_offset_y": 0.0,
                "avg_ear": 0.0,
                "mar": 0.0,
                "eyes_closed": False,
                "closure_duration": 0.0,
                "microsleep_count": 0,
                "blink_rate_per_minute": 0.0,
                "yawning": False,
                "yawn_count": 0,
                "yawn_duration": 0.0
            }

        self.face_detected_count += 1
        self.face_lost_count = 0

        # Extract eye and mouth landmarks
        left_eye = landmarks.get("left_eye", [])
        right_eye = landmarks.get("right_eye", [])
        mouth = landmarks.get("mouth", [])

        if not left_eye or not right_eye:
            return None

        # Calculate Eye Aspect Ratio (EAR)
        left_ear = self._calculate_ear(left_eye)
        right_ear = self._calculate_ear(right_eye)
        avg_ear = (left_ear + right_ear) / 2.0

        # Validate EAR - unrealistic values indicate false face detection
        # Normal human EAR range: 0.15-0.45 (based on research)
        if avg_ear < 0.10 or avg_ear > 0.50:
            # EAR outside normal human range, likely false positive
            return None

        # Calculate Mouth Aspect Ratio (MAR) for yawn detection
        mar = self._calculate_mar(mouth) if mouth else self.baseline_mar

        # Detect eye state
        eyes_closed = avg_ear < self.eye_closure_threshold

        # Track eye closure duration and blinks
        if eyes_closed:
            if self.eye_state == "open":
                # Eye is closing, start tracking duration
                self.eyes_closed_start = current_time
                self.eye_state = "closed"
            # Update closure duration while eyes are closed
            self.current_closure_duration = (current_time - self.eyes_closed_start) if self.eyes_closed_start else 0.0

            # Count microsleeps
            if self.current_closure_duration >= self.microsleep_threshold and not hasattr(self, '_microsleep_detected'):
                self.microsleep_count += 1
                self._microsleep_detected = True
        else:
            # Eyes are open
            if self.eye_state == "closed" and self.eyes_closed_start:
                # Eye is opening after being closed - check if it was a valid blink
                closure_duration = current_time - self.eyes_closed_start
                if self.min_blink_duration <= closure_duration <= self.max_blink_duration:
                    self.blink_count += 1
                    self.last_blink_time = current_time

            # Reset eye state
            self.eye_state = "open"
            self.current_closure_duration = 0.0
            self.eyes_closed_start = None
            if hasattr(self, '_microsleep_detected'):
                delattr(self, '_microsleep_detected')

        # Detect yawning
        if mar > self.yawn_threshold:
            # Check if in cooldown period
            if current_time - self.last_yawn_end_time > self.yawn_cooldown:
                if not self.is_yawning:
                    # Start of a new yawn
                    self.yawn_start_time = current_time
                    self.is_yawning = True
                # Update yawn duration
                self.current_yawn_duration = current_time - self.yawn_start_time if self.yawn_start_time else 0.0

                # Force end if yawn exceeds max duration
                if self.current_yawn_duration > self.max_yawn_duration:
                    self.yawn_count += 1
                    self.last_yawn_end_time = current_time
                    self.is_yawning = False
                    self.current_yawn_duration = 0.0
                    self.yawn_start_time = None
        else:
            if self.is_yawning and self.yawn_start_time:
                # End of yawn - check if valid duration
                yawn_duration = current_time - self.yawn_start_time
                if self.min_yawn_duration <= yawn_duration <= self.max_yawn_duration:
                    self.yawn_count += 1
                    self.last_yawn_end_time = current_time
            # Reset yawn state
            self.is_yawning = False
            self.current_yawn_duration = 0.0
            self.yawn_start_time = None

        # Calculate blink rate
        time_elapsed = current_time - self.session_start_time
        blink_rate = (self.blink_count / time_elapsed * 60) if time_elapsed > 30 else 0.0

        # Calculate face position offset
        face_offset_x, face_offset_y = self._calculate_face_offset(frame, left_eye, right_eye)

        # Return fatigue metrics with yawn data
        return {
            "timestamp": current_time,
            "avg_ear": float(round(avg_ear, 3)),
            "mar": float(round(mar, 3)),
            "eyes_closed": bool(eyes_closed),
            "closure_duration": float(round(self.current_closure_duration, 1)),
            "microsleep_count": int(self.microsleep_count),
            "blink_rate_per_minute": float(round(blink_rate, 0)),
            "face_detected": True,
            "face_offset_x": float(round(face_offset_x, 3)),
            "face_offset_y": float(round(face_offset_y, 3)),
            "yawning": bool(self.is_yawning),
            "yawn_count": int(self.yawn_count),
            "yawn_duration": float(round(self.current_yawn_duration, 1))
        }

    def _extract_landmarks(self, frame: np.ndarray) -> Optional[Dict[str, List[Tuple[float, float]]]]:
        """Extract facial landmarks using MediaPipe"""
        try:
            # Resize frame for faster processing
            h, w = frame.shape[:2]
            scale_factor = 0.75
            small_h, small_w = int(h * scale_factor), int(w * scale_factor)
            small_frame = cv2.resize(frame, (small_w, small_h), interpolation=cv2.INTER_LINEAR)

            # Convert BGR to RGB
            rgb_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            rgb_frame.flags.writeable = False
            results = self.face_mesh.process(rgb_frame)

            if not results.multi_face_landmarks:
                return None

            face_landmarks = results.multi_face_landmarks[0]
            if len(face_landmarks.landmark) < 468:
                return None

            # Validate face detection by checking landmark confidence
            # MediaPipe sometimes returns false positives with unrealistic positions
            # Check if key landmarks are within reasonable bounds
            nose_tip = face_landmarks.landmark[1]  # Nose tip landmark
            if nose_tip.x < 0.1 or nose_tip.x > 0.9 or nose_tip.y < 0.1 or nose_tip.y > 0.9:
                # Face is too close to edges, likely false positive
                return None

            # Extract landmark coordinates
            landmarks = {}

            # Left eye - keep as float for accurate EAR calculation
            left_eye = []
            for idx in LEFT_EYE_LANDMARKS:
                lm = face_landmarks.landmark[idx]
                x = lm.x * w  # Keep as float
                y = lm.y * h  # Keep as float
                left_eye.append((x, y))
            landmarks['left_eye'] = left_eye

            # Right eye - keep as float for accurate EAR calculation
            right_eye = []
            for idx in RIGHT_EYE_LANDMARKS:
                lm = face_landmarks.landmark[idx]
                x = lm.x * w  # Keep as float
                y = lm.y * h  # Keep as float
                right_eye.append((x, y))
            landmarks['right_eye'] = right_eye

            # Mouth - extract specific landmark pairs for MAR calculation
            mouth_points = []
            for pair in MOUTH_LANDMARKS_PAIRS:
                pair_coords = []
                for idx in pair:
                    lm = face_landmarks.landmark[idx]
                    x = lm.x * w  # Keep as float for more accurate calculation
                    y = lm.y * h
                    pair_coords.append((x, y))
                mouth_points.append(pair_coords)
            landmarks['mouth'] = mouth_points

            return landmarks

        except Exception as e:
            self.logger.error(f"Landmark extraction failed: {e}")
            return None

    def _calculate_ear(self, eye_landmarks: List[Tuple[float, float]]) -> float:
        """Calculate Eye Aspect Ratio (EAR) using the standard formula
        EAR = (A + B) / (2.0 * C)
        where A and B are vertical eye distances, C is horizontal eye width

        Landmark order: [P1, P2, P3, P4, P5, P6]
        P1 and P4 are eye corners (horizontal)
        P2-P6 and P3-P5 are vertical pairs
        """
        try:
            if len(eye_landmarks) != 6:
                return self.baseline_ear

            points = np.array(eye_landmarks, dtype=np.float32)

            # Calculate distances using numpy for better accuracy
            # A: distance between P2 (index 1) and P6 (index 5) - first vertical pair
            A = np.linalg.norm(points[1] - points[5])

            # B: distance between P3 (index 2) and P5 (index 4) - second vertical pair
            B = np.linalg.norm(points[2] - points[4])

            # C: distance between P1 (index 0) and P4 (index 3) - horizontal width
            C = np.linalg.norm(points[0] - points[3])

            if C > 0.0:
                ear = (A + B) / (2.0 * C)
                # Normal EAR range is typically 0.2-0.4 for open eyes, <0.2 for closed
                return ear
            else:
                return self.baseline_ear

        except Exception as e:
            self.logger.debug(f"EAR calculation error: {e}")
            return self.baseline_ear

    def _calculate_mar(self, mouth_landmarks: List[List[Tuple[float, float]]]) -> float:
        """Calculate Mouth Aspect Ratio (MAR) using proven formula from research
        MAR = (N1 + N2 + N3) / (3 * D)
        where N1, N2, N3 are vertical distances and D is horizontal distance
        """
        try:
            if not mouth_landmarks or len(mouth_landmarks) != 4:
                return self.baseline_mar

            # mouth_landmarks structure: [[horizontal], [vertical1], [vertical2], [vertical3]]
            # Each contains 2 points: [point1, point2]

            # Calculate horizontal distance (D) - mouth width
            horizontal_pair = mouth_landmarks[0]
            D = np.sqrt((horizontal_pair[1][0] - horizontal_pair[0][0])**2 +
                       (horizontal_pair[1][1] - horizontal_pair[0][1])**2)

            # Calculate three vertical distances (N1, N2, N3) - mouth openness
            N1 = np.sqrt((mouth_landmarks[1][1][0] - mouth_landmarks[1][0][0])**2 +
                        (mouth_landmarks[1][1][1] - mouth_landmarks[1][0][1])**2)

            N2 = np.sqrt((mouth_landmarks[2][1][0] - mouth_landmarks[2][0][0])**2 +
                        (mouth_landmarks[2][1][1] - mouth_landmarks[2][0][1])**2)

            N3 = np.sqrt((mouth_landmarks[3][1][0] - mouth_landmarks[3][0][0])**2 +
                        (mouth_landmarks[3][1][1] - mouth_landmarks[3][0][1])**2)

            # Calculate MAR using proven formula
            if D > 0:
                mar = (N1 + N2 + N3) / (3 * D)
                return mar
            else:
                return self.baseline_mar

        except Exception as e:
            self.logger.debug(f"MAR calculation error: {e}")
            return self.baseline_mar

    def _calculate_face_offset(self, frame: np.ndarray, left_eye: List, right_eye: List) -> Tuple[float, float]:
        """Calculate face position offset from frame center"""
        try:
            if left_eye and right_eye:
                # Calculate center between eyes
                left_eye_center_x = sum(x for x, y in left_eye) / len(left_eye)
                left_eye_center_y = sum(y for x, y in left_eye) / len(left_eye)
                right_eye_center_x = sum(x for x, y in right_eye) / len(right_eye)
                right_eye_center_y = sum(y for x, y in right_eye) / len(right_eye)

                face_center_x = (left_eye_center_x + right_eye_center_x) / 2
                face_center_y = (left_eye_center_y + right_eye_center_y) / 2
            else:
                face_center_x = frame.shape[1] / 2
                face_center_y = frame.shape[0] / 2

            # Calculate frame center
            frame_center_x = frame.shape[1] / 2
            frame_center_y = frame.shape[0] / 2

            # Calculate normalized offsets (-1 to 1)
            face_offset_x = (face_center_x - frame_center_x) / frame_center_x if frame_center_x > 0 else 0.0
            face_offset_y = (face_center_y - frame_center_y) / frame_center_y if frame_center_y > 0 else 0.0

            # Clamp values
            face_offset_x = max(-1.0, min(1.0, face_offset_x))
            face_offset_y = max(-1.0, min(1.0, face_offset_y))

            return face_offset_x, face_offset_y

        except Exception:
            return 0.0, 0.0

    def _reset_counters_if_needed(self, current_time: float):
        """Reset counters periodically - currently disabled to preserve session data"""
        # Removed automatic reset to prevent data loss
        # Counters will only reset when reset() is called explicitly
        pass

    def reset(self):
        """Reset all tracking variables"""
        self.eyes_closed_start = None
        self.current_closure_duration = 0.0
        self.microsleep_count = 0
        self.blink_count = 0
        self.eye_state = "open"
        self.face_detected_count = 0
        self.face_lost_count = 0
        # Reset yawn tracking
        self.yawn_count = 0
        self.yawn_start_time = None
        self.current_yawn_duration = 0.0
        self.last_yawn_end_time = 0
        self.is_yawning = False
        # Reset timing
        self.session_start_time = time.time()
        self.last_reset_time = time.time()