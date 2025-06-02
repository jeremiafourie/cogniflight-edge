import os

# Path to local model cache:
MODEL_DIR = "/opt/models"
MODEL_PATH = os.path.join(MODEL_DIR, "face_recognition.tflite")
MODEL_VERSION_FILE = os.path.join(MODEL_DIR, "version.txt")

# Base URLs and endpoints:
SERVER_BASE_URL = "https://cogniflight.exequtech.com"
ENDPOINT_FACE_EMBEDDINGS    = "/models/face_embeddings/latest"
ENDPOINT_PILOT_PROFILE = "/pilots/{pilot_id}/profile"

# Device MAC, used when requesting pilot profile:
DEVICE_MAC = "AA:BB:CC:DD:EE:FF"  # Replace with actual device MAC or load from config

# Heartbeat directory (each service writes a .hb file here):
HEARTBEAT_DIR = "/run/edge_hb"

# Queue sizes:
QUEUE_CAMERA_TO_PREPROC = 10
QUEUE_PREPROC_TO_INF    = 10
QUEUE_PREDICTOR         = 5
QUEUE_HR                = 5
QUEUE_SENSOR            = 5

# If you need to store embeddings or pilot info:
EMBEDDINGS_FILE = "/opt/embeddings/embeddings.pkl"
PROFILE_DB      = "/opt/edge-software/profiles.db"
