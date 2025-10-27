import os
import json
import time
import ssl
import threading
import sys
import logging
import math
from pathlib import Path
from typing import Optional, Dict, Any
import systemd.daemon
import paho.mqtt.client as mqtt

# Add project root to path for imports (deployment flexible)
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from CogniCore import CogniCore, SystemState

# Configuration
SERVICE_NAME = "network_connector"
HEARTBEAT_INTERVAL = 5  # seconds
TELEMETRY_INTERVAL = 2  # seconds - send data every 2 seconds
RECONNECT_DELAY = 5  # seconds between reconnection attempts

# MQTT configuration - can be overridden by environment variables
DEFAULT_MQTT_BROKER = "cogniflight.exequtech.com"
DEFAULT_MQTT_PORT = 8883
DEFAULT_MQTT_USERNAME = "N420HH"
DEFAULT_MQTT_PASSWORD = "LHUdEPUxjcuDU3XQ0RO+hLsOjdCUafB/68XNKyCB42s="
DEFAULT_MQTT_TOPIC = "cogniflight/telemetry"
DEFAULT_MQTT_QOS = 1  # At least once delivery

def sanitize_for_json(obj: Any) -> Any:
    """
    Recursively sanitize data to ensure valid JSON serialization.
    Removes NaN, Infinity, and -Infinity values which are not valid in JSON.

    Args:
        obj: Any Python object (dict, list, or primitive)

    Returns:
        Sanitized object with invalid values set to None
    """
    if isinstance(obj, dict):
        return {key: sanitize_for_json(value) for key, value in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_for_json(item) for item in obj]
    elif isinstance(obj, float):
        # Check for NaN or Infinity
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    else:
        return obj

