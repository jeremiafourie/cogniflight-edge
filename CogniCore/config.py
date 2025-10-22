"""
CogniCore Configuration

Centralized configuration for the CogniFlight Edge system.
"""

import os

# Base URLs and endpoints
SERVER_BASE_URL = "https://cogniflight.exequtech.com"
ENDPOINT_FACE_EMBEDDINGS = "/pilots/face_embeddings/sse"
ENDPOINT_PILOT_PROFILE = "/pilots/{pilot_id}"

# API Authentication
API_KEY = os.getenv('COGNIFLIGHT_API_KEY', 'your-api-key-here')

# Default HR sensor MAC address - XOSS X2 BLE heart rate monitor
DEFAULT_HR_SENSOR_MAC = "E7:DB:DB:85:B4:67"

# File paths - use working directory relative paths (deployment agnostic)
# Services run from their own directories, so use relative paths from working dir
EMBEDDINGS_FILE = os.getenv('EMBEDDINGS_FILE', 'embeddings.pkl')


# Service configuration
SERVICES = [
    "alert_manager",
    "bio_monitor",
    "https_client",
    "vision_processor",  # Now handles both authentication and fatigue monitoring
    "network_connector",
    "predictor",
    "env_monitor",
    "motion_controller"
]
