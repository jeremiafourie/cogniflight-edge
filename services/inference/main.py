import time
import tflite_runtime.interpreter as tflite
import numpy as np

from common.queues import preproc_to_inference_queue, hr_queue, preproc_to_inference_queue, predict_queue
from common.heartbeat import write_heartbeat
from common.utils import configure_logging

logger = configure_logging("inference")

BLINK_MODEL_PATH = "/opt/models/blink.tflite"
YAWN_MODEL_PATH = "/opt/models/yawn.tflite"
FUSION_MODEL_PATH = "/opt/models/fusion.tflite"

# Time tolerance:
MAX_FRAME_AGE = 0.1  # seconds (100 ms)

# Helper: non-blocking peek at latest HR
def get_latest_hr():
    latest = None
    while True:
        try:
            latest = hr_queue.get_nowait()
        except Exception:
            break
    return latest

def load_interpreter(model_path):
    interpreter = tflite.Interpreter(model_path=model_path)
    interpreter.allocate_tensors()
    return interpreter

def run_tflite(interpreter, image):
    inp_details = interpreter.get_input_details()[0]["index"]
    out_details = interpreter.get_output_details()[0]["index"]
    interpreter.set_tensor(inp_details, image.astype(np.float32))
    interpreter.invoke()
    return interpreter.get_tensor(out_details).reshape(-1)

def main():
    # Load interpreters:
    blink_interp = load_interpreter(BLINK_MODEL_PATH)
    yawn_interp  = load_interpreter(YAWN_MODEL_PATH)
    fusion_interp = load_interpreter(FUSION_MODEL_PATH)

    try:
        while True:
            try:
                inf_input = preproc_to_inference_queue.get(timeout=1)
            except Exception:
                write_heartbeat("inference")
                continue

            t_capture = inf_input["t_capture"]
            if time.time() - t_capture > MAX_FRAME_AGE:
                logger.warning("inference: stale frame dropped.")
                write_heartbeat("inference")
                continue

            # Grab latest HR (non-blocking):
            hr_packet = get_latest_hr()
            hr_value = hr_packet["hr"] if hr_packet else 0
            t_hr = hr_packet["t_hr"] if hr_packet else 0

            eye_img = inf_input["eye"].reshape((1, 64, 64, 1)) / 255.0
            mouth_img = inf_input["mouth"].reshape((1, 128, 128, 1)) / 255.0

            blink_score = run_tflite(blink_interp, eye_img)[0]
            yawn_score  = run_tflite(yawn_interp, mouth_img)[0]

            # Prepare fusion input: [blink, yawn, hr]
            fusion_input = np.array([[[[blink_score, yawn_score, hr_value]]]])
            interpreter = fusion_interp
            inp_index = interpreter.get_input_details()[0]["index"]
            out_index = interpreter.get_output_details()[0]["index"]
            interpreter.set_tensor(inp_index, fusion_input.astype(np.float32))
            interpreter.invoke()
            fusion_score = interpreter.get_tensor(out_index).reshape(-1)[0]

            output_packet = {
                "t_capture": t_capture,
                "t_hr": t_hr,
                "blink_score": float(blink_score),
                "yawn_score": float(yawn_score),
                "fusion_score": float(fusion_score),
                "timestamp": time.time(),
            }

            try:
                predict_queue.put_nowait(output_packet)
            except Exception:
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
