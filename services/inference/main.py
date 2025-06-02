import time

from common.queues import preproc_to_inference_queue, hr_queue, predict_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("inference")

MAX_FRAME_AGE = 0.1  # seconds (100 ms)

def get_latest_hr():
    """
    Non‐blocking peek at hr_queue. Returns the most recent HR packet or None.
    """
    latest = None
    while True:
        try:
            latest = hr_queue.get_nowait()
        except Exception:
            break
    return latest

def main():
    try:
        while True:
            try:
                data = preproc_to_inference_queue.get(timeout=1)
            except Exception:
                write_heartbeat("inference")
                continue

            t_capture = data["t_capture"]
            # Discard if frame is too old
            if time.time() - t_capture > MAX_FRAME_AGE:
                logger.warning("inference: stale data dropped.")
                write_heartbeat("inference")
                continue

            blink_score = data["blink_score"]
            yawn_score  = data["yawn_score"]

            # Get latest HR sample
            hr_packet = get_latest_hr()
            if hr_packet:
                hr_value = hr_packet["hr"]
                t_hr      = hr_packet["t_hr"]
            else:
                hr_value = 0.0
                t_hr      = 0.0

            # Simple fusion: normalize each component (assume HR max ~200)
            # Then average and clamp to [0,1].
            fusion_raw = blink_score + yawn_score + (hr_value / 200.0)
            fusion_score = min(max(fusion_raw / 3.0, 0.0), 1.0)

            output_packet = {
                "t_capture":    t_capture,
                "t_hr":         t_hr,
                "blink_score":  blink_score,
                "yawn_score":   yawn_score,
                "fusion_score": fusion_score,
                "timestamp":    time.time()
            }

            try:
                predict_queue.put_nowait(output_packet)
            except Exception:
                # On overflow, drop oldest then retry
                try:
                    predict_queue.get_nowait()
                    predict_queue.put_nowait(output_packet)
                    logger.warning("inference: predict_queue overflow – oldest dropped.")
                except Exception:
                    pass

            write_heartbeat("inference")

    except KeyboardInterrupt:
        logger.info("inference stopping...")
    except Exception:
        logger.exception("inference crashed:")

if __name__ == "__main__":
    main()
