import time
import common.config as cfg
from common.queues import hr_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

import asyncio
from bleak import BleakClient

logger = configure_logging("ble")

# BLE HR UUID:
HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"

BLE_DEVICE_ADDRESS = "AA:BB:CC:DD:EE:FF"  # replace with your sensor

async def run_ble_loop():
    while True:
        try:
            async with BleakClient(BLE_DEVICE_ADDRESS) as client:
                logger.info("Connected to BLE device.")
                await client.start_notify(
                    HR_UUID, notification_handler
                )

                # Stay connected; notifications will call handler
                while True:
                    await asyncio.sleep(1)

        except Exception as e:
            logger.warning(f"BLE connection failed: {e}. Retrying in 5s.")
            await asyncio.sleep(5)

def notification_handler(sender, data):
    """
    Parse heart-rate data from `data` (bytearray).
    This example assumes standard HRM format.
    """
    hr = int(data[1])  # simple parse; adapt if needed
    timestamp = time.time()
    packet = {"hr": hr, "t_hr": timestamp}
    try:
        hr_queue.put_nowait(packet)
    except Exception:
        # drop oldest if queue full
        try:
            hr_queue.get_nowait()
            hr_queue.put_nowait(packet)
            logger.warning("ble: hr_queue overflow – oldest sample dropped.")
        except Exception:
            pass

def main():
    try:
        loop = asyncio.get_event_loop()
        while True:
            write_heartbeat("ble")
            loop.run_until_complete(run_ble_loop())
            # If the BLE loop ever exits, wait 2s then retry:
            time.sleep(2)
    except KeyboardInterrupt:
        logger.info("ble stopping...")
    except Exception:
        logger.exception("ble crashed:")

if __name__ == "__main__":
    main()
