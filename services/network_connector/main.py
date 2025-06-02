import time
import json
import sqlite3
import threading

import paho.mqtt.client as mqtt

from common.queues import (
    stage_change_queue,
    sensor_queue,
    predict_queue
)
from common.heartbeat import write_heartbeat
from common.utils import configure_logging
import common.config as cfg

logger = configure_logging("network_connector")

# MQTT settings
MQTT_BROKER = "mqtt.yourbroker.com"
MQTT_PORT   = 8883
MQTT_TOPIC  = f"edge/telemetry/{cfg.DEVICE_MAC}"

# Local SQLite outbox (for retry on disconnect)
OUTBOX_DB = "/opt/edge-software/network_outbox.db"

# Retry parameters
RETRY_INTERVAL = 5  # seconds between outbox retries

def init_outbox_db():
    os.makedirs(os.path.dirname(OUTBOX_DB), exist_ok=True)
    conn = sqlite3.connect(OUTBOX_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS outbox (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            ts       REAL,
            payload  TEXT,
            attempts INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def enqueue_to_outbox(payload: dict):
    conn = sqlite3.connect(OUTBOX_DB)
    c = conn.cursor()
    c.execute(
        "INSERT INTO outbox (ts, payload, attempts) VALUES (?, ?, ?)",
        (time.time(), json.dumps(payload), 0)
    )
    conn.commit()
    conn.close()

def publish_payload(client: mqtt.Client, payload: dict) -> bool:
    data = json.dumps(payload)
    result = client.publish(MQTT_TOPIC, data, qos=1)
    return result.rc == mqtt.MQTT_ERR_SUCCESS

def outbox_worker(client: mqtt.Client):
    """
    Background thread that drains the SQLite outbox table.
    Retries every RETRY_INTERVAL seconds.
    """
    while True:
        conn = sqlite3.connect(OUTBOX_DB)
        c = conn.cursor()
        c.execute("SELECT id, payload, attempts FROM outbox")
        rows = c.fetchall()

        for row in rows:
            row_id, payload_str, attempts = row
            payload = json.loads(payload_str)
            success = publish_payload(client, payload)
            if success:
                c.execute("DELETE FROM outbox WHERE id = ?", (row_id,))
                conn.commit()
            else:
                c.execute(
                    "UPDATE outbox SET attempts = ? WHERE id = ?",
                    (attempts + 1, row_id)
                )
                conn.commit()
        conn.close()
        time.sleep(RETRY_INTERVAL)

def build_telemetry():
    """
    Gathers the most recent items from stage_change, sensor, and predict queues
    to assemble a telemetry payload.
    """
    latest_stage = None
    latest_sensor = None
    latest_predict = None

    # Non-blocking drains to grab “latest” item from each queue
    try:
        latest_stage = stage_change_queue.get_nowait()
    except Exception:
        pass

    try:
        latest_sensor = sensor_queue.get_nowait()
    except Exception:
        pass

    try:
        latest_predict = predict_queue.get_nowait()
    except Exception:
        pass

    payload = {
        "timestamp": time.time(),
        "stage": latest_stage,
        "sensor": latest_sensor,
        "prediction": latest_predict
    }
    return payload

def main():
    init_outbox_db()

    client = mqtt.Client()
    client.tls_set()  # Use default TLS context
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    # Start outbox‐retry thread
    threading.Thread(target=outbox_worker, args=(client,), daemon=True).start()

    try:
        while True:
            payload = build_telemetry()
            if client.is_connected():
                ok = publish_payload(client, payload)
                if not ok:
                    enqueue_to_outbox(payload)
                    logger.warning("network_connector: publish failed → saved to outbox")
            else:
                enqueue_to_outbox(payload)
                logger.warning("network_connector: MQTT disconnected → saved to outbox")

            write_heartbeat("network_connector")
            time.sleep(5)

    except KeyboardInterrupt:
        logger.info("network_connector: received KeyboardInterrupt, stopping...")
    except Exception:
        logger.exception("network_connector: crashed with an unexpected error")
    finally:
        client.disconnect()
        logger.info("network_connector: exited cleanly")

if __name__ == "__main__":
    main()
