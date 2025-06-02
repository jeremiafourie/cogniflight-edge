import time
import cv2
import numpy as np
import mediapipe as mp

from common.queues import camera_to_preproc_queue, preproc_to_inference_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("preprocessing")

# ---------------------------------------------------------------------
# MediaPipe Face Mesh initialization
# ---------------------------------------------------------------------
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=False,
    max_num_faces=1,
    refine_landmarks=True,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# Landmark indices used for Eye Aspect Ratio (EAR) and Mouth Aspect Ratio (MAR)
LEFT_EYE_LANDMARKS  = [33, 160, 158, 133, 153, 144]   # [outer, top‐outer, top‐inner, inner, bottom‐inner, bottom‐outer]
RIGHT_EYE_LANDMARKS = [263, 387, 385, 362, 380, 373]   # same pattern on right eye
MOUTH_LANDMARKS     = [13, 14, 78, 308, 61, 291]       # [upper_lip, lower_lip, left_corner, right_corner, top_inner, bottom_inner]

# ---------------------------------------------------------------------
# Helper functions to compute EAR and MAR
# ---------------------------------------------------------------------
def compute_EAR(landmarks, indices, img_w, img_h):
    """
    Compute Eye Aspect Ratio (EAR) given 6 landmarks:
      P1=outer corner, P2=top‐outer, P3=top‐inner, P4=inner corner, P5=bottom‐inner, P6=bottom‐outer.
    EAR = (‖P2–P6‖ + ‖P3–P5‖) / (2 * ‖P1–P4‖).
    """
    pts = []
    for i in indices:
        lm = landmarks[i]
        x_px = int(lm.x * img_w)
        y_px = int(lm.y * img_h)
        pts.append((x_px, y_px))
    P1 = np.array(pts[0])
    P2 = np.array(pts[1])
    P3 = np.array(pts[2])
    P4 = np.array(pts[3])
    P5 = np.array(pts[4])
    P6 = np.array(pts[5])

    vert1 = np.linalg.norm(P2 - P6)
    vert2 = np.linalg.norm(P3 - P5)
    horiz = np.linalg.norm(P1 - P4)
    if horiz == 0:
        return 0.0
    ear = (vert1 + vert2) / (2.0 * horiz)
    return float(ear)

def compute_MAR(landmarks, indices, img_w, img_h):
    """
    Compute Mouth Aspect Ratio (MAR) given 6 landmarks:
      P_upper = indices[0], P_lower = indices[1],
      P_left   = indices[2], P_right = indices[3].
    MAR = ‖P_upper − P_lower‖ / ‖P_left − P_right‖.
    """
    pts = []
    for i in indices:
        lm = landmarks[i]
        x_px = int(lm.x * img_w)
        y_px = int(lm.y * img_h)
        pts.append((x_px, y_px))
    P_upper = np.array(pts[0])
    P_lower = np.array(pts[1])
    P_left  = np.array(pts[2])
    P_right = np.array(pts[3])

    A = np.linalg.norm(P_upper - P_lower)
    B = np.linalg.norm(P_left - P_right)
    if B == 0:
        return 0.0
    mar = A / B
    return float(mar)

# ---------------------------------------------------------------------
# Main preprocessing logic: compute EAR and MAR for each frame
# ---------------------------------------------------------------------
def preprocess_frame(frame_packet):
    """
    Takes:
      frame_packet = {
        "frame": <BGR numpy array>,
        "t_capture": <timestamp>
      }
    Returns:
      {
        "t_capture": <same timestamp>,
        "blink_score": <float EAR average>,
        "yawn_score": <float MAR>
      }
    or None if detection fails.
    """
    frame     = frame_packet["frame"]
    t_capture = frame_packet["t_capture"]

    h, w = frame.shape[:2]
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb_frame)

    if not results.multi_face_landmarks:
        logger.warning("preprocessing: no face detected.")
        return None

    landmarks = results.multi_face_landmarks[0].landmark

    # Compute left‐eye EAR
    ear_left  = compute_EAR(landmarks, LEFT_EYE_LANDMARKS, w, h)
    # Compute right‐eye EAR
    ear_right = compute_EAR(landmarks, RIGHT_EYE_LANDMARKS, w, h)
    blink_score = (ear_left + ear_right) / 2.0

    # Compute mouth MAR
    mar = compute_MAR(landmarks, MOUTH_LANDMARKS, w, h)
    yawn_score = mar

    return {
        "t_capture":  t_capture,
        "blink_score": blink_score,
        "yawn_score":  yawn_score
    }

def main():
    try:
        while True:
            try:
                packet = camera_to_preproc_queue.get(timeout=1)
            except Exception:
                # No new frame, still write heartbeat
                write_heartbeat("preprocessing")
                continue

            out = preprocess_frame(packet)
            if out:
                try:
                    preproc_to_inference_queue.put_nowait(out)
                except Exception:
                    # queue full → drop oldest then retry
                    try:
                        preproc_to_inference_queue.get_nowait()
                        preproc_to_inference_queue.put_nowait(out)
                        logger.warning("preprocessing: inference_queue overflow – oldest dropped.")
                    except Exception:
                        pass

            write_heartbeat("preprocessing")

    except KeyboardInterrupt:
        logger.info("preprocessing stopping...")
    except Exception:
        logger.exception("preprocessing crashed:")
    finally:
        face_mesh.close()

if __name__ == "__main__":
    main()
