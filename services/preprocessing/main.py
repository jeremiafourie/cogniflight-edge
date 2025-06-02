import os
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

# Landmark indices for left eye, right eye, and mouth (MediaPipe 468‐point model)
LEFT_EYE_IDX = [
    33, 133, 159, 145, 23, 24, 153, 154, 155, 133, 144, 163, 7, 246, 161, 160, 158, 157, 173
]
RIGHT_EYE_IDX = [
    362, 263, 386, 374, 253, 254, 373, 374, 385, 362, 380, 390, 249, 466, 388, 387, 385, 384, 398
]
MOUTH_IDX = [
    78, 308, 13, 14, 61, 291, 0, 17, 37, 267, 82, 312
]

def detect_and_crop(frame):
    """
    Detects face, left eye, right eye, and mouth using MediaPipe Face Mesh.
    Returns (left_eye_resized, right_eye_resized, mouth_resized, t_capture). If any crop fails, returns (None, None, None).
    """
    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)
    if not results.multi_face_landmarks:
        return None, None, None

    landmarks = results.multi_face_landmarks[0].landmark
    pts = np.array([[int(lm.x * w), int(lm.y * h)] for lm in landmarks])

    # --- Left‐eye crop ----------------------------------------------
    left_pts = np.array([pts[idx] for idx in LEFT_EYE_IDX])
    lex_min, lex_max = max(0, left_pts[:,0].min()), min(w-1, left_pts[:,0].max())
    ley_min, ley_max = max(0, left_pts[:,1].min()), min(h-1, left_pts[:,1].max())
    le_w = lex_max - lex_min
    le_h = ley_max - ley_min
    pad_le_x = int(0.2 * le_w)
    pad_le_y = int(0.3 * le_h)
    le_x1 = max(0, lex_min - pad_le_x)
    le_y1 = max(0, ley_min - pad_le_y)
    le_x2 = min(w, lex_max + pad_le_x)
    le_y2 = min(h, ley_max + pad_le_y)
    if le_x2 <= le_x1 or le_y2 <= le_y1:
        return None, None, None
    left_eye_bgr = frame[le_y1:le_y2, le_x1:le_x2]
    left_eye_gray = cv2.cvtColor(left_eye_bgr, cv2.COLOR_BGR2GRAY)
    try:
        left_eye_resized = cv2.resize(left_eye_gray, (64, 64))
    except Exception:
        return None, None, None

    # --- Right‐eye crop ---------------------------------------------
    right_pts = np.array([pts[idx] for idx in RIGHT_EYE_IDX])
    rex_min, rex_max = max(0, right_pts[:,0].min()), min(w-1, right_pts[:,0].max())
    rey_min, rey_max = max(0, right_pts[:,1].min()), min(h-1, right_pts[:,1].max())
    re_w = rex_max - rex_min
    re_h = rey_max - rey_min
    pad_re_x = int(0.2 * re_w)
    pad_re_y = int(0.3 * re_h)
    re_x1 = max(0, rex_min - pad_re_x)
    re_y1 = max(0, rey_min - pad_re_y)
    re_x2 = min(w, rex_max + pad_re_x)
    re_y2 = min(h, rey_max + pad_re_y)
    if re_x2 <= re_x1 or re_y2 <= re_y1:
        return None, None, None
    right_eye_bgr = frame[re_y1:re_y2, re_x1:re_x2]
    right_eye_gray = cv2.cvtColor(right_eye_bgr, cv2.COLOR_BGR2GRAY)
    try:
        right_eye_resized = cv2.resize(right_eye_gray, (64, 64))
    except Exception:
        return None, None, None

    # --- Mouth crop -------------------------------------------------
    mouth_pts = np.array([pts[idx] for idx in MOUTH_IDX])
    mx_min, mx_max = max(0, mouth_pts[:,0].min()), min(w-1, mouth_pts[:,0].max())
    my_min, my_max = max(0, mouth_pts[:,1].min()), min(h-1, mouth_pts[:,1].max())
    m_w = mx_max - mx_min
    m_h = my_max - my_min
    pad_mx = int(0.2 * m_w)
    pad_my = int(0.4 * m_h)
    mx1 = max(0, mx_min - pad_mx)
    my1 = max(0, my_min - pad_my)
    mx2 = min(w, mx_max + pad_mx)
    my2 = min(h, my_max + pad_my)
    if mx2 <= mx1 or my2 <= my1:
        return None, None, None
    mouth_bgr = frame[my1:my2, mx1:mx2]
    mouth_gray = cv2.cvtColor(mouth_bgr, cv2.COLOR_BGR2GRAY)
    try:
        mouth_resized = cv2.resize(mouth_gray, (128, 128))
    except Exception:
        return None, None, None

    return left_eye_resized, right_eye_resized, mouth_resized

def preprocess_frame(frame_packet):
    frame     = frame_packet["frame"]
    t_capture = frame_packet["t_capture"]

    left_eye, right_eye, mouth = detect_and_crop(frame)
    if left_eye is None or right_eye is None or mouth is None:
        logger.warning("preprocessing: face/eyes/mouth not detected.")
        return None

    inference_input = {
        "left_eye": left_eye,
        "right_eye": right_eye,
        "mouth": mouth,
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
                    # drop oldest
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
