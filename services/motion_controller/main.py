"""
CogniFlight Motion Controller Service

Controls pan/tilt servo bracket for camera tracking using the Seeed Studio PWM Driver Board (PCA9685).
Subscribes to vision processor face position data and adjusts servos to keep the pilot's face centered.

Hardware Configuration:
- PCA9685 PWM Driver on I2C Bus 1 (GPIO 2 SDA / GPIO 3 SCL)
- Default I2C Address: 0x40 (can be changed via board jumpers to 0x7F for Seeed board)
- Channel 0: Pan servo (horizontal movement) - SG90 servo
- Channel 1: Tilt servo (vertical movement) - SG90 servo
- Power: External 5V supply to V+ terminal on PCA9685 board

Service Features:
- Smooth servo movements with PID control
- Dead zone to prevent jitter
- Safety limits to prevent mechanical damage
- Auto-center on face loss
- State-aware operation (only tracks when pilot active)
"""

import time
import sys
import logging
from pathlib import Path
from typing import Dict, Any, Optional
import systemd.daemon
import board
import busio
from adafruit_servokit import ServoKit
from simple_pid import PID

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from CogniCore import CogniCore, SystemState

# Configuration
SERVICE_NAME = "motion_controller"
HEARTBEAT_INTERVAL = 5  # seconds

# PCA9685 Configuration
I2C_ADDRESS = 0x40  # Default address, change to 0x7F if using Seeed's default
NUM_CHANNELS = 16   # PCA9685 has 16 PWM channels

# Servo Configuration (SG90 servos)
PAN_CHANNEL = 0     # Channel 0 for horizontal movement
TILT_CHANNEL = 1    # Channel 1 for vertical movement
SERVO_MIN_ANGLE = 10   # Minimum safe angle
SERVO_MAX_ANGLE = 170  # Maximum safe angle
SERVO_CENTER = 90      # Center position

# Tracking Configuration
DEAD_ZONE = 0.03    # Ignore movements smaller than this (3% of frame) for stability
UPDATE_RATE = 0.05  # 50ms between updates (20Hz) for stable control
AUTO_CENTER_DELAY = 3.0  # Time before auto-centering when face is lost
CENTERING_TOLERANCE = 0.01  # Face is considered centered within 1% of frame
TRACKING_SMOOTHNESS = 0.15  # Smoothing factor for movement (0.0 = instant, 1.0 = no movement)

# Adaptive PID Controller Configuration
# Tuned for smooth, stable tracking with proper convergence
PID_KP = 20.0  # Proportional gain - moderate for stability
PID_KI = 2.0   # Integral gain - low to prevent windup
PID_KD = 5.0   # Derivative gain - higher to reduce overshoot
PID_OUTPUT_LIMIT = 15.0  # Maximum degrees to move per update - reduced for smoothness

# Adaptive speed control based on error magnitude
MAX_SPEED_THRESHOLD = 0.3   # Use max speed when error > 30% of frame
MIN_SPEED_THRESHOLD = 0.05  # Use min speed when error < 5% of frame
MAX_SPEED_MULTIPLIER = 2.0  # Speed multiplier for large errors
MIN_SPEED_MULTIPLIER = 0.3  # Speed multiplier for small errors


