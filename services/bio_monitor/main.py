import time
import sys
import logging
import asyncio
import numpy as np
import subprocess
from pathlib import Path
from collections import deque
from typing import List, Optional
import systemd.daemon

# GPIO imports with availability check
try:
    from gpiozero import Button
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

# Add project root to path for imports (deployment flexible)
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from bleak import BleakClient, BleakScanner
from CogniCore import CogniCore
from CogniCore import config

# Configuration
HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"  # Heart Rate Measurement
HR_SENSOR_MAC = config.DEFAULT_HR_SENSOR_MAC
RETRY_DELAY = 5  # seconds
HEARTBEAT_INTERVAL = 10  # seconds
SERVICE_NAME = "bio_monitor"

# MQ3 Alcohol Sensor Configuration
ALCOHOL_SENSOR_PIN = 18  # GPIO 18 (Physical Pin 12) - MQ3 Digital Output
ALCOHOL_WARMUP_TIME = 30  # 30 seconds warmup time for heater stabilization
ALCOHOL_DEBOUNCE_TIME = 2  # 2 seconds debounce to avoid false positives

# Important: MQ3 sensor uses INVERTED LOGIC
# - GPIO HIGH (3.3V) = Clean air (no alcohol detected)
# - GPIO LOW (0V) = Alcohol detected (threshold exceeded)

# HR Analysis Configuration
RR_WINDOW_SIZE = 50  # RR intervals for HRV calculation
HR_TREND_WINDOW = 300  # 5 minutes for trend analysis
BASELINE_UPDATE_INTERVAL = 3600  # Update baseline every hour
STRESS_WINDOW_SIZE = 120  # 2 minutes for stress calculation

def parse_hr_data(data: bytearray) -> tuple[int, Optional[float]]:
    """Parse heart rate data from BLE heart rate measurement."""
    try:
        # Heart Rate Measurement format (standard)
        flags = data[0]
        if flags & 0x01:  # 16-bit HR value
            hr = int.from_bytes(data[1:3], byteorder='little')
        else:  # 8-bit HR value
            hr = int(data[1])
        
        # Extract RR interval if available (for HRV)
        rr_interval = None
        if flags & 0x10 and len(data) >= 4:  # RR interval present
            rr_raw = int.from_bytes(data[-2:], byteorder='little')
            rr_interval = rr_raw / 1024.0  # Convert to seconds
        
        return max(0, min(255, hr)), rr_interval
    except (IndexError, ValueError) as e:
        return 0, None

