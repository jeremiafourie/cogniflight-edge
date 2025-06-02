# watchdog/watcher.py

import os
import time
import subprocess

HEARTBEAT_DIR = "/run/edge_hb"
CHECK_INTERVAL = 10  # seconds
TIMEOUT = 10         # seconds before considering a service “stale”

# List all service names exactly as their systemd unit (without “.service” suffix)
SERVICES = [
    "https_client",
    "face_recognition",
    "camera",
    "ble",
    "sensor",
    "preprocessing",
    "inference",
    "predictor",
    "alert_manager",
    "network_connector",
    "local_logger"
]

def restart_service(svc_name: str):
    """
    Runs 'systemctl restart <svc_name>.service'
    """
    unit = f"{svc_name}.service"
    subprocess.run(["systemctl", "restart", unit])

def check_heartbeat(svc_name: str):
    """
    If /run/edge_hb/<svc_name>.hb is missing or older than TIMEOUT,
    restart the corresponding service.
    """
    hb_file = os.path.join(HEARTBEAT_DIR, f"{svc_name}.hb")
    now = time.time()

    if not os.path.exists(hb_file):
        print(f"[watchdog] {svc_name}: no heartbeat file → restarting service")
        restart_service(svc_name)
        return

    try:
        ts = float(open(hb_file).read().strip())
    except Exception:
        ts = 0

    if (now - ts) > TIMEOUT:
        print(f"[watchdog] {svc_name}: heartbeat stale ({now - ts:.1f}s) → restarting service")
        restart_service(svc_name)

def main():
    while True:
        for svc in SERVICES:
            check_heartbeat(svc)
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
