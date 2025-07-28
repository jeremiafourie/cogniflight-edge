import time
import sys
import logging
from pathlib import Path
import board
import adafruit_dht

# Add project root to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from CogniCore import CogniCore

# Configuration
DHT_PIN = 4  # BCM pin (board.D4)
POLL_INTERVAL = 2.0  # 2 seconds as requested
SERVICE_NAME = "env_monitor"

# Initialize DHT22 sensor
try:
    dht_device = adafruit_dht.DHT22(board.D4, use_pulseio=False)
except Exception as e:
    print(f"Failed to initialize DHT22: {e}")
    sys.exit(1)

def read_sensor_data(logger):
    """Read temperature and humidity from DHT sensor."""
    try:
        humidity = dht_device.humidity
        temperature = dht_device.temperature
        
        if humidity is not None and temperature is not None:
            return {
                "temp": round(temperature, 1),
                "humidity": round(humidity, 1),
                "t_sensor": time.time()
            }
        return None
    except RuntimeError as error:
        # DHT sensor timeout or checksum error - these are normal occasionally
        logger.debug(f"DHT sensor read error (will retry): {error.args[0]}")
        return None
    except Exception as e:
        logger.error(f"Unexpected sensor read error: {e}")
        return None

def main():
    """Main environmental monitoring service loop."""
    # Initialize CogniCore first to enable logging
    try:
        core = CogniCore(SERVICE_NAME)
        logger = core.get_logger(SERVICE_NAME)
        logger.info("Environmental monitoring service started")
    except Exception as e:
        print(f"Failed to connect to CogniCore: {e}")
        return
    
    try:
        while True:
            # Read sensor data
            sensor_data = read_sensor_data(logger)
            
            if sensor_data:
                try:
                    # Publish sensor data to CogniCore
                    core.publish_data("env_sensor", sensor_data)
                    logger.info(f"DHT22 reading: {sensor_data['temp']}°C, {sensor_data['humidity']}%")
                    logger.debug(f"Published sensor data: {sensor_data}")
                except Exception as e:
                    logger.error(f"Failed to publish sensor data: {e}")
            else:
                logger.warning("Failed to read DHT22 sensor")

            # Write heartbeat
            try:
                core.write_heartbeat()
                logger.debug("Heartbeat written")
            except Exception as e:
                logger.warning(f"Heartbeat write failed: {e}")
                
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Environmental monitoring service stopping...")
        logger.info("Service stopped by user interrupt")
    except Exception as e:
        logger.critical(f"Environmental monitoring service crashed: {e}")
        logger.critical(f"Service crashed: {e}")
    finally:
        core.shutdown()
        logger.info("Environmental monitoring service exited")

if __name__ == "__main__":
    main()