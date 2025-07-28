import time
import sys
import logging
import asyncio
from pathlib import Path

# Add project root to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from bleak import BleakClient
from CogniCore import CogniCore
from CogniCore import config

# Configuration
HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"  # Heart Rate Measurement
HR_SENSOR_MAC = config.DEFAULT_HR_SENSOR_MAC
RETRY_DELAY = 5  # seconds
HEARTBEAT_INTERVAL = 10  # seconds
SERVICE_NAME = "hr_monitor"

def parse_hr_data(data: bytearray) -> int:
    """Parse heart rate data from BLE heart rate measurement."""
    try:
        # Heart Rate Measurement format (standard)
        flags = data[0]
        if flags & 0x01:  # 16-bit HR value
            hr = int.from_bytes(data[1:3], byteorder='little')
        else:  # 8-bit HR value
            hr = int(data[1])
        return max(0, min(255, hr))  # Clamp to reasonable range
    except (IndexError, ValueError) as e:
        return 0

def create_notification_handler(core, logger):
    """Create notification handler with core and logger access."""
    def notification_handler(sender, data):
        """Handle heart rate notifications from BLE device."""
        try:
            hr = parse_hr_data(data)
            if hr > 0:
                hr_data = {
                    "hr": hr,
                    "t_hr": time.time()
                }
                
                try:
                    # Publish HR data to CogniCore - always available for other services
                    core.publish_data("hr_sensor", hr_data)
                    logger.info(f"HR: {hr} BPM")
                    logger.debug(f"Published HR data: {hr_data}")
                except Exception as e:
                    logger.error(f"Failed to publish HR data: {e}")
            else:
                logger.warning("Invalid heart rate data received")
        except Exception as e:
            logger.error(f"Error handling HR notification: {e}")
    
    return notification_handler

async def connect_and_monitor():
    """Connect to HR sensor and monitor continuously."""
    core = CogniCore(SERVICE_NAME)
    logger = core.get_logger(SERVICE_NAME)
    logger.info("HR Monitor service started")
    
    notification_handler = create_notification_handler(core, logger)
    last_heartbeat = 0
    
    while True:
        try:
            logger.info(f"Attempting to connect to HR sensor: {HR_SENSOR_MAC}")
            
            async with BleakClient(HR_SENSOR_MAC) as client:
                logger.info("Connected to HR sensor")
                
                # Start heart rate notifications
                await client.start_notify(HR_UUID, notification_handler)
                logger.info("Started heart rate notifications")
                
                # Stay connected and handle notifications
                while client.is_connected:
                    current_time = time.time()
                    
                    # Write heartbeat periodically
                    if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                        try:
                            core.write_heartbeat()
                            logger.debug("Heartbeat written")
                        except Exception as e:
                            logger.error(f"Failed to write heartbeat: {e}")
                        last_heartbeat = current_time
                    
                    await asyncio.sleep(1)
                    
        except Exception as e:
            logger.warning(f"HR sensor connection failed: {e}. Retrying in {RETRY_DELAY}s")
            await asyncio.sleep(RETRY_DELAY)

def main():
    """Main HR Monitor service entry point."""
    try:
        # Run the HR monitor
        asyncio.run(connect_and_monitor())
        
    except KeyboardInterrupt:
        print("HR Monitor service stopping...")
    except Exception as e:
        print(f"HR Monitor service crashed: {e}")

if __name__ == "__main__":
    main()