class AlcoholSensor:
    """
    MQ3 Alcohol Sensor monitoring and detection with inverted logic handling.

    The MQ3 sensor module uses inverted digital output logic:
    - HIGH (3.3V) = Clean air, no alcohol detected
    - LOW (0V) = Alcohol detected above threshold

    Features:
    - 30-second warmup period for heater stabilization
    - 2-second debounce to prevent false positive spam
    - Immediate publishing to CogniCore 'alcohol_detected' hash
    - GPIO diagnostics for troubleshooting sensor connections
    """

    def __init__(self, core: CogniCore, logger):
        self.core = core
        self.logger = logger
        self.last_detection_time = 0
        self.warmup_start_time = 0
        self.is_warmed_up = False
        self.sensor = None

        # Initialize GPIO
        self.setup_gpio()

    def setup_gpio(self):
        """
        Setup GPIO for MQ3 alcohol sensor using gpiozero library.

        Configures GPIO 18 as input with pull-down resistor for reliable readings.
        The gpiozero Button class is used with pull_up=False to enable internal pull-down.
        """
        try:
            if not GPIO_AVAILABLE:
                self.logger.error("gpiozero library not available - alcohol sensor disabled")
                return

            # Setup MQ3 digital output pin as input with pull-down
            self.sensor = Button(ALCOHOL_SENSOR_PIN, pull_up=False)

            # Run initial diagnostics
            self.run_sensor_diagnostics()

            self.warmup_start_time = time.time()
            self.logger.info(f"Alcohol sensor GPIO {ALCOHOL_SENSOR_PIN} initialized using gpiozero, starting warmup...")
        except Exception as e:
            self.logger.error(f"Failed to setup alcohol sensor GPIO: {e}")
            self.sensor = None

    def run_sensor_diagnostics(self):
        """
        Run diagnostics to check sensor wiring and configuration.

        Tests GPIO behavior with different pull resistor configurations to determine:
        1. If sensor is physically connected
        2. If sensor is powered correctly
        3. If wiring is correct

        Diagnostic Results:
        - Both HIGH: Sensor outputting HIGH (normal clean air state)
        - Both LOW: Sensor detecting alcohol or not powered
        - Different: GPIO responds to pull resistors - likely connected properly
        """
        if not self.sensor:
            return

        try:
            # Test current state
            current_state = self.sensor.is_pressed
            self.logger.info(f"MQ3 Diagnostics - Initial GPIO 18 state: {'HIGH' if current_state else 'LOW'}")

            # Test with different pull configurations
            time.sleep(0.1)

            # Close current sensor and test with pull-up
            self.sensor.close()
            test_sensor_pullup = Button(ALCOHOL_SENSOR_PIN, pull_up=True)
            pullup_state = test_sensor_pullup.is_pressed
            test_sensor_pullup.close()

            # Recreate original sensor with pull-down
            self.sensor = Button(ALCOHOL_SENSOR_PIN, pull_up=False)
            pulldown_state = self.sensor.is_pressed

            self.logger.info(f"MQ3 Diagnostics - With pull-up: {'HIGH' if pullup_state else 'LOW'}, With pull-down: {'HIGH' if pulldown_state else 'LOW'}")

            # Determine likely issue (sensor uses inverted logic: HIGH=clean, LOW=alcohol)
            if pullup_state and pulldown_state:
                self.logger.warning("MQ3 Diagnostics - GPIO 18 reads HIGH in both configurations - sensor outputting HIGH (normal clean air state)")
            elif not pullup_state and not pulldown_state:
                self.logger.warning("MQ3 Diagnostics - GPIO 18 reads LOW in both configurations - sensor detecting alcohol or not powered")
            else:
                self.logger.info("MQ3 Diagnostics - GPIO 18 responds to pull resistors - sensor connected properly. Note: Uses inverted logic (HIGH=clean, LOW=alcohol)")

        except Exception as e:
            self.logger.error(f"MQ3 diagnostics failed: {e}")

    def check_warmup(self):
        """Check if sensor has completed warmup period"""
        if not self.is_warmed_up:
            if time.time() - self.warmup_start_time >= ALCOHOL_WARMUP_TIME:
                self.is_warmed_up = True
                self.logger.info("Alcohol sensor warmup completed - ready for detection")

    def read_sensor(self):
        """
        Read alcohol sensor and publish detection events to CogniCore.

        Process:
        1. Check if sensor completed 30-second warmup period
        2. Read GPIO 18 state using gpiozero (inverted logic: LOW = alcohol detected)
        3. Apply 2-second debounce to prevent rapid-fire detections
        4. Publish detection event with timestamp to 'alcohol_detected' Redis hash
        5. Log detection with GPIO state for debugging

        Returns:
            bool: True if alcohol was detected and published, False otherwise
        """
        try:
            if not self.sensor:
                return False

            # Check warmup status
            self.check_warmup()
            if not self.is_warmed_up:
                return False

            # Read digital output (LOW = alcohol detected, HIGH = clean air - inverted logic)
            alcohol_detected = not self.sensor.is_pressed
            current_time = time.time()

            # Debug logging every 10 seconds to see sensor state
            if not hasattr(self, '_last_debug_time'):
                self._last_debug_time = 0

            if current_time - self._last_debug_time >= 10:
                gpio_state = "HIGH" if self.sensor.is_pressed else "LOW"
                self.logger.debug(f"MQ3 sensor: GPIO={gpio_state}, Alcohol={'DETECTED' if alcohol_detected else 'CLEAN'}")
                self._last_debug_time = current_time

            # Debounce - only trigger if enough time has passed since last detection
            if alcohol_detected and (current_time - self.last_detection_time) >= ALCOHOL_DEBOUNCE_TIME:
                self.last_detection_time = current_time

                # Publish alcohol detection to CogniCore hash
                alcohol_data = {
                    "detected": True,
                    "timestamp": current_time,
                    "detection_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(current_time))
                }

                # Publish to alcohol_detected hash using CogniCore
                self.core.publish_data("alcohol_detected", alcohol_data)
                gpio_state = "HIGH" if self.sensor.is_pressed else "LOW"
                self.logger.warning(f"ALCOHOL DETECTED! GPIO 18 = {gpio_state} (inverted logic), Published to alcohol_detected hash: {alcohol_data}")

                return True

            return alcohol_detected

        except Exception as e:
            self.logger.error(f"Error reading alcohol sensor: {e}")
            return False

    def cleanup(self):
        """Cleanup GPIO resources"""
        try:
            if self.sensor:
                self.sensor.close()
            self.logger.info("Alcohol sensor GPIO cleaned up")
        except Exception as e:
            self.logger.error(f"Error cleaning up GPIO: {e}")

