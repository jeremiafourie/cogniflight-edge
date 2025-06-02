# services/local_logger/main.py

import os
import time
import sqlite3
import json

from common.queues import (
    camera_to_preproc_queue,
    preproc_to_inference_queue,
    predict_queue,
    hr_queue,
    sensor_queue,
    stage_change_queue,
)
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("local_logger")

# Path to encrypted or unencrypted SQLite (you can swap to SQLCipher later)
LOG_DB = "/opt/edge-software/logs/edge_logs.db"

# When to flush logs to disk (seconds) or if >= BATCH_SIZE entries
BATCH_INTERVAL = 5
BATCH_SIZE     = 50

def init_log_db():
    os.makedirs(os.path.dirname(LOG_DB), exist_ok=True)
    conn = sqlite3.connect(LOG_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       REAL,
            service  TEXT,
            message  TEXT
        )
    """)
    conn.commit()
    conn.close()

def flush_logs(entries):
    """
    entries: list of tuples (ts, service, message)
    """
    conn = sqlite3.connect(LOG_DB)
    c = conn.cursor()
    c.executemany(
        "INSERT INTO logs (ts, service, message) VALUES (?, ?, ?)",
        entries
    )
    conn.commit()
    conn.close()

def main():
    init_log_db()
    buffer = []
    last_flush = time.time()

    try:
        while True:
            now = time.time()

            # 1) Check for any stage_change events
            try:
                evt = stage_change_queue.get_nowait()
                entry = (now, "local_logger", f"stage_change → {json.dumps(evt)}")
                buffer.append(entry)
            except Exception:
                pass

            # 2) Optionally record queue‐drops or queue‐puts for other queues:
            #    For brevity, we record only stage_change here. Extend as needed.

            # 3) Flush if enough time has passed or buffer is large
            if buffer and ((now - last_flush) >= BATCH_INTERVAL or len(buffer) >= BATCH_SIZE):
                try:
                    flush_logs(buffer)
                    buffer.clear()
                    last_flush = now
                except Exception as e:
                    logger.error(f"local_logger: failed to write logs: {e}")

            write_heartbeat("local_logger")
            time.sleep(1)

    except KeyboardInterrupt:
        logger.info("local_logger: received KeyboardInterrupt, stopping...")
    except Exception:
        logger.exception("local_logger: crashed with an unexpected error")
    finally:
        # Flush any remaining logs before exit
        if buffer:
            try:
                flush_logs(buffer)
            except Exception:
                pass
        logger.info("local_logger: exited cleanly")

if __name__ == "__main__":
    main()