class NetworkConnector:
    """
    Network Connector Service for CogniFlight Edge

    Collects sensor data and predictions every 2 seconds and transmits to MQTT broker via TLS.
    Handles offline buffering and retry logic for reliable data transmission.
    """

    def __init__(self):
        # Initialize CogniCore
        self.core = CogniCore(SERVICE_NAME)
        self.logger = self.core.get_logger(SERVICE_NAME)

        # MQTT configuration
        self.mqtt_broker = os.getenv('MQTT_BROKER', DEFAULT_MQTT_BROKER)
        self.mqtt_port = int(os.getenv('MQTT_PORT', DEFAULT_MQTT_PORT))
        self.mqtt_username = os.getenv('MQTT_USERNAME', DEFAULT_MQTT_USERNAME)
        self.mqtt_password = os.getenv('MQTT_PASSWORD', DEFAULT_MQTT_PASSWORD)
        self.mqtt_topic = os.getenv('MQTT_TOPIC', DEFAULT_MQTT_TOPIC)
        self.mqtt_qos = int(os.getenv('MQTT_QOS', DEFAULT_MQTT_QOS))

        # Service state
        self.running = False
        self.last_heartbeat = 0
        self.connection_status = "disconnected"
        self.failed_transmissions = 0
        self.successful_transmissions = 0
        self.mqtt_connected = False

        # Offline buffer for failed transmissions
        self.offline_buffer = []
        self.max_buffer_size = 1000

        # Threading
        self.telemetry_thread = None
        self.mqtt_client = None

        # Setup MQTT client
        self.setup_mqtt_client()

    def setup_mqtt_client(self):
        """Setup MQTT client with TLS and authentication"""
        try:
            # Create MQTT client using edge_username for unique identification
            client_id = f"{self.mqtt_username}_{int(time.time())}"
            self.mqtt_client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311, callback_api_version=mqtt.CallbackAPIVersion.VERSION1)

            # Log credential configuration (mask password for security)
            self.logger.info(f"MQTT credentials - Username: '{self.mqtt_username}', Password length: {len(self.mqtt_password) if self.mqtt_password else 0} chars")
            self.logger.debug(f"Client ID: {client_id}")

            # Set username and password
            if self.mqtt_username and self.mqtt_password:
                self.mqtt_client.username_pw_set(self.mqtt_username, self.mqtt_password)
                self.logger.info("MQTT username and password configured")
            else:
                self.logger.warning("MQTT credentials not properly set!")

            # Configure TLS
            self.mqtt_client.tls_set(
                cert_reqs=ssl.CERT_REQUIRED,
                tls_version=ssl.PROTOCOL_TLS,
                ciphers=None
            )

            # Set callbacks
            self.mqtt_client.on_connect = self.on_mqtt_connect
            self.mqtt_client.on_disconnect = self.on_mqtt_disconnect
            self.mqtt_client.on_publish = self.on_mqtt_publish

            # Enable logging for debugging
            self.mqtt_client.enable_logger(self.logger)

            self.logger.info("MQTT client configured for TLS connection")

        except Exception as e:
            self.logger.error(f"Failed to setup MQTT client: {e}")

    def on_mqtt_connect(self, client, userdata, flags, rc):
        """Callback for when MQTT client connects"""
        self.logger.info(f"MQTT on_connect callback - rc={rc}, flags={flags}")

        if rc == 0:
            self.mqtt_connected = True
            self.connection_status = "connected"
            self.logger.info(f"Successfully connected to MQTT broker at {self.mqtt_broker}:{self.mqtt_port}")

            # Try to send buffered messages
            if self.offline_buffer:
                self.retry_buffered_transmissions()
        else:
            self.mqtt_connected = False
            self.connection_status = f"connection_failed_rc{rc}"
            error_messages = {
                1: "incorrect protocol version",
                2: "invalid client identifier",
                3: "server unavailable",
                4: "bad username or password",
                5: "not authorized"
            }
            error_msg = error_messages.get(rc, f"unknown error code {rc}")
            self.logger.error(f"MQTT connection failed (rc={rc}): {error_msg}")
            self.logger.error(f"Using username: '{self.mqtt_username}', broker: {self.mqtt_broker}:{self.mqtt_port}")

    def on_mqtt_disconnect(self, client, userdata, rc):
        """Callback for when MQTT client disconnects"""
        self.mqtt_connected = False
        self.connection_status = "disconnected"

        if rc != 0:
            self.logger.warning(f"Unexpected MQTT disconnection (rc={rc}). Will attempt to reconnect.")

    def on_mqtt_publish(self, client, userdata, mid):
        """Callback for when a message is successfully published"""
        self.logger.debug(f"MQTT message {mid} published successfully")

    def is_data_fresh(self, data: Optional[Dict[str, Any]], current_time: float, max_age_seconds: float = 2.0) -> bool:
        """
        Check if continuous sensor data is fresh (not older than max_age_seconds)

        Args:
            data: Data dictionary with timestamp field
            current_time: Current Unix timestamp
            max_age_seconds: Maximum age in seconds (default: 2.0)

        Returns:
            True if data is fresh, False otherwise
        """
        if not data:
            return False

        data_timestamp = data.get("timestamp")
        if not data_timestamp:
            return False

        age = current_time - data_timestamp
        return age <= max_age_seconds

    def collect_telemetry_snapshot(self) -> Dict[str, Any]:
        """
        Collect comprehensive telemetry snapshot from all sensors and services
        Only includes continuous sensor data that is fresh (within 2 seconds)
        System state and pilot data are always included as they represent current state

        Returns:
            Dictionary containing all current sensor and prediction data
        """
        try:
            timestamp = time.time()

            # Read latest data directly from Redis
            vision_data = self.core.get_data("vision")
            hr_data = self.core.get_data("hr_sensor")
            fusion_data = self.core.get_data("fusion")
            env_data = self.core.get_data("env_sensor")
            imu_data = self.core.get_data("imu_sensor")
            alcohol_data = self.core.get_data("alcohol_detected")
            system_state_data = self.core.get_data("system_state")

            # Build flattened telemetry payload for Telegraf compatibility
            telemetry = {
                "collection_time": timestamp,
                "predictor_version": "1.0.0"
            }

            # Add hardcoded ground-level altitude and pressure (for testing on ground)
            telemetry["altitude"] = 0.0  # Sea level / ground level in meters
            telemetry["pressure"] = 1013.25  # Standard atmospheric pressure at sea level (hPa)

            # Flatten environmental data (only if fresh)
            if self.is_data_fresh(env_data, timestamp):
                telemetry["temperature"] = env_data.get("temp")
                telemetry["humidity"] = env_data.get("humidity")

            # Flatten IMU sensor data (only if fresh)
            if self.is_data_fresh(imu_data, timestamp):
                telemetry["accel_x"] = imu_data.get("accel_x")
                telemetry["accel_y"] = imu_data.get("accel_y")
                telemetry["accel_z"] = imu_data.get("accel_z")
                telemetry["gyro_x"] = imu_data.get("gyro_x")
                telemetry["gyro_y"] = imu_data.get("gyro_y")
                telemetry["gyro_z"] = imu_data.get("gyro_z")
                telemetry["mag_x"] = imu_data.get("mag_x")
                telemetry["mag_y"] = imu_data.get("mag_y")
                telemetry["mag_z"] = imu_data.get("mag_z")
                telemetry["roll"] = imu_data.get("roll")
                telemetry["pitch"] = imu_data.get("pitch")
                telemetry["yaw"] = imu_data.get("yaw")

            # Flatten alcohol detection data (only if fresh)
            if self.is_data_fresh(alcohol_data, timestamp):
                telemetry["alcohol_detected"] = alcohol_data.get("detected")

            # Flatten biometric data (only if fresh)
            if self.is_data_fresh(hr_data, timestamp):
                telemetry["heart_rate"] = hr_data.get("hr")
                telemetry["rr_interval"] = hr_data.get("rr_interval")
                telemetry["baseline_deviation"] = hr_data.get("baseline_deviation")
                telemetry["rmssd"] = hr_data.get("rmssd")
                telemetry["hr_trend"] = hr_data.get("hr_trend")
                telemetry["stress_index"] = hr_data.get("stress_index")

            # Flatten vision data (only if fresh)
            if self.is_data_fresh(vision_data, timestamp):
                telemetry["avg_ear"] = vision_data.get("avg_ear")
                telemetry["mar"] = vision_data.get("mar")
                telemetry["eyes_closed"] = vision_data.get("eyes_closed")
                telemetry["closure_duration"] = vision_data.get("closure_duration")
                # Ensure microsleep_count is an integer
                microsleep_count = vision_data.get("microsleep_count")
                if microsleep_count is not None:
                    telemetry["microsleep_count"] = int(microsleep_count)
                telemetry["blink_rate"] = vision_data.get("blink_rate_per_minute")
                telemetry["yawning"] = vision_data.get("yawning")
                # Ensure yawn_count is an integer
                yawn_count = vision_data.get("yawn_count")
                if yawn_count is not None:
                    telemetry["yawn_count"] = int(yawn_count)
                telemetry["yawn_duration"] = vision_data.get("yawn_duration")

            # Flatten fusion/prediction data (only if fresh)
            if self.is_data_fresh(fusion_data, timestamp):
                telemetry["fusion_score"] = fusion_data.get("fusion_score")
                telemetry["confidence"] = fusion_data.get("confidence")
                telemetry["is_critical_event"] = fusion_data.get("is_critical_event")

            # Add system state (always include - represents current state, not continuous measurement)
            if system_state_data:
                telemetry["system_state"] = system_state_data.get("state")
                telemetry["state_message"] = system_state_data.get("message")

            # Add pilot info (always include - represents current state, not continuous measurement)
            # Try to get authenticated pilot from any known pilots
            pilot_data = None
            pilots = self.core.list_pilots()
            for pilot_username in pilots:
                candidate = self.core.get_data(f"pilot:{pilot_username}")
                if candidate and candidate.get('authenticated'):
                    pilot_data = candidate
                    break

            if pilot_data:
                telemetry["pilot_username"] = pilot_data.get("pilot_username")
                # Always include flight_id (even if empty string)
                telemetry["flight_id"] = pilot_data.get("flight_id", "")

            return telemetry

        except Exception as e:
            self.logger.error(f"Error collecting telemetry snapshot: {e}")
            return None

    def transmit_data(self, data: Dict[str, Any]) -> bool:
        """
        Transmit telemetry data to MQTT broker

        Args:
            data: Telemetry data to transmit

        Returns:
            True if transmission successful, False otherwise
        """
        if not data:
            return False

        if not self.mqtt_connected:
            self.logger.debug("MQTT not connected, buffering message")
            return False

        try:
            # Sanitize data to remove NaN and Infinity values (invalid in JSON)
            sanitized_data = sanitize_for_json(data)

            # Convert data to JSON
            payload = json.dumps(sanitized_data)

            # Build topic with edge username (MQTT username is the edge identifier)
            # Format: cogniflight/telemetry/{edge_username}
            topic_with_edge = f"{self.mqtt_topic}/{self.mqtt_username}"

            # Publish to MQTT topic
            result = self.mqtt_client.publish(
                topic_with_edge,
                payload,
                qos=self.mqtt_qos,
                retain=False
            )

            # Check if publish was successful
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                self.successful_transmissions += 1

                # Log successful transmission (occasionally to avoid spam)
                if self.successful_transmissions % 30 == 0:  # Every minute at 2s intervals
                    self.logger.info(f"Telemetry transmitted to {topic_with_edge} (total: {self.successful_transmissions})")
                    # Debug: Log actual payload content
                    payload_preview = payload[:500] + "..." if len(payload) > 500 else payload
                    self.logger.info(f"Sample payload: {payload_preview}")

                return True
            else:
                self.logger.warning(f"MQTT publish failed with rc={result.rc}")
                return False

        except Exception as e:
            self.logger.error(f"Transmission failed: {e}")
            return False

    def buffer_failed_transmission(self, data: Dict[str, Any]):
        """Buffer failed transmission for later retry"""
        if len(self.offline_buffer) < self.max_buffer_size:
            self.offline_buffer.append(data)
            self.logger.debug(f"Buffered failed transmission (buffer size: {len(self.offline_buffer)})")
        else:
            # Remove oldest entry to make room
            self.offline_buffer.pop(0)
            self.offline_buffer.append(data)
            self.logger.warning("Buffer full - removed oldest entry")

    def retry_buffered_transmissions(self):
        """Attempt to retransmit buffered data"""
        if not self.offline_buffer:
            return

        self.logger.info(f"Attempting to retransmit {len(self.offline_buffer)} buffered messages")

        successful_retries = 0
        failed_retries = []

        for data in self.offline_buffer:
            if self.transmit_data(data):
                successful_retries += 1
            else:
                failed_retries.append(data)

        # Update buffer with still-failed transmissions
        self.offline_buffer = failed_retries

        if successful_retries > 0:
            self.logger.info(f"Successfully retransmitted {successful_retries} buffered messages")

        if self.offline_buffer:
            self.logger.warning(f"{len(self.offline_buffer)} messages still in retry buffer")

    def telemetry_loop(self):
        """Main telemetry transmission loop - runs every 2 seconds"""
        self.logger.info("Telemetry loop started - sending data every 2 seconds")

        retry_counter = 0

        while self.running:
            try:
                # Collect current telemetry snapshot
                telemetry_data = self.collect_telemetry_snapshot()

                if telemetry_data:
                    # Attempt transmission
                    if self.transmit_data(telemetry_data):
                        # Successful transmission

                        # Every 5th successful transmission, try to clear buffer
                        if self.successful_transmissions % 5 == 0 and self.offline_buffer:
                            self.retry_buffered_transmissions()

                    else:
                        # Failed transmission - buffer for retry
                        self.buffer_failed_transmission(telemetry_data)

                # Every 30 seconds (15 iterations), attempt buffer retry regardless
                retry_counter += 1
                if retry_counter >= 15:
                    if self.offline_buffer and self.mqtt_connected:
                        self.retry_buffered_transmissions()
                    retry_counter = 0

                # Wait for next telemetry interval
                time.sleep(TELEMETRY_INTERVAL)

            except Exception as e:
                self.logger.error(f"Error in telemetry loop: {e}")
                time.sleep(TELEMETRY_INTERVAL)

    def mqtt_connection_loop(self):
        """Maintain MQTT connection with automatic reconnection"""
        while self.running:
            try:
                if not self.mqtt_connected:
                    self.logger.info(f"Attempting MQTT connection to {self.mqtt_broker}:{self.mqtt_port} with username '{self.mqtt_username}'")
                    self.logger.debug(f"TLS enabled, keepalive=60s")
                    self.mqtt_client.connect(self.mqtt_broker, self.mqtt_port, keepalive=60)
                    self.mqtt_client.loop_start()

                time.sleep(RECONNECT_DELAY)

            except Exception as e:
                self.logger.error(f"MQTT connection error: {e}")
                self.logger.exception("Full exception details:")
                self.connection_status = "connection_error"
                time.sleep(RECONNECT_DELAY)

    def run(self):
        """Main network connector service loop"""
        self.logger.info("Network Connector service starting...")

        # Validate configuration
        if not self.mqtt_broker:
            self.logger.error("No MQTT broker configured")
            return

        self.logger.info(f"MQTT broker: {self.mqtt_broker}:{self.mqtt_port}")
        self.logger.info(f"MQTT base topic: {self.mqtt_topic}")
        self.logger.info(f"MQTT full topic: {self.mqtt_topic}/{self.mqtt_username}")
        self.logger.info(f"Edge username (unique ID): {self.mqtt_username}")
        self.logger.info(f"Transmission interval: {TELEMETRY_INTERVAL} seconds")

        # Notify systemd that service is ready
        systemd.daemon.notify('READY=1')
        self.logger.info("Notified systemd that service is ready")

        # Start MQTT connection thread
        self.running = True
        mqtt_thread = threading.Thread(target=self.mqtt_connection_loop, daemon=True)
        mqtt_thread.start()

        # Start telemetry transmission thread
        self.telemetry_thread = threading.Thread(target=self.telemetry_loop, daemon=True)
        self.telemetry_thread.start()

        # Main service loop - health monitoring and watchdog
        while True:
            try:
                current_time = time.time()

                # Send systemd watchdog notification
                if current_time - self.last_heartbeat >= HEARTBEAT_INTERVAL:
                    systemd.daemon.notify('WATCHDOG=1')
                    self.last_heartbeat = current_time

                    # Log service health status periodically
                    if self.successful_transmissions % 30 == 0 and self.successful_transmissions > 0:
                        self.logger.info(f"Service health: {self.successful_transmissions} successful, "
                                       f"{self.failed_transmissions} failed, "
                                       f"{len(self.offline_buffer)} buffered, "
                                       f"status: {self.connection_status}, "
                                       f"mqtt_connected: {self.mqtt_connected}")

                # Check if telemetry thread is still alive
                if self.telemetry_thread and not self.telemetry_thread.is_alive():
                    self.logger.error("Telemetry thread died - restarting")
                    self.telemetry_thread = threading.Thread(target=self.telemetry_loop, daemon=True)
                    self.telemetry_thread.start()

                time.sleep(1)  # Main loop sleep

            except KeyboardInterrupt:
                self.logger.info("Network Connector service stopping...")
                break
            except Exception as e:
                self.logger.exception(f"Network Connector error: {e}")
                time.sleep(5)  # Wait before retry

        # Cleanup
        self.running = False

        # Disconnect MQTT client
        if self.mqtt_client:
            self.mqtt_client.loop_stop()
            self.mqtt_client.disconnect()

        if self.telemetry_thread:
            self.telemetry_thread.join(timeout=5)

def main():
    """Main network connector entry point"""
    connector = NetworkConnector()
    connector.run()

if __name__ == "__main__":
    main()
