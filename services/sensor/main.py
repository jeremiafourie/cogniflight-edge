import time
import Adafruit_DHT

from common.queues import sensor_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("sensor")

DHT_SENSOR = Adafruit_DHT.DHT22
DHT_PIN = 4  # BCM pin

POLL_INTERVAL = 1.0  # 1 Hz

def main():
    try:
        while True:
            humidity, temperature = Adafruit_DHT.read_retry(DHT_SENSOR, DHT_PIN)
            t_read = time.time()
            if humidity is not None and temperature is not None:
                packet = {"temp": temperature, "humidity": humidity, "t_sensor": t_read}
                try:
                    sensor_queue.put_nowait(packet)
                except Exception:
                    try:
                        sensor_queue.get_nowait()
                        sensor_queue.put_nowait(packet)
                        logger.warning("sensor: queue overflow – oldest sample dropped.")
                    except Exception:
                        pass
            else:
                logger.warning("sensor: failed to read DHT22.")

            write_heartbeat("sensor")
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("sensor stopping...")
    except Exception:
        logger.exception("sensor crashed:")

if __name__ == "__main__":
    main()
