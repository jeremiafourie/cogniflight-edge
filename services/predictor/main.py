import time
from collections import deque

from common.queues import predict_queue, stage_change_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("predictor")

# Size of the sliding window (N = 3 samples)
WINDOW_SIZE = 3

# These threshold values should be computed per‐pilot (e.g., resting HR + Δ1, Δ2, Δ3)
# For now, we define placeholders. In your real code, read them from SQLite.
THRESHOLD_MILD   = 0.5
THRESHOLD_MOD    = 0.7
THRESHOLD_SEVERE = 0.9
HYSTERESIS       = 0.05  # small gap to prevent flapping

def main():
    # A deque that holds the last WINDOW_SIZE fusion_scores
    buffer = deque(maxlen=WINDOW_SIZE)
    last_stage = "active"  # default initial stage

    try:
        while True:
            try:
                # Try to get the newest fusion‐score packet (non‐blocking)
                pkt = predict_queue.get(timeout=1)
            except Exception:
                # No new packet available this second—still write heartbeat and continue
                write_heartbeat("predictor")
                continue

            fusion_score = pkt["fusion_score"]
            buffer.append(fusion_score)

            # Only evaluate stage changes once we have WINDOW_SIZE samples
            if len(buffer) == WINDOW_SIZE:
                # Check for a “stable” transition into MILD
                if all(s >= THRESHOLD_MILD for s in buffer) and last_stage == "active":
                    last_stage = "mild"
                    event = {"stage": "mild", "timestamp": time.time()}
                    stage_change_queue.put(event)
                    logger.info("predictor → Stage changed to MILD")

                # Check for transition into MODERATE
                elif all(s >= THRESHOLD_MOD for s in buffer) and last_stage in ["active", "mild"]:
                    last_stage = "moderate"
                    event = {"stage": "moderate", "timestamp": time.time()}
                    stage_change_queue.put(event)
                    logger.info("predictor → Stage changed to MODERATE")

                # Check for transition into SEVERE
                elif all(s >= THRESHOLD_SEVERE for s in buffer) and last_stage in ["active", "mild", "moderate"]:
                    last_stage = "severe"
                    event = {"stage": "severe", "timestamp": time.time()}
                    stage_change_queue.put(event)
                    logger.info("predictor → Stage changed to SEVERE")

                # Check for dropping back to ACTIVE (use hysteresis)
                elif fusion_score < THRESHOLD_MILD - HYSTERESIS and last_stage != "active":
                    last_stage = "active"
                    event = {"stage": "active", "timestamp": time.time()}
                    stage_change_queue.put(event)
                    logger.info("predictor → Stage changed to ACTIVE")

            # Write heartbeat for this service
            write_heartbeat("predictor")

    except KeyboardInterrupt:
        logger.info("predictor stopping (KeyboardInterrupt)")
    except Exception:
        logger.exception("predictor crashed with an unexpected error")
    finally:
        logger.info("predictor has exited")

if __name__ == "__main__":
    main()