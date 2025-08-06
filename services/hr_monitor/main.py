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

# Add project root to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from bleak import BleakClient, BleakScanner
from CogniCore import CogniCore
from CogniCore import config

# Configuration
HR_UUID = "00002a37-0000-1000-8000-00805f9b34fb"  # Heart Rate Measurement
HR_SENSOR_MAC = config.DEFAULT_HR_SENSOR_MAC
RETRY_DELAY = 5  # seconds
HEARTBEAT_INTERVAL = 10  # seconds
SERVICE_NAME = "hr_monitor"

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
    logger.info("Advanced HR Monitor service started with fatigue prediction")
    
    # Initialize HR analyzer
    analyzer = HRAnalyzer(core, logger)
    
    # Notify systemd that service is ready
    systemd.daemon.notify('READY=1')
    logger.info("Notified systemd that service is ready")
    
    notification_handler = create_notification_handler(core, logger, analyzer)
    last_heartbeat = 0
    
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
                if current_time - last_heartbeat >= HEARTBEAT_INTERVAL:
                    systemd.daemon.notify('WATCHDOG=1')
                    last_heartbeat = current_time
                await asyncio.sleep(1)

def main():
    """Main HR Monitor service entry point."""
    try:
        # Run the HR monitor
        asyncio.run(connect_and_monitor())
        
    except KeyboardInterrupt:
        print("HR Monitor service stopping...")
    except Exception as e:
        print(f"HR Monitor service crashed: {e}")

if __name__ == "__main__":
    main()