import os
import sys
import time
import json
import threading
import logging
import cv2
import numpy as np
import subprocess
from pathlib import Path

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

# Import shared resources
try:
    from CogniCore import CogniCore, SystemState, config
except ImportError as e:
    print(f"Failed to import CogniCore modules: {e}")
    sys.exit(1)

# Configuration constants
HEARTBEAT_DIR = config.HEARTBEAT_DIR

# Import InsightFace after system setup
try:
    from insightface.app import FaceAnalysis
except ImportError as e:
    print(f"Failed to import InsightFace: {e}")
    print("Install with: pip install insightface")
    sys.exit(1)

# Configuration - Can be overridden by environment variables
RECOGNITION_THRESHOLD = float(os.getenv('RECOGNITION_THRESHOLD', '0.4'))
FACE_DETECTION_THRESHOLD = float(os.getenv('FACE_DETECTION_THRESHOLD', '0.7'))  # Minimum confidence for face detection
FACE_MODEL_NAME = os.getenv('FACE_MODEL_NAME', 'buffalo_s')
HEARTBEAT_INTERVAL = int(os.getenv('HEARTBEAT_INTERVAL', '5'))  # seconds
CAMERA_WIDTH = int(os.getenv('CAMERA_WIDTH', '640'))
CAMERA_HEIGHT = int(os.getenv('CAMERA_HEIGHT', '360'))
CAMERA_FPS = int(os.getenv('CAMERA_FPS', '15'))

# Service name for heartbeat
SERVICE_NAME = "face_recognition"

# Global variables
last_heartbeat = 0

class PilotDetectionCamera:
    """Camera capture system for pilot identification using rpicam-vid"""
    
    def __init__(self, logger, width=640, height=360, fps=15):
        self.logger = logger
        self.width = width
        self.height = height
        self.fps = fps
        self.process = None
        self.running = False
        self.frame_data = None
        self.frame_lock = threading.Lock()
        self.frames_read = 0
        
    def start(self):
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
                bufsize=0
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
        frame_size = self.width * self.height * 3 // 2
        buffer = b''
        
        while self.running and self.process and self.process.poll() is None:
            try:
                chunk = self.process.stdout.read(4096)
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
        with self.frame_lock:
            if self.frame_data is not None:
                return True, self.frame_data.copy()
            else:
                return False, None
    
    def get_frame_count(self):
        return self.frames_read
    
    def release(self):
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

def write_service_heartbeat(core, logger):
    """Write pilot identification service heartbeat for watchdog monitoring"""
    global last_heartbeat
    current_time = time.time()
    
    if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
        try:
            core.write_heartbeat()
            last_heartbeat = current_time
            logger.debug(f"Heartbeat written: {current_time}")
            
        except Exception as e:
            logger.error(f"Failed to write heartbeat: {e}")

def load_pilot_face_embeddings_from_redis(core, logger):
    """Load known pilot face embeddings from CogniCore Redis"""
    try:
        embeddings = {}
        
        # Get all pilot IDs to check for embeddings
        pilots = core.list_pilots()
        
        # Also check for embedding keys directly
        redis_client = core._redis_client
        embedding_keys = redis_client.keys("cognicore:data:embedding:*")
        
        all_pilot_ids = set(pilots)
        for key in embedding_keys:
            pilot_id = key.split(":")[-1]  # Extract pilot_id from key
            all_pilot_ids.add(pilot_id)
        
        for pilot_id in all_pilot_ids:
            embedding_data = core.get_data(f'embedding:{pilot_id}')
            if embedding_data and 'embedding' in embedding_data:
                try:
                    # CogniCore already parses JSON, so embedding is already a list
                    embedding = embedding_data['embedding']
                    if isinstance(embedding, str):
                        # In case it's still a string, parse it
                        embedding = json.loads(embedding)
                    embedding_array = np.array(embedding, dtype=np.float32)
                    
                    # Normalize embedding to unit length
                    norm = np.linalg.norm(embedding_array)
                    if norm > 0:
                        embedding_array = embedding_array / norm
                    
                    embeddings[pilot_id] = embedding_array
                    logger.debug(f"Loaded embedding for pilot {pilot_id} from {embedding_data.get('source', 'unknown')}")
                except Exception as e:
                    logger.warning(f"Failed to parse embedding for pilot {pilot_id}: {e}")
        
        logger.info(f"Loaded {len(embeddings)} face embeddings from Redis: {list(embeddings.keys())}")
        return embeddings
        
    except Exception as e:
        logger.error(f"Failed to load embeddings from Redis: {e}")
        return {}