class HRAnalyzer:
    """Advanced heart rate analysis for fatigue prediction"""

    def __init__(self, core: CogniCore, logger):
        self.core = core
        self.logger = logger

        # Data storage
        self.hr_history = deque(maxlen=HR_TREND_WINDOW)
        self.rr_intervals = deque(maxlen=RR_WINDOW_SIZE)
        self.timestamp_history = deque(maxlen=HR_TREND_WINDOW)

        # Baseline tracking
        self.baseline_hr = None
        self.baseline_hrv = None
        self.last_baseline_update = 0

        # Stress tracking
        self.stress_scores = deque(maxlen=STRESS_WINDOW_SIZE)
        
    def update_baseline(self, pilot_profile):
        """Update baseline from pilot profile"""
        if pilot_profile and pilot_profile.baseline:
            self.baseline_hr = pilot_profile.baseline.get('heart_rate', 72)
            self.baseline_hrv = pilot_profile.baseline.get('heart_rate_variability', 45)
            self.logger.info(f"Updated baseline: HR={self.baseline_hr}, HRV={self.baseline_hrv}")
        else:
            # Use default values if no profile
            self.baseline_hr = 72
            self.baseline_hrv = 45
            
    def calculate_baseline_deviation(self, current_hr: int) -> float:
        """Calculate heart rate baseline deviation percentage"""
        if not self.baseline_hr:
            return 0.0
        
        deviation = abs(current_hr - self.baseline_hr) / self.baseline_hr
        return min(1.0, deviation)  # Cap at 100%
    
    def calculate_rmssd(self) -> Optional[float]:
        """Calculate RMSSD (Root Mean Square of Successive Differences) for HRV"""
        if len(self.rr_intervals) < 5:
            return None
            
        try:
            rr_array = np.array(list(self.rr_intervals))
            # Calculate successive differences
            diff_rr = np.diff(rr_array)
            # Square the differences
            squared_diff = diff_rr ** 2
            # Calculate mean and square root
            rmssd = np.sqrt(np.mean(squared_diff)) * 1000  # Convert to ms
            return float(rmssd)
        except Exception as e:
            self.logger.error(f"Error calculating RMSSD: {e}")
            return None
    
    def calculate_hr_trend(self) -> Optional[float]:
        """Calculate heart rate trend/drift over time"""
        if len(self.hr_history) < 10:
            return None
            
        try:
            hr_array = np.array(list(self.hr_history))
            time_array = np.array(list(self.timestamp_history))
            
            # Calculate linear regression slope
            coeffs = np.polyfit(time_array - time_array[0], hr_array, 1)
            trend = float(coeffs[0])  # bpm per second
            
            # Convert to bpm per minute
            return trend * 60
        except Exception as e:
            self.logger.error(f"Error calculating HR trend: {e}")
            return None
    
    def calculate_stress_index(self, current_hr: int, rmssd: Optional[float]) -> float:
        """Calculate stress index based on HR elevation and HRV reduction"""
        stress_score = 0.0
        
        # HR-based stress (50% weight)
        if self.baseline_hr:
            hr_elevation = max(0, (current_hr - self.baseline_hr) / self.baseline_hr)
            stress_score += min(0.5, hr_elevation * 0.5)
        
        # HRV-based stress (50% weight)
        if rmssd and self.baseline_hrv:
            hrv_reduction = max(0, (self.baseline_hrv - rmssd) / self.baseline_hrv)
            stress_score += min(0.5, hrv_reduction * 0.5)
        
        # Store for moving average
        self.stress_scores.append(stress_score)
        
        # Return smoothed stress index
        return float(np.mean(self.stress_scores)) if self.stress_scores else stress_score
    
    def process_hr_reading(self, hr: int, rr_interval: Optional[float], timestamp: float):
        """Process new heart rate reading and calculate metrics"""
        # Store data
        self.hr_history.append(hr)
        self.timestamp_history.append(timestamp)
        
        if rr_interval:
            self.rr_intervals.append(rr_interval)
        
        # Update baseline if needed
        pilot_profile = self.core.get_active_pilot_profile()
        current_time = time.time()
        if current_time - self.last_baseline_update > BASELINE_UPDATE_INTERVAL:
            self.update_baseline(pilot_profile)
            self.last_baseline_update = current_time
        
        # Calculate metrics
        baseline_deviation = self.calculate_baseline_deviation(hr)
        rmssd = self.calculate_rmssd()
        hr_trend = self.calculate_hr_trend()
        stress_index = self.calculate_stress_index(hr, rmssd)
        
        return {
            'baseline_deviation': baseline_deviation,
            'rmssd': rmssd,
            'hr_trend': hr_trend,
            'stress_index': stress_index,
            'baseline_hr': self.baseline_hr,
            'baseline_hrv': self.baseline_hrv
        }

