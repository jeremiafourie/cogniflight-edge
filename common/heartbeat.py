# common/heartbeat.py
# Utility to write a heartbeat file every N seconds.

import os
import time

def write_heartbeat(service_name: str):
    """
    Call this periodically from each service’s main loop.
    It writes /run/edge_hb/<service_name>.hb with current timestamp.
    """
    hb_dir = os.path.abspath(os.environ.get("HEARTBEAT_DIR", "/run/edge_hb"))
    if not os.path.exists(hb_dir):
        try:
            os.makedirs(hb_dir, exist_ok=True)
        except PermissionError:
            pass
    hb_path = os.path.join(hb_dir, f"{service_name}.hb")
    with open(hb_path, "w") as f:
        f.write(str(int(time.time())))