def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def identify_pilot_from_frame(frame, face_analyzer, pilot_embeddings, recognition_threshold, detection_threshold, logger):
    """
    Identify pilot from camera frame against known pilot embeddings.
    Returns: (pilot_id or None, face_detected_boolean, confidence_score)
    """
    try:
        faces = face_analyzer.get(frame)
        if not faces:
            return None, False, 0.0
        
        face = faces[0]  # Use largest/first face
        
        # Check face detection confidence to filter false positives
        detection_score = getattr(face, 'det_score', 1.0)  # Default to 1.0 if not available
        logger.debug(f"Face detection score: {detection_score:.3f}, threshold: {detection_threshold}")
        
        if detection_score < detection_threshold:
            logger.debug(f"Face detection confidence too low: {detection_score:.3f} < {detection_threshold}")
            return None, False, 0.0
        
        emb = face.embedding
        
        # Normalize embedding
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        
        best_match = None
        best_sim = -1.0
        
        # Compare against all known embeddings
        for pid, pilot_embedding in pilot_embeddings.items():
            sim = cosine_similarity(emb, pilot_embedding)
            if sim > best_sim:
                best_sim = sim
                best_match = pid
        
        logger.debug(f"Best match: {best_match} with similarity: {best_sim:.3f}")
        
        if best_sim >= recognition_threshold:
            return best_match, True, best_sim
        
        return None, True, best_sim  # Face detected but not recognized
        
    except Exception as e:
        logger.error(f"Face recognition error: {e}")
        return None, False, 0.0

def check_active_pilot_status(core, logger):
    """Check if any pilot is currently active in the system via CogniCore"""
    try:
        active_pilot = core.get_active_pilot()
        return active_pilot is not None
    except Exception as e:
        logger.error(f"Error checking active pilot: {e}")
        return False

def check_pending_pilot_identification_request(core, logger):
    """Check if a pilot identification request is currently pending from another service"""
    try:
        request_data = core.get_data("pilot_id_request")
        return request_data is not None
    except Exception as e:
        logger.debug(f"Error checking pilot request: {e}")
        return False

# Global variables for request tracking
pilot_request_pending = False
active_pilot_detected = False
camera_released = False

def on_pilot_request_cleared(hash_name, data):
    """Callback when pilot_id_request is cleared"""
    global pilot_request_pending
    if data is None:  # Request was cleared/deleted
        pilot_request_pending = False

def on_active_pilot_change(hash_name, data):
    """Callback when active pilot changes"""
    global active_pilot_detected, camera_released
    pilot_id = data.get('pilot_id') if data else None
    
    if pilot_id and not active_pilot_detected:
        # New pilot detected - trigger camera release
        active_pilot_detected = True
        camera_released = False
    elif not pilot_id and active_pilot_detected:
        # Pilot cleared - reset state for next detection
        active_pilot_detected = False
        camera_released = False

