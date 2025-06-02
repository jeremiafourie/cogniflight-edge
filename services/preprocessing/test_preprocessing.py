# test_preprocessing.py

import os
import time
import threading
import queue
import cv2
import numpy as np
import mediapipe as mp

# ---------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------

# Maximum queue size before dropping
QUEUE_MAXSIZE = 5

# Output directories
OUTPUT_DIR        = "output"
FACES_DIR         = os.path.join(OUTPUT_DIR, "faces")
EYES_DIR          = os.path.join(OUTPUT_DIR, "eyes")
EYES_LEFT_RAW     = os.path.join(EYES_DIR, "left_raw")
EYES_LEFT_RES     = os.path.join(EYES_DIR, "left_resized")
EYES_RIGHT_RAW    = os.path.join(EYES_DIR, "right_raw")
EYES_RIGHT_RES    = os.path.join(EYES_DIR, "right_resized")
MOUTHS_DIR        = os.path.join(OUTPUT_DIR, "mouths")

# Create output folders
os.makedirs(FACES_DIR, exist_ok=True)
os.makedirs(EYES_LEFT_RAW, exist_ok=True)
os.makedirs(EYES_LEFT_RES, exist_ok=True)
os.makedirs(EYES_RIGHT_RAW, exist_ok=True)
os.makedirs(EYES_RIGHT_RES, exist_ok=True)
os.makedirs(MOUTHS_DIR, exist_ok=True)

# Camera settings
CAMERA_ID    = 0
FRAME_WIDTH  = 640
FRAME_HEIGHT = 360

# MediaPipe Face Mesh
mp_face_mesh = mp.solutions.face_mesh
face_mesh = mp_face_mesh.FaceMesh(
    static_image_mode=False,
    max_num_faces=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
)

# Landmark indices for left and right eyes (MediaPipe 468 landmarks)
LEFT_EYE_IDX = [
    33, 133, 159, 145, 23, 24, 153, 154, 155, 133, 144, 163, 7, 246, 161, 160, 159, 158, 157, 173
]
RIGHT_EYE_IDX = [
    362, 263, 386, 374, 253, 254, 373, 374, 385, 362, 380, 390, 249, 466, 388, 387, 386, 385, 384, 398
]

# Landmark indices for mouth (expanded set)
MOUTH_IDX = [
    78, 308, 13, 14, 61, 291, 0, 17, 37, 267, 82, 312
]

# Shared queue between camera and preprocessing
camera_to_preproc_queue = queue.Queue(maxsize=QUEUE_MAXSIZE)

# ---------------------------------------------------------------------
# CAMERA THREAD
# ---------------------------------------------------------------------

def camera_thread_fn():
    """
    Captures frames from webcam and enqueues packets with:
    { "frame": <BGR array>, "t_capture": <timestamp>, "frame_id": <int> }.
    Drops oldest if queue full.
    """
    cap = cv2.VideoCapture(CAMERA_ID)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    frame_counter = 0
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                continue

            packet = {
                "frame": frame,
                "t_capture": time.time(),
                "frame_id": frame_counter
            }
            frame_counter += 1

            try:
                camera_to_preproc_queue.put_nowait(packet)
            except queue.Full:
                camera_to_preproc_queue.get_nowait()
                camera_to_preproc_queue.put_nowait(packet)

            time.sleep(1.0 / 30.0)  # ~30 FPS

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()

# ---------------------------------------------------------------------
# DETECT & CROP FUNCTION
# ---------------------------------------------------------------------

