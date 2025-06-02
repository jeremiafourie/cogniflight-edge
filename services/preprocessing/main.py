import time
import cv2
import numpy as np

from common.queues import camera_to_preproc_queue, preproc_to_inference_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("preprocessing")

# Haar cascade file paths (adjust if needed):
FACE_CASCADE_PATH = "/usr/share/opencv4/haarcascades/haarcascade_frontalface_default.xml"
EYE_CASCADE_PATH  = "/usr/share/opencv4/haarcascades/haarcascade_eye.xml"
MOUTH_CASCADE_PATH = "/usr/share/opencv4/haarcascades/haarcascade_mcs_mouth.xml"

def detect_and_crop(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    face_cascade = cv2.CascadeClassifier(FACE_CASCADE_PATH)
    faces = face_cascade.detectMultiScale(gray, 1.1, 4)
    if len(faces) == 0:
        return None, None  # no face detected
    x, y, w, h = faces[0]
    face_roi = gray[y:y+h, x:x+w]

    eye_cascade = cv2.CascadeClassifier(EYE_CASCADE_PATH)
    eyes = eye_cascade.detectMultiScale(face_roi)
    eye_patch = None
    if len(eyes) > 0:
        ex, ey, ew, eh = eyes[0]
        eye_patch = face_roi[ey:ey+eh, ex:ex+ew]

    mouth_cascade = cv2.CascadeClassifier(MOUTH_CASCADE_PATH)
    mouths = mouth_cascade.detectMultiScale(face_roi, 1.5, 5)
    mouth_patch = None
    if len(mouths) > 0:
        mx, my, mw, mh = mouths[0]
        mouth_patch = face_roi[my:my+mh, mx:mx+mw]

    return eye_patch, mouth_patch, frame  # return face‐image for fallback if necessary

def preprocess_frame(frame_packet):
    frame = frame_packet["frame"]
    t_capture = frame_packet["t_capture"]

    eye_patch, mouth_patch, raw = detect_and_crop(frame)
    if eye_patch is None or mouth_patch is None:
        logger.warning("preprocessing: no face/eyes/mouth detected.")
        return None

    # Resize to model input dims:
    eye_resized = cv2.resize(eye_patch, (64, 64))
    mouth_resized = cv2.resize(mouth_patch, (128, 128))

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
