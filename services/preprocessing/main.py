import time
import cv2
import numpy as np
import mediapipe as mp

from common.queues import camera_to_preproc_queue, preproc_to_inference_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("preprocessing")

# Initialize MediaPipe Face Mesh once
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=False,
    max_num_faces=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# Landmark indices for eyes and mouth (MediaPipe 468-landmark model)
LEFT_EYE_IDX = [33, 246, 161, 160, 159, 158, 157, 173, 133, 155, 154, 153, 145, 144, 163, 7]
RIGHT_EYE_IDX = [362, 398, 384, 385, 386, 387, 388, 466, 263, 249, 390, 373, 374, 380, 381, 382]
MOUTH_IDX = [78, 308, 13, 14, 61, 291]

def detect_and_crop(frame):
    """
    Uses MediaPipe Face Mesh to detect facial landmarks, then crops eye and mouth patches.
    Returns (eye_patch_gray, mouth_patch_gray) in grayscale.
    If no face or if cropping fails, returns (None, None).
    """
    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)
    if not results.multi_face_landmarks:
        return None, None

    # Take first face
    landmarks = results.multi_face_landmarks[0].landmark

    # Helper to convert normalized landmark to pixel coords
    def lm_to_point(idx):
        lm = landmarks[idx]
        x_px = int(lm.x * w)
        y_px = int(lm.y * h)
        return x_px, y_px

    # Compute bounding box around left eye
    eye_points = [lm_to_point(idx) for idx in LEFT_EYE_IDX + RIGHT_EYE_IDX]
    ex_coords = [pt[0] for pt in eye_points]
    ey_coords = [pt[1] for pt in eye_points]
    ex_min, ex_max = max(0, min(ex_coords)), min(w, max(ex_coords))
    ey_min, ey_max = max(0, min(ey_coords)), min(h, max(ey_coords))
    # Add small padding
    ex_pad = int(0.1 * (ex_max - ex_min))
    ey_pad = int(0.1 * (ey_max - ey_min))
    ex1 = max(0, ex_min - ex_pad)
    ey1 = max(0, ey_min - ey_pad)
    ex2 = min(w, ex_max + ex_pad)
    ey2 = min(h, ey_max + ey_pad)
    if ex2 <= ex1 or ey2 <= ey1:
        return None, None
    eye_crop = frame[ey1:ey2, ex1:ex2]

    # Compute bounding box around mouth
    mouth_points = [lm_to_point(idx) for idx in MOUTH_IDX]
    mx_coords = [pt[0] for pt in mouth_points]
    my_coords = [pt[1] for pt in mouth_points]
    mx_min, mx_max = max(0, min(mx_coords)), min(w, max(mx_coords))
    my_min, my_max = max(0, min(my_coords)), min(h, max(my_coords))
    # Add padding
    mx_pad = int(0.2 * (mx_max - mx_min))
    my_pad = int(0.2 * (my_max - my_min))
    mx1 = max(0, mx_min - mx_pad)
    my1 = max(0, my_min - my_pad)
    mx2 = min(w, mx_max + mx_pad)
    my2 = min(h, my_max + my_pad)
    if mx2 <= mx1 or my2 <= my1:
        return None, None
    mouth_crop = frame[my1:my2, mx1:mx2]

    # Convert to grayscale
    eye_gray = cv2.cvtColor(eye_crop, cv2.COLOR_BGR2GRAY)
    mouth_gray = cv2.cvtColor(mouth_crop, cv2.COLOR_BGR2GRAY)

    return eye_gray, mouth_gray

def preprocess_frame(frame_packet):
    frame = frame_packet["frame"]
    t_capture = frame_packet["t_capture"]

    eye_patch, mouth_patch = detect_and_crop(frame)
    if eye_patch is None or mouth_patch is None:
        logger.warning("preprocessing: no face/eyes/mouth detected.")
        return None

    # Resize to model input dimensions
    try:
        eye_resized = cv2.resize(eye_patch, (64, 64))
        mouth_resized = cv2.resize(mouth_patch, (128, 128))
    except Exception as e:
        logger.warning(f"preprocessing: resizing failed: {e}")
        return None

    inference_input = {
        "eye": eye_resized,
        "mouth": mouth_resized,
        "t_capture": t_capture
    }
    return inference_input

def main():
    try:
        while True:
            try:
                packet = camera_to_preproc_queue.get(timeout=1)
            except Exception:
                # no frame; still write heartbeat
                write_heartbeat("preprocessing")
                continue

            inf_input = preprocess_frame(packet)
            if inf_input:
                try:
                    preproc_to_inference_queue.put_nowait(inf_input)
                except Exception:
                    # drop oldest and retry
                    try:
                        preproc_to_inference_queue.get_nowait()
                        preproc_to_inference_queue.put_nowait(inf_input)
                        logger.warning("preprocessing: inference_queue overflow – oldest dropped.")
                    except Exception:
                        pass

            write_heartbeat("preprocessing")

    except KeyboardInterrupt:
        logger.info("preprocessing stopping...")
    except Exception:
        logger.exception("preprocessing crashed:")

if __name__ == "__main__":
    main()
