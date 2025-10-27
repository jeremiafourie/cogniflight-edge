"""
Unified Camera Manager
Handles camera capture without race conditions - never releases until shutdown
"""
import time
import cv2
import numpy as np
import subprocess
import threading
import logging
from typing import Optional, Tuple


class CameraManager:
    """
    Single camera manager that owns the camera for the entire service lifetime.
    No handover, no race conditions.
    """

    def __init__(self, logger: logging.Logger, width: int = 640, height: int = 360, fps: int = 30):
        self.logger = logger
        self.width = width
        self.height = height
        self.fps = fps
        self.process = None
        self.running = False
        self.frame_data = None
        self.frame_lock = threading.Lock()
        self.frames_read = 0
        self.last_frame_time = time.time()
        self.read_thread = None

    def start(self) -> bool:
        """Start camera capture process - called once at service startup"""
        try:
            cmd = [
                'rpicam-vid',
                '--codec', 'yuv420',
                '--width', str(self.width),
                '--height', str(self.height),
                '--framerate', str(self.fps),
                '--timeout', '0',
                '--output', '-',
                '--nopreview',
                '--flush'
            ]

            self.logger.info(f"Starting camera: {self.width}x{self.height} at {self.fps}fps")

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=self.width * self.height * 3  # Larger buffer for better performance
            )

            self.running = True
            self.read_thread = threading.Thread(target=self._read_frames, daemon=True)
            self.read_thread.start()

            # Wait for camera to stabilize
            time.sleep(2)

            # Verify we're getting frames
            for _ in range(10):
                ret, frame = self.read()
                if ret and frame is not None:
                    self.logger.info("Camera started successfully and receiving frames")
                    return True
                time.sleep(0.1)

            self.logger.error("Camera started but no frames received")
            return False

        except Exception as e:
            self.logger.error(f"Camera start failed: {e}")
            return False

    def _read_frames(self):
        """Background thread to continuously read frames from camera"""
        frame_size = self.width * self.height * 3 // 2
        buffer = b''
        max_buffer_size = frame_size * 10  # Limit buffer to prevent memory buildup

        while self.running and self.process and self.process.poll() is None:
            try:
                chunk = self.process.stdout.read(8192)  # Larger chunks for better performance
                if not chunk:
                    time.sleep(0.01)
                    continue

                buffer += chunk

                # Prevent excessive buffer growth
                if len(buffer) > max_buffer_size:
                    buffer = buffer[-max_buffer_size:]
                    self.logger.debug("Camera buffer trimmed to prevent memory buildup")

                while len(buffer) >= frame_size:
                    frame_data = buffer[:frame_size]
                    buffer = buffer[frame_size:]

                    try:
                        yuv_array = np.frombuffer(frame_data, dtype=np.uint8)
                        yuv_frame = yuv_array.reshape((self.height * 3 // 2, self.width))
                        bgr_frame = cv2.cvtColor(yuv_frame, cv2.COLOR_YUV2BGR_I420)

                        with self.frame_lock:
                            self.frame_data = bgr_frame.copy()
                            self.frames_read += 1
                            self.last_frame_time = time.time()

                    except Exception as e:
                        continue

            except Exception as e:
                if self.running:
                    time.sleep(0.01)

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read current frame - non-blocking"""
        with self.frame_lock:
            if self.frame_data is not None:
                return True, self.frame_data.copy()
            else:
                return False, None

    def get_frame_count(self) -> int:
        """Get total frames read"""
        return self.frames_read

    def is_healthy(self) -> bool:
        """Check if camera is receiving frames regularly"""
        current_time = time.time()
        # Consider unhealthy if no frames received in last 5 seconds
        return current_time - self.last_frame_time < 5.0

    def restart(self) -> bool:
        """Restart camera if it becomes unhealthy"""
        self.logger.info("Restarting camera...")

        # Stop current camera
        self.stop()

        # Wait for resources to be freed
        time.sleep(2)

        # Start camera again
        return self.start()

    def stop(self):
        """Stop camera - only called at service shutdown"""
        self.running = False

        # Wait for read thread to finish
        if self.read_thread and self.read_thread.is_alive():
            self.read_thread.join(timeout=2)

        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

        self.logger.info("Camera stopped")