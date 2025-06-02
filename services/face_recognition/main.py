import os
import time
import pickle
import threading

import cv2
import numpy as np
import RPi.GPIO as GPIO

import insightface.app as ia
# from common.heartbeat import write_heartbeat
# from common.utils import configure_logging

# logger = configure_logging("face_recognition")

# GPIO pins (BCM numbering)
BLUE_LED_PIN  = 27
GREEN_LED_PIN = 17

# Paths
EMBEDDING_PATH = "./embeddings.pkl"

# Recognition settings
RECOGNITION_THRESHOLD = 0.4  # cosine similarity threshold

# FaceAnalysis model name
FACE_MODEL_NAME = "buffalo_s"


def initialize_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(BLUE_LED_PIN, GPIO.OUT)
    GPIO.setup(GREEN_LED_PIN, GPIO.OUT)
    GPIO.output(GREEN_LED_PIN, GPIO.LOW)


def blink_blue_led(stop_event):
    while not stop_event.is_set():
        GPIO.output(BLUE_LED_PIN, GPIO.HIGH)
        time.sleep(0.25)
        GPIO.output(BLUE_LED_PIN, GPIO.LOW)
        time.sleep(0.25)


def load_known_embeddings(path):
    if not os.path.exists(path):
        # logger.error(f"Embeddings file not found at {path}")
        print(f"Embeddings file not found at {path}")
        return {}
    with open(path, "rb") as f:
        embeddings = pickle.load(f)
    # Normalize each embedding to unit length
    for pid, emb in embeddings.items():
        norm = np.linalg.norm(emb)
        if norm > 0:
            embeddings[pid] = emb / norm
    return embeddings


def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def recognize_face(frame, face_app, known_embeddings, threshold):
    """
    Runs InsightFace FaceAnalysis on the BGR frame,
    returns the best matching pilot_id or None.
    """
    faces = face_app.get(frame)
    if not faces:
        return None

    # Take the first detected face
    face = faces[0]
    emb = face.embedding
    # Normalize embedding
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm

    best_match = None
    best_sim = -1.0

    for pid, known_emb in known_embeddings.items():
        sim = cosine_similarity(emb, known_emb)
        if sim > best_sim:
            best_sim = sim
            best_match = pid

    if best_sim >= threshold:
        return best_match
    return None


def main():
    initialize_gpio()

    # Load known embeddings
    known_embeddings = load_known_embeddings(EMBEDDING_PATH)
    if not known_embeddings:
        # logger.error("No known embeddings loaded; exiting.")
        print("No known embeddings loaded; exiting.")
        return

    # Initialize InsightFace FaceAnalysis
    try:
        face_app = ia.FaceAnalysis(name=FACE_MODEL_NAME, providers=["CPUExecutionProvider"])
        face_app.prepare(ctx_id=0, det_size=(640, 640))
    except Exception as e:
        # logger.exception(f"Failed to initialize FaceAnalysis: {e}")
        return

    # Open camera
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)

    # Start blinking blue LED
    stop_event = threading.Event()
    blink_thread = threading.Thread(target=blink_blue_led, args=(stop_event,), daemon=True)
    blink_thread.start()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.1)
                # write_heartbeat("face_recognition")
                continue

            # Recognize face in the current frame
            pilot_id = recognize_face(frame, face_app, known_embeddings, RECOGNITION_THRESHOLD)

            if pilot_id:
                # Stop blue LED, turn on green
                stop_event.set()
                GPIO.output(BLUE_LED_PIN, GPIO.LOW)
                GPIO.output(GREEN_LED_PIN, GPIO.HIGH)

                # logger.info(f"Pilot identified: {pilot_id}")
                print(f"Pilot identified: {pilot_id}")
                break

            # write_heartbeat("face_recognition")

    except KeyboardInterrupt:
        # logger.info("face_recognition: interrupted by user")
        print("error")
    except Exception as e:
        # logger.exception(f"face_recognition crashed: {e}")
        print("error")
    finally:
        cap.release()
        GPIO.cleanup()
        stop_event.set()
        blink_thread.join()


if __name__ == "__main__":
    main()
