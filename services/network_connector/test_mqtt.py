#!/usr/bin/env python3
"""Quick MQTT connection test"""

import ssl
import time
import paho.mqtt.client as mqtt

BROKER = "cogniflight.exequtech.com"
PORT = 8883
USERNAME = "EdgeSimulator-1"
PASSWORD = "EdgeSimulator-1"

connected = False

def on_connect(client, userdata, flags, reason_code, properties):
    global connected
    rc = reason_code.value if hasattr(reason_code, 'value') else reason_code
    print(f"on_connect called: rc={rc}")
    if rc == 0:
        connected = True
        print("Connected successfully!")
    else:
        print(f"Connection failed: {rc}")

def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    rc = reason_code.value if hasattr(reason_code, 'value') else reason_code
    print(f"Disconnected: rc={rc}")

def on_log(client, userdata, level, buf):
    print(f"LOG [{level}]: {buf}")

print("Creating MQTT client...")
client = mqtt.Client(
    client_id=f"test_{int(time.time())}",
    protocol=mqtt.MQTTv311,
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2
)

client.on_connect = on_connect
client.on_disconnect = on_disconnect
client.on_log = on_log

print(f"Setting credentials: {USERNAME}")
client.username_pw_set(USERNAME, PASSWORD)

print("Configuring TLS...")
client.tls_set(
    cert_reqs=ssl.CERT_REQUIRED,
    tls_version=ssl.PROTOCOL_TLS,
    ciphers=None
)

print(f"Connecting to {BROKER}:{PORT}...")
try:
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()

    # Wait for connection
    timeout = 15
    start = time.time()
    while not connected and (time.time() - start) < timeout:
        time.sleep(0.5)

    if connected:
        print("\n✓ Successfully connected!")
        client.disconnect()
    else:
        print("\n✗ Connection timeout")

    client.loop_stop()

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
