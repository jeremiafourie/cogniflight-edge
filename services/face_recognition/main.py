# services/face_recognition/main.py

import time
import os
import traceback
import cv2
import tflite_runtime.interpreter as tflite
import numpy as np

import common.config as cfg
from common.queues import camera_to_preproc_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

import RPi.GPIO as GPIO
from queue import Empty

logger = configure_logging("face_recognition")

# GPIO pins (BCM):
BLUE_LED_PIN = 27
GREEN_LED_PIN = 17

# Face‐to‐embedding threshold (example):
EMBEDDING_THRESHOLD = 0.6

def load_embeddings(path="embeddings.pkl"):
    """
    Load precomputed embeddings (pickle of dict: {pilot_id: embedding_array})
    """
    import pickle
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    return {}

def compare_embedding(known_embeddings, face_embedding):
    """
    Simple Euclidean or cosine‐normalized comparison.
    Return pilot_id if match found, else None.
    """
    for pilot_id, emb in known_embeddings.items():
        dist = np.linalg.norm(emb - face_embedding)
        if dist < EMBEDDING_THRESHOLD:
            return pilot_id
    return None

def initialize_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(BLUE_LED_PIN, GPIO.OUT)
    GPIO.setup(GREEN_LED_PIN, GPIO.OUT)
    GPIO.output(GREEN_LED_PIN, GPIO.LOW)

def blink_blue_led(stop_event):
    """
    Internal thread that toggles BLUE_LED_PIN at 2 Hz until pilot is found.
    """
    while not stop_event.is_set():
        GPIO.output(BLUE_LED_PIN, GPIO.HIGH)
        time.sleep(0.25)
        GPIO.output(BLUE_LED_PIN, GPIO.LOW)
        time.sleep(0.25)

def run_face_recognition():
    # 1) Load model
    if not os.path.exists(cfg.MODEL_PATH):
        logger.error("Face model not found. Exiting.")
        return

    interpreter = tflite.Interpreter(model_path=cfg.MODEL_PATH)
    interpreter.allocate_tensors()

    # 2) Load known embeddings:
    known_embeddings = load_embeddings("/opt/embeddings/embeddings.pkl")

    # 3) Setup video capture at 5 FPS (skip frames if needed)
    cap = cv2.VideoCapture(0)  # assume CSI camera is /dev/video0
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
    # If 5 FPS is required, read at 30 FPS but process every 6th frame:
    frame_interval = 6
    frame_count = 0

    stop_event = __import__("threading").Event()
    import threading
    blink_thread = threading.Thread(target=blink_blue_led, args=(stop_event,))
    blink_thread.start()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.warning("Camera read failed.")
                continue

            frame_count += 1
            if frame_count % frame_interval != 0:
                continue  # skip until next 5 FPS

            # Preprocessing: detect face, crop & resize to model input dims.
            # (Insert your own face‐detection here; placeholder below)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            face = gray  # replace with actual face crop
            resized = cv2.resize(face, (128, 128))
            inp = np.expand_dims(resized, axis=(0, 3)) / 255.0  # shape (1,128,128,1)

            # Run inference:
            input_index = interpreter.get_input_details()[0]["index"]
            output_index = interpreter.get_output_details()[0]["index"]
            interpreter.set_tensor(input_index, inp.astype(np.float32))
            interpreter.invoke()
            emb_output = interpreter.get_tensor(output_index).reshape(-1)

            # Compare embeddings:
            pilot_id = compare_embedding(known_embeddings, emb_output)
            if pilot_id:
                # Stop blinking blue LED; turn GREEN ON
                stop_event.set()
                GPIO.output(BLUE_LED_PIN, GPIO.LOW)
                GPIO.output(GREEN_LED_PIN, GPIO.HIGH)
                logger.info(f"Pilot identified: {pilot_id}")
                # Publish event to config or to common queue (if you had a bus)
                # e.g. camera_to_preproc_queue.put({"event": "pilot_identified", "pilot_id": pilot_id})
                break

    except KeyboardInterrupt:
        logger.info("face_recognition interrupted by user.")
    except Exception:
        logger.exception("face_recognition crashed:")
    finally:
        cap.release()
        GPIO.cleanup()
        stop_event.set()
        blink_thread.join()

# Once a pilot_id is found, the snippet toggles LEDs and exits. In your real flow, you’d publish pilot_identified to an internal event bus or database, then let Supervisor spawn the next services (camera/preproc/inference/etc.).