class MotionController:
    """Motion controller for pan/tilt servo tracking of pilot's face"""
    
    def __init__(self):
        # Initialize CogniCore
        self.core = CogniCore(SERVICE_NAME)
        self.logger = self.core.get_logger(SERVICE_NAME)
        self.logger.setLevel(logging.DEBUG)  # Enable debug logging
        
        # Servo kit and position tracking
        self.kit = None
        self.pan_position = SERVO_CENTER
        self.tilt_position = SERVO_CENTER
        self.target_pan = SERVO_CENTER  # Target position for smooth movement
        self.target_tilt = SERVO_CENTER  # Target position for smooth movement
        self.last_face_time = 0
        self.face_lost = False

        # Feedback control tracking
        self.last_offset_x = 0.0
        self.last_offset_y = 0.0
        self.error_history_x = []
        self.error_history_y = []
        self.convergence_check_count = 0
        self.is_converged = False
        
        # PID controllers for smooth tracking
        # Note: Setpoint is 0 (center of frame), input is offset (-1 to 1)
        # Output is servo angle adjustment
        self.pid_pan = PID(
            PID_KP, PID_KI, PID_KD,
            setpoint=0,
            output_limits=(-PID_OUTPUT_LIMIT, PID_OUTPUT_LIMIT),
            sample_time=UPDATE_RATE
        )
        
        self.pid_tilt = PID(
            PID_KP, PID_KI, PID_KD,
            setpoint=0,
            output_limits=(-PID_OUTPUT_LIMIT, PID_OUTPUT_LIMIT),
            sample_time=UPDATE_RATE
        )
        
        # Service state
        self.running = False
        self.tracking_enabled = False
        self.last_heartbeat = 0
        self.last_update_time = 0
        
        # Subscribe to vision data
        self.setup_subscriptions()
    
    def setup_subscriptions(self):
        """Setup CogniCore subscriptions for vision data and state changes"""
        try:
            # Subscribe to vision processor data
            self.core.subscribe_to_data("vision", self.handle_vision_data)
            self.logger.info("Subscribed to vision processor data")
            
            # Subscribe to system state changes
            self.core.subscribe_to_state_changes(self.handle_state_change)
            self.logger.info("Subscribed to system state changes")
            
        except Exception as e:
            self.logger.error(f"Failed to setup subscriptions: {e}")
    
    def initialize_servos(self) -> bool:
        """Initialize PCA9685 and servo kit"""
        try:
            # Create I2C bus interface
            i2c = busio.I2C(board.SCL, board.SDA)
            
            # Initialize ServoKit with PCA9685
            # Note: Some Seeed boards use address 0x7F by default
            try:
                self.kit = ServoKit(channels=NUM_CHANNELS, i2c=i2c, address=I2C_ADDRESS)
                self.logger.info(f"PCA9685 initialized at address 0x{I2C_ADDRESS:02X}")
            except Exception as e:
                # Try alternate address if default fails
                self.logger.warning(f"Failed with address 0x{I2C_ADDRESS:02X}, trying 0x7F (Seeed default)")
                self.kit = ServoKit(channels=NUM_CHANNELS, i2c=i2c, address=0x7F)
                self.logger.info("PCA9685 initialized at address 0x7F")
            
            # Configure servo channels for SG90 servos
            # SG90 typically uses 500-2400 microsecond pulse width
            self.kit.servo[PAN_CHANNEL].set_pulse_width_range(500, 2400)
            self.kit.servo[TILT_CHANNEL].set_pulse_width_range(500, 2400)
            
            # Set actuation range
            self.kit.servo[PAN_CHANNEL].actuation_range = 180
            self.kit.servo[TILT_CHANNEL].actuation_range = 180
            
            # Move to center position
            self.center_servos()
            
            self.logger.info("Servos initialized and centered")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize servos: {e}")
            return False
    
    def center_servos(self):
        """Move servos to center position and reset tracking state"""
        try:
            self.move_servo_direct(PAN_CHANNEL, SERVO_CENTER)
            self.move_servo_direct(TILT_CHANNEL, SERVO_CENTER)
            self.pan_position = SERVO_CENTER
            self.tilt_position = SERVO_CENTER
            self.target_pan = SERVO_CENTER
            self.target_tilt = SERVO_CENTER

            # Reset PID controllers and tracking state
            self.pid_pan.reset()
            self.pid_tilt.reset()

            # Reset feedback control state
            self.last_offset_x = 0.0
            self.last_offset_y = 0.0
            self.error_history_x.clear()
            self.error_history_y.clear()
            self.convergence_check_count = 0
            self.is_converged = False

            self.logger.info("Servos centered and tracking state reset")

        except Exception as e:
            self.logger.error(f"Failed to center servos: {e}")
    
    def move_servo_direct(self, channel: int, target_angle: float):
        """
        Move servo directly to target position for fastest response

        Args:
            channel: Servo channel (0 for pan, 1 for tilt)
            target_angle: Target angle in degrees
        """
        try:
            # Constrain angle to safe limits
            target_angle = max(SERVO_MIN_ANGLE, min(SERVO_MAX_ANGLE, target_angle))

            # Direct movement - no delays for fastest response
            self.kit.servo[channel].angle = target_angle

            # Update stored position
            if channel == PAN_CHANNEL:
                self.pan_position = target_angle
            else:
                self.tilt_position = target_angle

        except Exception as e:
            self.logger.error(f"Failed to move servo on channel {channel}: {e}")
    
    def handle_vision_data(self, hash_name: str, data: Dict[str, Any]):
        """
        Handle vision processor data and track face position

        Args:
            hash_name: Redis hash name (should be "vision")
            data: Vision data including face position offsets
        """
        # Debug logging to see what data we receive
        self.logger.debug(f"Received vision data: hash={hash_name}, data keys={list(data.keys()) if data else 'None'}")

        if not self.tracking_enabled or not data:
            if not self.tracking_enabled:
                self.logger.debug("Tracking disabled, ignoring vision data")
            return
        
        current_time = time.time()
        
        # Rate limiting - don't update too frequently
        if current_time - self.last_update_time < UPDATE_RATE:
            return
        
        try:
            face_detected = data.get("face_detected", False)
            
            if face_detected:
                # Get face offsets (normalized -1 to 1)
                offset_x = data.get("face_offset_x", 0.0)
                offset_y = data.get("face_offset_y", 0.0)
                
                # Update last face time
                self.last_face_time = current_time
                self.face_lost = False
                
                # Apply dead zone to prevent jitter
                if abs(offset_x) < DEAD_ZONE:
                    offset_x = 0
                if abs(offset_y) < DEAD_ZONE:
                    offset_y = 0
                
                # Only track if face is off-center
                if offset_x != 0 or offset_y != 0:
                    self.logger.debug(f"Face off-center: offset_x={offset_x:+.3f}, offset_y={offset_y:+.3f}, calling track_face")
                    self.track_face(offset_x, offset_y)
                else:
                    self.logger.debug("Face centered, no tracking needed")
                
                self.last_update_time = current_time
                
            else:
                # Face not detected
                if not self.face_lost:
                    self.logger.debug("Face lost - waiting before auto-center")
                    self.face_lost = True
                
                # Auto-center after delay
                if current_time - self.last_face_time > AUTO_CENTER_DELAY:
                    if self.pan_position != SERVO_CENTER or self.tilt_position != SERVO_CENTER:
                        self.logger.info("Auto-centering after face loss")
                        self.center_servos()
                        
        except Exception as e:
            self.logger.error(f"Error handling vision data: {e}")
    
    def calculate_adaptive_speed(self, error_magnitude: float) -> float:
        """
        Calculate adaptive speed multiplier based on error magnitude

        Args:
            error_magnitude: Absolute magnitude of tracking error (0-1)

        Returns:
            Speed multiplier for PID output
        """
        if error_magnitude > MAX_SPEED_THRESHOLD:
            return MAX_SPEED_MULTIPLIER
        elif error_magnitude < MIN_SPEED_THRESHOLD:
            return MIN_SPEED_MULTIPLIER
        else:
            # Linear interpolation between min and max
            ratio = (error_magnitude - MIN_SPEED_THRESHOLD) / (MAX_SPEED_THRESHOLD - MIN_SPEED_THRESHOLD)
            return MIN_SPEED_MULTIPLIER + ratio * (MAX_SPEED_MULTIPLIER - MIN_SPEED_MULTIPLIER)

    def check_convergence(self, offset_x: float, offset_y: float) -> bool:
        """
        Check if face tracking has converged (face is centered)

        Args:
            offset_x: Current horizontal offset
            offset_y: Current vertical offset

        Returns:
            True if face is centered and tracking has converged
        """
        error_magnitude = (offset_x**2 + offset_y**2)**0.5

        if error_magnitude < CENTERING_TOLERANCE:
            self.convergence_check_count += 1
            if self.convergence_check_count >= 3:  # Require 3 consecutive centered readings
                self.is_converged = True
                return True
        else:
            self.convergence_check_count = 0
            self.is_converged = False

        return False

    def smooth_movement(self, current_pos: float, target_pos: float) -> float:
        """
        Apply smoothing to servo movement for stability

        Args:
            current_pos: Current servo position
            target_pos: Target servo position

        Returns:
            Smoothed position for next movement
        """
        # Exponential smoothing
        return current_pos + TRACKING_SMOOTHNESS * (target_pos - current_pos)

    def track_face(self, offset_x: float, offset_y: float):
        """
        Advanced face tracking with adaptive speed control and feedback loop

        Args:
            offset_x: Horizontal offset (-1 to 1, negative = left, positive = right)
            offset_y: Vertical offset (-1 to 1, negative = up, positive = down)
        """
        try:
            # Check if face is already centered
            if self.check_convergence(offset_x, offset_y):
                self.logger.debug(f"Face centered: offset_x={offset_x:+.3f}, offset_y={offset_y:+.3f}")
                return

            # Calculate error magnitude for adaptive speed control
            error_magnitude = (offset_x**2 + offset_y**2)**0.5
            speed_multiplier = self.calculate_adaptive_speed(error_magnitude)

            # Direction mapping with proper feedback:
            # offset_x > 0: face is right → servo turns right (increase angle)
            # offset_x < 0: face is left → servo turns left (decrease angle)
            # offset_y > 0: face is down → servo tilts down (need to invert for servo mechanics)
            # offset_y < 0: face is up → servo tilts up (need to invert for servo mechanics)

            # Calculate PID adjustments with adaptive speed
            pan_adjustment = self.pid_pan(offset_x) * speed_multiplier
            tilt_adjustment = self.pid_tilt(-offset_y) * speed_multiplier  # Invert Y for servo mechanics

            # Calculate target positions
            target_pan = self.pan_position + pan_adjustment
            target_tilt = self.tilt_position + tilt_adjustment

            # Constrain to safe limits
            target_pan = max(SERVO_MIN_ANGLE, min(SERVO_MAX_ANGLE, target_pan))
            target_tilt = max(SERVO_MIN_ANGLE, min(SERVO_MAX_ANGLE, target_tilt))

            # Apply smooth movement for stability
            new_pan = self.smooth_movement(self.pan_position, target_pan)
            new_tilt = self.smooth_movement(self.tilt_position, target_tilt)

            # Move servos with minimum movement threshold to prevent jitter
            moved = False
            if abs(new_pan - self.pan_position) > 0.2:  # Minimum movement threshold
                self.logger.debug(f"Moving PAN servo: {self.pan_position:.1f}° -> {new_pan:.1f}°")
                self.kit.servo[PAN_CHANNEL].angle = new_pan
                self.pan_position = new_pan
                moved = True

            if abs(new_tilt - self.tilt_position) > 0.2:  # Minimum movement threshold
                self.logger.debug(f"Moving TILT servo: {self.tilt_position:.1f}° -> {new_tilt:.1f}°")
                self.kit.servo[TILT_CHANNEL].angle = new_tilt
                self.tilt_position = new_tilt
                moved = True

            # Logging for debugging and performance analysis
            if moved or error_magnitude > 0.1:
                self.logger.debug(f"Tracking: error_mag={error_magnitude:.3f}, speed={speed_multiplier:.2f}x, "
                                f"offset=({offset_x:+.3f},{offset_y:+.3f}) → "
                                f"pos=({self.pan_position:.1f}°,{self.tilt_position:.1f}°), "
                                f"adj=({pan_adjustment:+.2f}°,{tilt_adjustment:+.2f}°)")

            # Update error history for analysis
            self.error_history_x.append(offset_x)
            self.error_history_y.append(offset_y)

            # Keep only recent history (last 10 readings)
            if len(self.error_history_x) > 10:
                self.error_history_x.pop(0)
                self.error_history_y.pop(0)

            # Store current offsets for next iteration
            self.last_offset_x = offset_x
            self.last_offset_y = offset_y

            # Publish servo positions to CogniCore
            self.publish_servo_status()

        except Exception as e:
            self.logger.error(f"Error tracking face: {e}")
    
    def publish_servo_status(self):
        """Publish current servo positions and status to CogniCore"""
        try:
            # Calculate tracking quality metrics
            error_magnitude = 0.0
            if len(self.error_history_x) > 0 and len(self.error_history_y) > 0:
                recent_x = self.error_history_x[-1] if self.error_history_x else 0.0
                recent_y = self.error_history_y[-1] if self.error_history_y else 0.0
                error_magnitude = (recent_x**2 + recent_y**2)**0.5

            status_data = {
                "pan_angle": float(round(self.pan_position, 1)),
                "tilt_angle": float(round(self.tilt_position, 1)),
                "tracking_enabled": self.tracking_enabled,
                "face_tracked": not self.face_lost,
                "is_converged": self.is_converged,
                "tracking_error": float(round(error_magnitude, 3)),
                "convergence_count": self.convergence_check_count,
                "timestamp": time.time()
            }

            self.core.publish_data("motion", status_data)

        except Exception as e:
            self.logger.error(f"Failed to publish servo status: {e}")
    
    def handle_state_change(self, state_data: Dict[str, Any]):
        """Handle system state changes"""
        try:
            state = state_data.get('state')
            
            # Enable tracking when system is in active monitoring state
            if state in ['monitoring_active', 'scanning']:
                if not self.tracking_enabled:
                    self.logger.info(f"System state {state} - enabling tracking")
                    self.tracking_enabled = True
            
            # Disable tracking during errors or inactive states
            elif state in ['system_error', 'system_crashed', 'idle', 'offline']:
                if self.tracking_enabled:
                    self.logger.info(f"System state {state} - disabling tracking")
                    self.tracking_enabled = False
                    self.center_servos()
                    
        except Exception as e:
            self.logger.error(f"Error handling state change: {e}")
    
    def check_pilot_state(self):
        """Check if there's an authenticated pilot and enable tracking accordingly"""
        try:
            authenticated_pilot = self.core.get_authenticated_pilot()

            if authenticated_pilot and not self.tracking_enabled:
                self.logger.info(f"Authenticated pilot detected: {authenticated_pilot} - enabling tracking")
                self.tracking_enabled = True

            elif not authenticated_pilot and self.tracking_enabled:
                self.logger.info("No authenticated pilot - disabling tracking")
                self.tracking_enabled = False
                self.center_servos()

        except Exception as e:
            self.logger.error(f"Error checking pilot state: {e}")
    
    def run(self):
        """Main service loop"""
        self.logger.info("Motion Controller service starting...")
        
        # Initialize servos
        if not self.initialize_servos():
            self.logger.error("Failed to initialize servos - exiting")
            return
        
        # Notify systemd that service is ready
        systemd.daemon.notify('READY=1')
        self.logger.info("Service ready - waiting for vision data")
        
        # Check initial pilot state
        self.check_pilot_state()
        
        self.running = True
        
        # Main service loop
        while self.running:
            try:
                current_time = time.time()
                
                # Send watchdog notification
                if current_time - self.last_heartbeat >= HEARTBEAT_INTERVAL:
                    systemd.daemon.notify('WATCHDOG=1')
                    self.last_heartbeat = current_time
                    
                    # Periodic pilot state check
                    self.check_pilot_state()
                    
                    # Publish current status
                    if self.tracking_enabled:
                        self.publish_servo_status()
                
                # Small sleep to prevent busy waiting
                time.sleep(0.01)
                
            except KeyboardInterrupt:
                self.logger.info("Motion Controller service stopping...")
                break
                
            except Exception as e:
                self.logger.exception(f"Motion Controller error: {e}")
                time.sleep(1)
        
        # Cleanup
        self.logger.info("Centering servos before shutdown...")
        self.center_servos()
        self.logger.info("Motion Controller service stopped")


def main():
    """Main entry point"""
    controller = MotionController()
    controller.run()


if __name__ == "__main__":
    main()