def detect_and_crop(frame):
    """
    Detects face, left+right eye, and mouth using MediaPipe face mesh.
    Returns:
      face_crop (BGR),
      left_eye_raw (grayscale), left_eye_resized (64×64),
      right_eye_raw (grayscale), right_eye_resized (64×64),
      mouth_crop (128×128 grayscale)
    If detection fails, returns all None.
    """
    h, w = frame.shape[:2]
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = face_mesh.process(rgb)
    if not results.multi_face_landmarks:
        return (None, None, None, None, None, None)

    landmarks = results.multi_face_landmarks[0].landmark
    pts = np.array([[int(lm.x * w), int(lm.y * h)] for lm in landmarks])

    # 1) Full-face bounding box
    x_coords = pts[:, 0]
    y_coords = pts[:, 1]
    fx_min, fx_max = max(0, x_coords.min()), min(w - 1, x_coords.max())
    fy_min, fy_max = max(0, y_coords.min()), min(h - 1, y_coords.max())

    # Pad face by 10%
    fw = fx_max - fx_min
    fh = fy_max - fy_min
    pad_fx = int(0.1 * fw)
    pad_fy = int(0.1 * fh)

    fx1 = max(0, fx_min - pad_fx)
    fy1 = max(0, fy_min - pad_fy)
    fx2 = min(w, fx_max + pad_fx)
    fy2 = min(h, fy_max + pad_fy)

    if fx2 <= fx1 or fy2 <= fy1:
        return (None, None, None, None, None, None)

    face_crop = frame[fy1:fy2, fx1:fx2]

    # 2) Left-eye bounding box
    left_pts = np.array([pts[idx] for idx in LEFT_EYE_IDX])
    lex = left_pts[:, 0]
    ley = left_pts[:, 1]
    le_xmin, le_xmax = max(0, lex.min()), min(w - 1, lex.max())
    le_ymin, le_ymax = max(0, ley.min()), min(h - 1, ley.max())

    # Pad left eye by 30% vertical, 20% horizontal
    le_w = le_xmax - le_xmin
    le_h = le_ymax - le_ymin
    pad_le_x = int(0.2 * le_w)
    pad_le_y = int(0.3 * le_h)

    le_x1 = max(0, le_xmin - pad_le_x)
    le_y1 = max(0, le_ymin - pad_le_y)
    le_x2 = min(w, le_xmax + pad_le_x)
    le_y2 = min(h, le_ymax + pad_le_y)

    if le_x2 <= le_x1 or le_y2 <= le_y1:
        left_eye_raw = None
        left_eye_resized = None
    else:
        left_eye_bgr = frame[le_y1:le_y2, le_x1:le_x2]
        left_eye_gray = cv2.cvtColor(left_eye_bgr, cv2.COLOR_BGR2GRAY)
        left_eye_raw = left_eye_gray.copy()
        try:
            left_eye_resized = cv2.resize(left_eye_gray, (64, 64))
        except Exception:
            left_eye_resized = None

    # 3) Right-eye bounding box
    right_pts = np.array([pts[idx] for idx in RIGHT_EYE_IDX])
    rex = right_pts[:, 0]
    rey = right_pts[:, 1]
    re_xmin, re_xmax = max(0, rex.min()), min(w - 1, rex.max())
    re_ymin, re_ymax = max(0, rey.min()), min(h - 1, rey.max())

    # Pad right eye by 30% vertical, 20% horizontal
    re_w = re_xmax - re_xmin
    re_h = re_ymax - re_ymin
    pad_re_x = int(0.2 * re_w)
    pad_re_y = int(0.3 * re_h)

    re_x1 = max(0, re_xmin - pad_re_x)
    re_y1 = max(0, re_ymin - pad_re_y)
    re_x2 = min(w, re_xmax + pad_re_x)
    re_y2 = min(h, re_ymax + pad_re_y)

    if re_x2 <= re_x1 or re_y2 <= re_y1:
        right_eye_raw = None
        right_eye_resized = None
    else:
        right_eye_bgr = frame[re_y1:re_y2, re_x1:re_x2]
        right_eye_gray = cv2.cvtColor(right_eye_bgr, cv2.COLOR_BGR2GRAY)
        right_eye_raw = right_eye_gray.copy()
        try:
            right_eye_resized = cv2.resize(right_eye_gray, (64, 64))
        except Exception:
            right_eye_resized = None

    # 4) Mouth bounding box
    mouth_pts = np.array([pts[idx] for idx in MOUTH_IDX])
    mx = mouth_pts[:, 0]
    my = mouth_pts[:, 1]
    m_xmin, m_xmax = max(0, mx.min()), min(w - 1, mx.max())
    m_ymin, m_ymax = max(0, my.min()), min(h - 1, my.max())

    # Pad mouth by 40% vertical, 20% horizontal
    m_w = m_xmax - m_xmin
    m_h = m_ymax - m_ymin
    pad_mx = int(0.2 * m_w)
    pad_my = int(0.4 * m_h)

    m_x1 = max(0, m_xmin - pad_mx)
    m_y1 = max(0, m_ymin - pad_my)
    m_x2 = min(w, m_xmax + pad_mx)
    m_y2 = min(h, m_ymax + pad_my)

    if m_x2 <= m_x1 or m_y2 <= m_y1:
        mouth_crop = None
    else:
        mouth_bgr = frame[m_y1:m_y2, m_x1:m_x2]
        mouth_gray = cv2.cvtColor(mouth_bgr, cv2.COLOR_BGR2GRAY)
        try:
            mouth_crop = cv2.resize(mouth_gray, (128, 128))
        except Exception:
            mouth_crop = None

    return face_crop, left_eye_raw, left_eye_resized, right_eye_raw, right_eye_resized, mouth_crop

