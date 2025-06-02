import time
import cv2

from common.queues import camera_to_preproc_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("camera")

FRAME_WIDTH = 640
FRAME_HEIGHT = 360
FPS = 30
SLEEP_INTERVAL = 1.0 / FPS

def main():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    try:
        while True:
            t0 = time.time()
            ret, frame = cap.read()
            if not ret:
                logger.warning("camera: frame read failed.")
                time.sleep(0.1)
                continue

            # Timestamp
            t_capture = time.time()
            packet = {"frame": frame, "t_capture": t_capture}

            try:
                camera_to_preproc_queue.put_nowait(packet)
            except Exception:
                # If full, drop oldest:
                try:
                    camera_to_preproc_queue.get_nowait()
                    camera_to_preproc_queue.put_nowait(packet)
                    logger.warning("camera: queue overflow – oldest frame dropped.")
                except Exception:
                    pass

            write_heartbeat("camera")
            # Maintain ~30 FPS
            elapsed = time.time() - t0
            if elapsed < SLEEP_INTERVAL:
                time.sleep(SLEEP_INTERVAL - elapsed)

    except KeyboardInterrupt:
        logger.info("camera stopping...")
    except Exception:
        logger.exception("camera crashed:")
    finally:
        cap.release()

if __name__ == "__main__":
    main()