def main():
    """Main face recognition service loop"""
    try:
        # Initialize CogniCore
        core = CogniCore("face_recognition")
        logger = core.get_logger(SERVICE_NAME)
        
        # Global flag for tracking pending requests
        global pilot_request_pending, active_pilot_detected, camera_released
        pilot_request_pending = False
        active_pilot_detected = False
        camera_released = False
        
        # Subscribe to pilot_id_request to monitor when it gets cleared
        core.subscribe_to_data("pilot_id_request", on_pilot_request_cleared)
        
        # Subscribe to active pilot changes for better handover management
        core.subscribe_to_data("active_pilot", on_active_pilot_change)
        
        # Clear active pilot on face recognition startup for proper camera handover
        try:
            core.clear_active_pilot()
            logger.info("Cleared active pilot on face recognition startup")
        except Exception as e:
            logger.debug(f"Failed to clear active pilot on startup: {e}")
        
        logger.info("Face Recognition service starting...")
        logger.info(f"Recognition threshold: {RECOGNITION_THRESHOLD}")
        logger.info(f"Face detection threshold: {FACE_DETECTION_THRESHOLD}")
        
        # Write initial heartbeat
        write_service_heartbeat(core, logger)
        
        # Service starting up
        logger.info("Face recognition service initializing...")
        
        logger.info("Sending LCD message: Face Recognition Starting...")
        # LCD messages are handled only via state changes
        logger.info("LCD message sent successfully")
        
        # Load pilot embeddings from CogniCore
        pilot_embeddings = load_pilot_face_embeddings_from_redis(core, logger)
        if not pilot_embeddings:
            logger.error("No pilot embeddings found in CogniCore. HTTPS client should manage embedding sync.")
            logger.info("Face recognition service will wait for HTTPS client to load embeddings...")
            # Continue running to allow HTTPS client to load embeddings
            pilot_embeddings = {}  # Start with empty, will be refreshed periodically
        
        # Set up periodic pilot embeddings refresh from Redis
        last_pilot_embeddings_refresh = time.time()
        PILOT_EMBEDDINGS_REFRESH_INTERVAL = 60 # 60 seconds - check frequently for new embeddings
        
        # Initialize pilot face recognition analyzer
        try:
            pilot_face_analyzer = FaceAnalysis(name=FACE_MODEL_NAME, providers=["CPUExecutionProvider"])
            pilot_face_analyzer.prepare(ctx_id=0, det_size=(640, 640))
            logger.info("Pilot face analyzer initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize FaceAnalysis: {e}")
            return
        
        # Setup camera
        camera = PilotDetectionCamera(logger, width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)
        if not camera.start():
            logger.error("Failed to initialize camera")
            return
        
        logger.info("Face recognition service started and running")
        
        camera_frames_processed = 0
        last_status_log = time.time()
        last_pilot_feedback_time = time.time()
        unknown_pilot_detection_start = None
        current_pilot_detection_state = "searching"
        pilot_faces_processed = 0
        running = True
        pilot_request_pending = False
        last_pilot_request_time = 0
        
        while running:
            # Check for active pilot status and refresh pilot embeddings periodically
            current_time = time.time()
            
            # Refresh embeddings from Redis periodically
            if current_time - last_pilot_embeddings_refresh > PILOT_EMBEDDINGS_REFRESH_INTERVAL:
                logger.info("Refreshing embeddings from Redis...")
                new_pilot_embeddings = load_pilot_face_embeddings_from_redis(core, logger)
                if new_pilot_embeddings:
                    pilot_embeddings = new_pilot_embeddings
                    logger.info(f"Refreshed {len(pilot_embeddings)} pilot embeddings from Redis")
                else:
                    logger.warning("Failed to refresh embeddings from Redis, keeping current ones")
                last_pilot_embeddings_refresh = current_time
            
            # Check if pilot request has timed out (30 seconds)
            if pilot_request_pending and current_time - last_pilot_request_time > 30:
                logger.warning("Pilot request timed out - clearing pending status")
                pilot_request_pending = False
                last_pilot_request_time = 0
            
            # Use subscription-based active pilot detection
            if active_pilot_detected and not camera_released:
                logger.info("Active pilot found via subscription - releasing camera and stopping face recognition")
                
                # Predictor service will set MONITORING_ACTIVE state when no fatigue detected
                active_pilot_id = core.get_active_pilot()
                logger.info(f"Active pilot {active_pilot_id} detected - predictor will handle monitoring state")
                
                # Release camera for vision processor
                camera.release()
                camera_released = True
                
                # Add small delay to ensure camera resources are fully released
                time.sleep(0.5)
                
                # Wait for pilot to be cleared before restarting
                logger.info("Waiting for pilot to be cleared...")
                while active_pilot_detected:
                    write_service_heartbeat(core, logger)
                    time.sleep(5)
                
                logger.info("Pilot cleared - restarting face recognition")
                
                # Set system state back to scanning for pilot
                core.set_system_state(SystemState.SCANNING, "Scanning for\nPilot...")
                
                # Add delay before restarting camera to ensure vision processing has fully released it
                time.sleep(1.0)
                
                # Restart camera with retry logic for robustness
                retry_count = 0
                max_retries = 3
                while retry_count < max_retries:
                    camera = PilotDetectionCamera(logger, width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)
                    if camera.start():
                        logger.info("Camera restarted successfully after handover")
                        break
                    else:
                        retry_count += 1
                        logger.warning(f"Camera restart attempt {retry_count}/{max_retries} failed, retrying...")
                        if retry_count < max_retries:
                            time.sleep(2.0)  # Wait before retry
                        else:
                            logger.error("Failed to restart camera after multiple attempts")
                            return
                    
                    # Reset recognition state
                    current_pilot_detection_state = "searching"
                    unknown_pilot_detection_start = None
                    camera_frames_processed = 0
                    pilot_faces_processed = 0
                    pilot_request_pending = False
                    last_pilot_request_time = 0
                    
                last_profile_check = current_time
            # Simple running check
            if not running:
                time.sleep(0.1)
                continue
                
            ret, frame = camera.read()
            if not ret or frame is None:
                time.sleep(0.1)
                continue
            
            camera_frames_processed += 1
            
            # Write heartbeat and status update every 30 seconds
            current_time = time.time()
            
            # Write heartbeat regularly
            write_service_heartbeat(core, logger)
            
            if current_time - last_status_log > 30:
                camera_frames = camera.get_frame_count()
                logger.info(f"Status: Camera frames: {camera_frames}, Processed: {camera_frames_processed}")
                last_status_log = current_time
            
            # Process every 15th frame
            if camera_frames_processed % 15 == 0:
                pilot_faces_processed += 1
                pilot_id, face_detected, confidence = identify_pilot_from_frame(frame, pilot_face_analyzer, pilot_embeddings, RECOGNITION_THRESHOLD, FACE_DETECTION_THRESHOLD, logger)
                
                # Show processing indicator every 20 face checks (300 frames) - less frequent
                if pilot_faces_processed % 20 == 0:
                    logger.debug(f"Pilot detection indicator: {pilot_faces_processed} faces analyzed")
                
                if not face_detected:
                    # No face detected
                    if current_pilot_detection_state != "searching":
                        logger.info("No face detected - returning to search mode")
                        # Set searching status message
                        core.set_system_state(SystemState.SCANNING, "Scanning...\nCabin Empty")
                        current_pilot_detection_state = "searching"
                        last_pilot_feedback_time = time.time()
                    unknown_pilot_detection_start = None
                    
                    # Periodic "still searching" feedback - less frequent
                    if time.time() - last_pilot_feedback_time > 15:
                        core.set_system_state(SystemState.SCANNING, "Scanning...\nCabin Empty")
                        last_pilot_feedback_time = time.time()
                    
                elif pilot_id:
                    # Known face recognized
                    logger.info(f"Pilot identified: {pilot_id} (confidence: {confidence:.3f})")
                    
                    # Check if a request is already pending or recently sent
                    if not pilot_request_pending and not check_pending_pilot_identification_request(core, logger):
                        # Set welcome status message
                        core.set_system_state(SystemState.SCANNING, f"Welcome {pilot_id}\nFetching profile")
                        
                        # Send pilot ID request via CogniCore
                        logger.info(f"Sending pilot ID {pilot_id} to HTTPS client")
                        try:
                            request_data = {
                                "pilot_id": pilot_id,
                                "confidence": float(confidence),
                                "timestamp": time.time(),
                                "source": "face_recognition"
                            }
                            
                            core.publish_data("pilot_id_request", request_data)
                            logger.info("Profile request sent to HTTPS client via CogniCore")
                            
                            # Mark request as pending
                            pilot_request_pending = True
                            last_pilot_request_time = current_time
                            
                        except Exception as e:
                            logger.error(f"Failed to send pilot ID to HTTPS client: {e}")
                            pilot_request_pending = False
                    else:
                        logger.debug(f"Pilot request already pending for {pilot_id} - skipping duplicate request")
                        # Still update status message if not already set
                        if current_pilot_detection_state != "recognized":
                            core.set_system_state(SystemState.SCANNING, f"Hey Skywalker\nFetching profile")
                    
                    unknown_pilot_detection_start = None
                    current_pilot_detection_state = "recognized"
                    last_pilot_feedback_time = time.time()
                    
                else:
                    # Unknown face detected
                    logger.info(f"Face detected but not recognized (confidence: {confidence:.3f}, threshold: {RECOGNITION_THRESHOLD})")
                    
                    if unknown_pilot_detection_start is None:
                        unknown_pilot_detection_start = time.time()
                        logger.warning(f"Unknown face detected - security alert (confidence: {confidence:.3f})")
                        # Set intruder alert status message
                        core.set_system_state(SystemState.INTRUDER_DETECTED, "WARNING\nIntruder Alert")
                    elif time.time() - unknown_pilot_detection_start > 10:
                        # Show face detected feedback only occasionally to avoid spam
                        core.set_system_state(SystemState.INTRUDER_DETECTED, "WARNING\nIntruder Alert")
                        unknown_pilot_detection_start = time.time()
                        
                    current_pilot_detection_state = "unknown"
                    last_pilot_feedback_time = time.time()
            
    except KeyboardInterrupt:
        logger.info("Face recognition service interrupted by user")
    except Exception as e:
        logger.error(f"Face recognition service crashed: {e}")
    finally:
        if 'camera' in locals():
            camera.release()
        if 'core' in locals():
            core.shutdown()
        logger.info("Face recognition service exited cleanly")

if __name__ == "__main__":
    main()