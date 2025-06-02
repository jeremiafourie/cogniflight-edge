from multiprocessing import Queue

import common.config as cfg

# Create named queues for inter-process communication.
# We’ll import these same queue objects in each service.

camera_to_preproc_queue = Queue(maxsize=cfg.QUEUE_CAMERA_TO_PREPROC)
preproc_to_inference_queue = Queue(maxsize=cfg.QUEUE_PREPROC_TO_INF)
predict_queue = Queue(maxsize=cfg.QUEUE_PREDICTOR)
hr_queue = Queue(maxsize=cfg.QUEUE_HR)
sensor_queue = Queue(maxsize=cfg.QUEUE_SENSOR)
stage_change_queue = Queue(maxsize=10)  # for predictor → alert_manager
