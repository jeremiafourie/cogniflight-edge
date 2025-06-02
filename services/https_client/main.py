# services/https_client/main.py

import os
import time
import hashlib
import random
import requests
import common.config as cfg
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("https_client")

# Exponential backoff parameters
MAX_RETRIES = 5
BASE_DELAY = 2  # seconds
JITTER = 0.2    # ±20%

def read_local_version():
    if os.path.exists(cfg.MODEL_VERSION_FILE):
        with open(cfg.MODEL_VERSION_FILE, "r") as f:
            return f.read().strip()
    return ""

def write_local_version(version: str):
    os.makedirs(os.path.dirname(cfg.MODEL_VERSION_FILE), exist_ok=True)
    with open(cfg.MODEL_VERSION_FILE, "w") as f:
        f.write(version)

def compute_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            h.update(chunk)
    return h.hexdigest()

def fetch_model():
    """
    Fetch /models/face_recognition/latest, validate, save to MODEL_PATH.
    Assume server returns JSON: { "version": "...", "checksum": "...", "url": "..." }
    """
    url = cfg.SERVER_BASE_URL + cfg.ENDPOINT_FACE_MODEL
    retry = 0
    while retry < MAX_RETRIES:
        try:
            resp = requests.get(url, timeout=10, verify=True)
            resp.raise_for_status()
            data = resp.json()
            version = data["version"]
            checksum = data["checksum"]
            model_url = data["url"]

            local_version = read_local_version()
            if local_version == version and os.path.exists(cfg.MODEL_PATH):
                logger.info(f"Model is up‐to‐date (version {version}).")
                return

            # Download
            r2 = requests.get(model_url, stream=True)
            r2.raise_for_status()
            os.makedirs(os.path.dirname(cfg.MODEL_PATH), exist_ok=True)
            with open(cfg.MODEL_PATH, "wb") as f:
                for chunk in r2.iter_content(4096):
                    f.write(chunk)

            # Validate
            local_checksum = compute_sha256(cfg.MODEL_PATH)
            if local_checksum != checksum:
                logger.error("Checksum mismatch. Removing corrupt model.")
                os.remove(cfg.MODEL_PATH)
                raise ValueError("Checksum mismatch")

            write_local_version(version)
            logger.info(f"Model v{version} downloaded and verified.")
            return

        except Exception as e:
            delay = BASE_DELAY * (2 ** retry)
            delay = delay * (1 + random.uniform(-JITTER, JITTER))
            logger.warning(f"Fetch attempt {retry+1} failed: {e}. Retrying in {delay:.1f}s")
            time.sleep(delay)
            retry += 1

    logger.error("Exceeded max retries. Will try again on next boot.")

def main():
    # On boot, ensure model cache directory exists:
    os.makedirs(os.path.dirname(cfg.MODEL_PATH), exist_ok=True)

    # 1. Check if local version is stale (>1 day) or missing:
    if (
        not os.path.exists(cfg.MODEL_PATH)
        or (time.time() - os.path.getmtime(cfg.MODEL_PATH)) > 86400
    ):
        fetch_model()
    else:
        logger.info("Local model is fresh.")

    # Write heartbeat loop:
    try:
        while True:
            write_heartbeat("https_client")
            time.sleep(2)
    except KeyboardInterrupt:
        logger.info("https_client stopping...")
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()