# ---------------------------------------------------------------------
# PREPROCESSING THREAD
# ---------------------------------------------------------------------

def preprocessing_thread_fn():
    """
    Consumes frames from queue, crops face/eyes/mouth, writes:
      - face_<id>_<ts>.png
      - eye_left_raw_<id>_<ts>.png
      - eye_left_res_<id>_<ts>.png
      - eye_right_raw_<id>_<ts>.png
      - eye_right_res_<id>_<ts>.png
      - mouth_<id>_<ts>.png
    """
    while True:
        try:
            packet = camera_to_preproc_queue.get(timeout=1)
        except queue.Empty:
            continue

        frame      = packet["frame"]
        frame_id   = packet["frame_id"]
        timestamp  = int(packet["t_capture"] * 1000)

        (face_crop,
         left_eye_raw, left_eye_res,
         right_eye_raw, right_eye_res,
         mouth_crop) = detect_and_crop(frame)

        if face_crop is None:
            print(f"[Preproc] Frame {frame_id}: no face detected.")
            continue

        # Save full-face crop
        face_fname = os.path.join(FACES_DIR, f"face_{frame_id}_{timestamp}.png")
        cv2.imwrite(face_fname, face_crop)

        # Save left eye crops
        if left_eye_raw is None:
            print(f"[Preproc] Frame {frame_id}: left eye crop failed.")
        else:
            left_raw_fname = os.path.join(EYES_LEFT_RAW, f"eye_left_raw_{frame_id}_{timestamp}.png")
            cv2.imwrite(left_raw_fname, left_eye_raw)
            if left_eye_res is not None:
                left_res_fname = os.path.join(EYES_LEFT_RES, f"eye_left_res_{frame_id}_{timestamp}.png")
                cv2.imwrite(left_res_fname, left_eye_res)

        # Save right eye crops
        if right_eye_raw is None:
            print(f"[Preproc] Frame {frame_id}: right eye crop failed.")
        else:
            right_raw_fname = os.path.join(EYES_RIGHT_RAW, f"eye_right_raw_{frame_id}_{timestamp}.png")
            cv2.imwrite(right_raw_fname, right_eye_raw)
            if right_eye_res is not None:
                right_res_fname = os.path.join(EYES_RIGHT_RES, f"eye_right_res_{frame_id}_{timestamp}.png")
                cv2.imwrite(right_res_fname, right_eye_res)

        # Save mouth crop
        if mouth_crop is None:
            print(f"[Preproc] Frame {frame_id}: mouth crop failed.")
        else:
            mouth_fname = os.path.join(MOUTHS_DIR, f"mouth_{frame_id}_{timestamp}.png")
            cv2.imwrite(mouth_fname, mouth_crop)

        print(f"[Preproc] Saved crops for frame {frame_id}.")

# ---------------------------------------------------------------------
# MAIN ENTRY POINT
# ---------------------------------------------------------------------

if __name__ == "__main__":
    # Start camera thread
    cam_thread = threading.Thread(target=camera_thread_fn, daemon=True)
    cam_thread.start()

    # Start preprocessing thread
    preproc_thread = threading.Thread(target=preprocessing_thread_fn, daemon=True)
    preproc_thread.start()

    print("Test running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Exiting test…")

    face_mesh.close()
