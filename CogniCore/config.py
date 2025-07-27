"""
CogniCore Configuration

Centralized configuration for the CogniFlight Edge system.
All configuration values are consolidated here to eliminate dependencies
on the old common.config module.
"""

import os

# Project root directory
PROJECT_ROOT = "/home/jeremia/Desktop/cogniflight-edge"

# Device MAC, used when requesting pilot profile
DEVICE_MAC = "AA:BB:CC:DD:EE:FF"

# Base URLs and endpoints
SERVER_BASE_URL = "https://cogniflight.exequtech.com"
ENDPOINT_FACE_EMBEDDINGS = "/pilots/face_embeddings/sse"
ENDPOINT_PILOT_PROFILE = "/pilots/{pilot_id}"

# API Authentication
API_KEY = os.getenv('COGNIFLIGHT_API_KEY', 'your-api-key-here')

# Default HR sensor MAC address (from prototype)
DEFAULT_HR_SENSOR_MAC = "E7:DB:DB:85:B4:67"

# Heartbeat directory (each service writes a .hb file here)
# Use environment variable or fallback to user-accessible directory
HEARTBEAT_DIR = os.getenv('HEARTBEAT_DIR', '/run/cogniflight')

# File paths - using actual project structure
EMBEDDINGS_FILE = os.path.join(PROJECT_ROOT, "services/face_recognition/embeddings.pkl")

# Path to local model cache
MODEL_DIR = "/opt/models"
MODEL_PATH = os.path.join(MODEL_DIR, "face_recognition.tflite")
MODEL_VERSION_FILE = os.path.join(MODEL_DIR, "version.txt")

# Service configuration
SERVICES = [
    "alert_manager",
    "hr_monitor", 
    "face_recognition",
    "https_client",
    "vision_processing",
    "inference",
    "network_connector",
    "predictor",
    "env_monitor"
]