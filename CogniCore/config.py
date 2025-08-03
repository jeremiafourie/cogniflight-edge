"""
CogniCore Configuration

Centralized configuration for the CogniFlight Edge system.
"""

import os

# Project root directory
PROJECT_ROOT = "/home/jeremia/projects/cogniflight-edge-backup"


# Base URLs and endpoints
SERVER_BASE_URL = "https://cogniflight.exequtech.com"
ENDPOINT_FACE_EMBEDDINGS = "/pilots/face_embeddings/sse"
ENDPOINT_PILOT_PROFILE = "/pilots/{pilot_id}"

# API Authentication
API_KEY = os.getenv('COGNIFLIGHT_API_KEY', 'your-api-key-here')

# Default HR sensor MAC address (from prototype)
DEFAULT_HR_SENSOR_MAC = "E7:DB:DB:85:B4:67"


# File paths - using actual project structure
EMBEDDINGS_FILE = os.path.join(PROJECT_ROOT, "services/face_recognition/embeddings.pkl")


# Service configuration
SERVICES = [
    "alert_manager",
    "hr_monitor", 
    "face_recognition",
    "https_client",
    "vision_processing",
    "network_connector",
    "predictor",
    "env_monitor"
]