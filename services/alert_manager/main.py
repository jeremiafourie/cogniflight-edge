import time
import RPi.GPIO as GPIO

from common.queues import stage_change_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("alert_manager")

# GPIO pins (BCM numbering):
LED_ACTIVE   = 17  # Green
LED_MILD     = 27  # Blue
LED_MOD      = 22  # Yellow
LED_SEVERE   = 23  # Red
BUZZER_PIN   = 24
VIBRATION_PIN = 25

# Duration to hold each actuation (in seconds)
ALERT_DURATION = 0.5

def setup_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    for pin in [LED_ACTIVE, LED_MILD, LED_MOD, LED_SEVERE, BUZZER_PIN, VIBRATION_PIN]:
        GPIO.setup(pin, GPIO.OUT)
        GPIO.output(pin, GPIO.LOW)

def clear_all_actuators():
    for pin in [LED_ACTIVE, LED_MILD, LED_MOD, LED_SEVERE, BUZZER_PIN, VIBRATION_PIN]:
        GPIO.output(pin, GPIO.LOW)

def handle_stage_event(evt: dict):
    """
    evt = { "stage": <"active"|"mild"|"moderate"|"severe">, "timestamp": <float> }
    """
    stage = evt.get("stage", "active")
    logger.info(f"alert_manager: handling stage_change → {stage}")
    clear_all_actuators()

    if stage == "active":
        GPIO.output(LED_ACTIVE, GPIO.HIGH)
        time.sleep(ALERT_DURATION)
        GPIO.output(LED_ACTIVE, GPIO.LOW)

    elif stage == "mild":
        GPIO.output(LED_MILD, GPIO.HIGH)
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        time.sleep(ALERT_DURATION)
        GPIO.output(LED_MILD, GPIO.LOW)
        GPIO.output(BUZZER_PIN, GPIO.LOW)

    elif stage == "moderate":
        GPIO.output(LED_MOD, GPIO.HIGH)
        GPIO.output(VIBRATION_PIN, GPIO.HIGH)
        time.sleep(ALERT_DURATION)
        GPIO.output(LED_MOD, GPIO.LOW)
        GPIO.output(VIBRATION_PIN, GPIO.LOW)

    elif stage == "severe":
        GPIO.output(LED_SEVERE, GPIO.HIGH)
        GPIO.output(BUZZER_PIN, GPIO.HIGH)
        GPIO.output(VIBRATION_PIN, GPIO.HIGH)
        time.sleep(ALERT_DURATION)
        GPIO.output(LED_SEVERE, GPIO.LOW)
        GPIO.output(BUZZER_PIN, GPIO.LOW)
        GPIO.output(VIBRATION_PIN, GPIO.LOW)

    else:
        logger.warning(f"alert_manager: unknown stage '{stage}'")

def main():
    setup_gpio()
    try:
        while True:
            try:
                # Wait up to 1 second for a stage_change event
                evt = stage_change_queue.get(timeout=1)
                handle_stage_event(evt)
            except Exception:
                # No event received this second, but still write heartbeat
                write_heartbeat("alert_manager")
                continue

            write_heartbeat("alert_manager")

    except KeyboardInterrupt:
        logger.info("alert_manager: received KeyboardInterrupt, stopping...")
    except Exception:
        logger.exception("alert_manager: crashed with an unexpected error")
    finally:
        clear_all_actuators()
        GPIO.cleanup()
        logger.info("alert_manager: exited cleanly")

if __name__ == "__main__":
    main()