def create_notification_handler(core, logger, analyzer):
    """Create notification handler with core, logger, and analyzer access."""
    def notification_handler(sender, data):
        """Handle heart rate notifications from BLE device."""
        try:
            hr, rr_interval = parse_hr_data(data)
            if hr and hr > 0:
                timestamp = time.time()
                
                # Process with advanced analyzer
                metrics = analyzer.process_hr_reading(hr, rr_interval, timestamp)
                
                # Prepare comprehensive HR data
                hr_data = {
                    "hr": hr,
                    "t_hr": timestamp,
                    "rr_interval": rr_interval,
                    "baseline_deviation": metrics['baseline_deviation'],
                    "rmssd": metrics['rmssd'],
                    "hr_trend": metrics['hr_trend'],
                    "stress_index": metrics['stress_index'],
                    "baseline_hr": metrics['baseline_hr'],
                    "baseline_hrv": metrics['baseline_hrv']
                }
                
                try:
                    # Publish enhanced HR data to CogniCore
                    core.publish_data("hr_sensor", hr_data)
                    
                    # Log all HR metrics
                    logger.info(f"HR: {hr} BPM | RR: {rr_interval:.3f}s | Dev: {metrics['baseline_deviation']:.3f} | RMSSD: {metrics['rmssd']:.1f}ms | Trend: {metrics['hr_trend']:.2f} BPM/min | Stress: {metrics['stress_index']:.3f} | Baseline HR: {metrics['baseline_hr']} | Baseline HRV: {metrics['baseline_hrv']}")
                    logger.debug(f"Published enhanced HR data: {hr_data}")
                except Exception as e:
                    logger.error(f"Failed to publish HR data: {e}")
            else:
                logger.warning("Invalid heart rate data received")
        except Exception as e:
            logger.error(f"Error handling HR notification: {e}")
    
    return notification_handler

def disconnect_system_bluetooth(mac_address: str, logger):
    """Simple disconnect from system Bluetooth."""
    try:
        result = subprocess.run(['bluetoothctl', 'disconnect', mac_address], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            logger.info(f"Disconnected {mac_address} from system")
        return result.returncode == 0
    except Exception as e:
        logger.warning(f"Could not disconnect {mac_address}: {e}")
        return False

async def connect_and_monitor():
    """Connect to HR sensor and monitor continuously."""
    core = CogniCore(SERVICE_NAME)
    logger = core.get_logger(SERVICE_NAME)
    logger.info("Advanced Bio Monitor service started with fatigue prediction and alcohol detection")

    # Initialize HR analyzer and alcohol sensor
    analyzer = HRAnalyzer(core, logger)
    alcohol_sensor = AlcoholSensor(core, logger)

    # Notify systemd that service is ready
    systemd.daemon.notify('READY=1')
    logger.info("Notified systemd that service is ready")

    notification_handler = create_notification_handler(core, logger, analyzer)
    last_heartbeat = 0
    last_alcohol_check = 0

    try:
        while True:
            try:
                # Disconnect from system first
                disconnect_system_bluetooth(HR_SENSOR_MAC, logger)
                await asyncio.sleep(2)  # Wait for disconnect

                logger.info(f"Attempting to connect to HR sensor: {HR_SENSOR_MAC}")

                async with BleakClient(HR_SENSOR_MAC) as client:
                    logger.info("Connected to HR sensor")

                    # Start heart rate notifications
                    await client.start_notify(HR_UUID, notification_handler)
                    logger.info("Started heart rate notifications")

                    # Stay connected and handle notifications
                    while client.is_connected:
                        current_time = time.time()

                        # Check alcohol sensor every second
                        if current_time - last_alcohol_check >= 1.0:
                            alcohol_sensor.read_sensor()
                            last_alcohol_check = current_time

                        # Send watchdog notification periodically
                        if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                            systemd.daemon.notify('WATCHDOG=1')
                            last_heartbeat = current_time

                        await asyncio.sleep(1)

            except Exception as e:
                logger.warning(f"HR sensor connection failed: {e}. Retrying in {RETRY_DELAY}s")

                # Send watchdog notifications during retry delay to prevent timeout
                retry_start = time.time()
                while time.time() - retry_start < RETRY_DELAY:
                    current_time = time.time()

                    # Continue checking alcohol sensor during retry
                    if current_time - last_alcohol_check >= 1.0:
                        alcohol_sensor.read_sensor()
                        last_alcohol_check = current_time

                    if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                        systemd.daemon.notify('WATCHDOG=1')
                        last_heartbeat = current_time
                    await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Bio Monitor service stopping...")
    except Exception as e:
        logger.error(f"Bio Monitor service crashed: {e}")
    finally:
        # Cleanup alcohol sensor GPIO
        alcohol_sensor.cleanup()

def main():
    """Main Bio Monitor service entry point."""
    try:
        # Run the HR monitor with alcohol detection
        asyncio.run(connect_and_monitor())

    except KeyboardInterrupt:
        print("Bio Monitor service stopping...")
    except Exception as e:
        print(f"Bio Monitor service crashed: {e}")
    finally:
        # Ensure GPIO cleanup on any exit
        pass

if __name__ == "__main__":
    main()