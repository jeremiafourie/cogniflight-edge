import os
import sys
import time
import logging
import threading
from pathlib import Path
from threading import Timer
import systemd.daemon

# Add project root to path for imports (deployment flexible)
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from CogniCore import CogniCore, SystemState
from CogniCore import config

# GPIO imports with availability check
try:
    from gpiozero import LED, Buzzer, OutputDevice
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

SERVICE_NAME = "alert_manager"

class AlertManager:
    """Alert Manager - Listens to system state changes and controls RGB LED and GPIO hardware"""
    
    def __init__(self):
        self.core = CogniCore(SERVICE_NAME)
        self.logger = self.core.get_logger(SERVICE_NAME)
        
        # Track current state to avoid duplicate displays
        self.current_state = None
        self.current_message = None
        
        # Initialize GPIO hardware
        self.gpio_initialized = False
        self.initialize_gpio()
        
        # Threading control for GPIO effects
        self.gpio_threads = []
        self.stop_gpio_effects = threading.Event()
        
        # Subscribe ONLY to state changes
        self.core.subscribe_to_state_changes(self.on_state_change)
        
        # Notify systemd that service is ready
        systemd.daemon.notify('READY=1')
        self.logger.info("Notified systemd that service is ready")
        
        self.logger.info("Alert Manager initialized - listening to state changes and controlling RGB LED")
    
    def initialize_gpio(self):
        """Initialize GPIO hardware components"""
        if not GPIO_AVAILABLE:
            self.logger.warning("GPIO Zero not available, GPIO functionality disabled")
            return
        
        try:
            # Initialize RGB LED (Common Cathode)
            self.red_channel = LED(17)    # GPIO 17: Red channel
            self.green_channel = LED(27)  # GPIO 27: Green channel
            self.blue_channel = LED(22)   # GPIO 22: Blue channel
            
            # Initialize buzzer (inverted logic for 9012 transistor module) and vibrator
            self.buzzer = OutputDevice(24, active_high=False)  # GPIO 24: HKD Active Buzzer with 9012 transistor
            self.vibrator = OutputDevice(25)  # GPIO 25: Vibrator Motor
            
            # Set initialized flag first so turn_off_all_devices works
            self.gpio_initialized = True
            
            # Turn off all devices initially
            self.turn_off_all_devices()

            # Extra safety: explicitly ensure buzzer is off
            try:
                self.buzzer.off()
                self.logger.debug("Buzzer explicitly turned off during initialization")
            except Exception as e:
                self.logger.error(f"Failed to explicitly turn off buzzer: {e}")

            self.logger.info("GPIO hardware initialized successfully")
            
        except Exception as e:
            self.logger.error(f"GPIO initialization failed: {e}")
            self.gpio_initialized = False
    
    def turn_off_all_devices(self):
        """Turn off all GPIO devices with individual error handling"""
        if not self.gpio_initialized:
            return
        
        devices = [
            ("red_channel", self.red_channel),
            ("green_channel", self.green_channel), 
            ("blue_channel", self.blue_channel),
            ("buzzer", self.buzzer),
            ("vibrator", self.vibrator)
        ]
        
        errors = []
        for device_name, device in devices:
            try:
                if hasattr(device, 'off'):
                    device.off()
            except Exception as e:
                errors.append(f"{device_name}: {e}")
        
        if errors:
            self.logger.error(f"Errors turning off devices: {'; '.join(errors)}")
        else:
            self.logger.debug("All GPIO devices turned off successfully")
    
    def stop_all_gpio_effects(self):
        """Stop all running GPIO effects with improved cleanup"""
        self.stop_gpio_effects.set()
        
        # Wait for threads to finish with better timeout handling
        threads_to_cleanup = []
        for thread in self.gpio_threads:
            if thread.is_alive():
                thread.join(timeout=2.0)
                if thread.is_alive():
                    threads_to_cleanup.append(thread.name if thread.name else "unnamed")
                    self.logger.warning(f"Thread {thread.name or 'unnamed'} failed to stop within timeout")
        
        # Log any problematic threads
        if threads_to_cleanup:
            self.logger.error(f"Failed to cleanly stop threads: {threads_to_cleanup}")
        
        # Always cleanup state regardless of thread status
        self.gpio_threads.clear()
        self.stop_gpio_effects.clear()
        
        # Force GPIO cleanup even if threads didn't stop properly
        try:
            self.turn_off_all_devices()
            # Extra safety: explicitly ensure buzzer is off
            if self.gpio_initialized and hasattr(self, 'buzzer'):
                self.buzzer.off()
                self.logger.debug("Buzzer explicitly turned off during effect cleanup")
        except Exception as e:
            self.logger.error(f"Error during forced GPIO cleanup: {e}")
    
    def start_gpio_effect(self, effect_func, *args):
        """Start a GPIO effect in a separate thread with proper naming"""
        self.stop_all_gpio_effects()
        effect_name = effect_func.__name__ if hasattr(effect_func, '__name__') else "gpio_effect"
        thread = threading.Thread(target=effect_func, args=args, daemon=True, name=effect_name)
        thread.start()
        self.gpio_threads.append(thread)
    
    def scanning_effect(self):
        """SCANNING: Toggle yellow color (red+green) continuously with periodic buzzer every 30 seconds"""
        if not self.gpio_initialized:
            return
        
        # Turn off all channels and devices at start
        if not self.set_rgb_color(False, False, False):
            self.logger.warning("Failed to initialize RGB LED for scanning effect")
        
        self.safe_gpio_control(self.buzzer, "off", "buzzer")
        self.safe_gpio_control(self.vibrator, "off", "vibrator")
        
        last_buzzer_time = 0
        
        while not self.stop_gpio_effects.is_set():
            try:
                # Toggle yellow (red + green)
                self.set_rgb_color(True, True, False)
                time.sleep(0.5)
                
                if self.stop_gpio_effects.is_set():
                    break
                    
                self.set_rgb_color(False, False, False)
                time.sleep(0.5)
                
                # Buzzer beep every 30 seconds
                current_time = time.time()
                if current_time - last_buzzer_time >= 30:
                    if self.safe_gpio_control(self.buzzer, "on", "buzzer"):
                        time.sleep(0.1)
                        # Ensure buzzer turns off after beep
                        if not self.safe_gpio_control(self.buzzer, "off", "buzzer"):
                            self.logger.error("Failed to turn off buzzer after scanning beep")
                    last_buzzer_time = current_time
                
            except Exception as e:
                self.logger.error(f"Error in scanning effect: {e}")
                break

        # Cleanup: ensure buzzer is off when scanning effect ends
        self.safe_gpio_control(self.buzzer, "off", "buzzer")
    
    def intruder_detected_effect(self):
        """INTRUDER_DETECTED: Alternate red/blue colors, toggle buzzer and vibrator (siren-like)"""
        if not self.gpio_initialized:
            return

        while not self.stop_gpio_effects.is_set():
            try:
                # Red color + buzzer + vibrator on
                self.set_rgb_color(True, False, False)
                self.safe_gpio_control(self.buzzer, "on", "buzzer")
                self.safe_gpio_control(self.vibrator, "on", "vibrator")
                time.sleep(0.5)

                if self.stop_gpio_effects.is_set():
                    break

                # Blue color + buzzer + vibrator off
                self.set_rgb_color(False, False, True)
                self.safe_gpio_control(self.buzzer, "off", "buzzer")
                self.safe_gpio_control(self.vibrator, "off", "vibrator")
                time.sleep(0.5)

            except Exception as e:
                self.logger.error(f"Error in intruder detected effect: {e}")
                break

        # Cleanup: ensure buzzer and vibrator are off when effect ends
        self.safe_gpio_control(self.buzzer, "off", "buzzer")
        self.safe_gpio_control(self.vibrator, "off", "vibrator")
    
    def monitoring_active_effect(self):
        """MONITORING_ACTIVE: Keep green color on"""
        if not self.gpio_initialized:
            return
        
        try:
            self.turn_off_all_devices()
            self.set_rgb_color(False, True, False)
        except Exception as e:
            self.logger.error(f"Error in monitoring active effect: {e}")
    
    def system_crashed_effect(self):
        """SYSTEM_CRASHED: Red color and buzzer continuously on"""
        if not self.gpio_initialized:
            return

        try:
            self.turn_off_all_devices()
            self.set_rgb_color(True, False, False)
            self.safe_gpio_control(self.buzzer, "on", "buzzer")
        except Exception as e:
            self.logger.error(f"Error in system crashed effect: {e}")
    
    def system_error_effect(self):
        """SYSTEM_ERROR: Toggle red color and short buzzer beeps"""
        if not self.gpio_initialized:
            return

        while not self.stop_gpio_effects.is_set():
            try:
                # Red color and buzzer on
                self.set_rgb_color(True, False, False)
                self.safe_gpio_control(self.buzzer, "on", "buzzer")
                time.sleep(0.1)  # Short beep
                self.safe_gpio_control(self.buzzer, "off", "buzzer")
                time.sleep(0.4)  # LED stays on for total 0.5s

                if self.stop_gpio_effects.is_set():
                    break

                # LED off
                self.set_rgb_color(False, False, False)
                time.sleep(0.5)

            except Exception as e:
                self.logger.error(f"Error in system error effect: {e}")
                break

        # Cleanup: ensure buzzer is off when effect ends
        self.safe_gpio_control(self.buzzer, "off", "buzzer")
    
    def alert_mild_effect(self):
        """ALERT_MILD: Slow pulsing blue (breathing effect), triple beeps every 20s"""
        if not self.gpio_initialized:
            return

        last_buzzer_time = 0
        beep_stage = 0  # 0=off, 1=beep1, 2=pause1, 3=beep2, 4=pause2, 5=beep3
        beep_stage_start = 0

        cycle_start = time.time()
        cycle_duration = 3.0  # Full breathing cycle: 1.5s on + 1.5s off

        while not self.stop_gpio_effects.is_set():
            try:
                current_time = time.time()
                cycle_position = (current_time - cycle_start) % cycle_duration

                # Simplified breathing effect - just on/off
                # Phase 1 (0-1.5s): Blue ON (bright)
                # Phase 2 (1.5-3s): Blue OFF (dark)

                if cycle_position < 1.5:
                    # Blue ON - solid for better visibility
                    self.set_rgb_color(False, False, True)
                    time.sleep(0.1)
                else:
                    # Blue OFF
                    self.set_rgb_color(False, False, False)
                    time.sleep(0.1)

                # Handle triple beep pattern every 20 seconds (non-blocking)
                if beep_stage == 0 and current_time - last_buzzer_time >= 20:
                    # Start beep sequence
                    beep_stage = 1
                    beep_stage_start = current_time
                    self.safe_gpio_control(self.buzzer, "on", "buzzer")
                elif beep_stage == 1 and current_time - beep_stage_start >= 0.1:
                    # End first beep
                    self.safe_gpio_control(self.buzzer, "off", "buzzer")
                    beep_stage = 2
                    beep_stage_start = current_time
                elif beep_stage == 2 and current_time - beep_stage_start >= 0.1:
                    # Start second beep
                    self.safe_gpio_control(self.buzzer, "on", "buzzer")
                    beep_stage = 3
                    beep_stage_start = current_time
                elif beep_stage == 3 and current_time - beep_stage_start >= 0.1:
                    # End second beep
                    self.safe_gpio_control(self.buzzer, "off", "buzzer")
                    beep_stage = 4
                    beep_stage_start = current_time
                elif beep_stage == 4 and current_time - beep_stage_start >= 0.1:
                    # Start third beep
                    self.safe_gpio_control(self.buzzer, "on", "buzzer")
                    beep_stage = 5
                    beep_stage_start = current_time
                elif beep_stage == 5 and current_time - beep_stage_start >= 0.1:
                    # End third beep, reset cycle
                    self.safe_gpio_control(self.buzzer, "off", "buzzer")
                    beep_stage = 0
                    last_buzzer_time = current_time

                if self.stop_gpio_effects.is_set():
                    break

            except Exception as e:
                self.logger.error(f"Error in alert mild effect: {e}")
                break

        # Cleanup: ensure buzzer is off when effect ends
        self.safe_gpio_control(self.buzzer, "off", "buzzer")
    
    def alert_moderate_effect(self):
        """ALERT_MODERATE: Yellow/Orange rapid alternation with pause, double beeps and vibrator pulses every 12s"""
        if not self.gpio_initialized:
            return

        last_alert_time = 0
        alert_stage = 0  # 0=off, 1=beep1+vib1, 2=pause1, 3=beep2+vib2
        alert_stage_start = 0
        strobe_count = 0

        while not self.stop_gpio_effects.is_set():
            try:
                current_time = time.time()

                # Strobe pattern: 4 rapid alternations then 1 second pause
                if strobe_count < 8:  # 4 cycles of yellow/orange (8 transitions)
                    if strobe_count % 2 == 0:
                        # Yellow (red + green)
                        self.set_rgb_color(True, True, False)
                    else:
                        # Orange (red + more green) - approximated as red + green
                        # Note: True RGB orange isn't possible with digital RGB, using yellow as "orange"
                        self.set_rgb_color(True, True, False)
                    time.sleep(0.3)
                    strobe_count += 1
                else:
                    # Pause - all off
                    self.set_rgb_color(False, False, False)
                    time.sleep(1.0)
                    strobe_count = 0

                # Handle double beep + vibrator pulse pattern every 12 seconds (non-blocking)
                if alert_stage == 0 and current_time - last_alert_time >= 12:
                    # Start first beep + vibration
                    alert_stage = 1
                    alert_stage_start = current_time
                    self.safe_gpio_control(self.buzzer, "on", "buzzer")
                    self.safe_gpio_control(self.vibrator, "on", "vibrator")
                elif alert_stage == 1 and current_time - alert_stage_start >= 0.2:
                    # End first beep + vibration
                    self.safe_gpio_control(self.buzzer, "off", "buzzer")
                    self.safe_gpio_control(self.vibrator, "off", "vibrator")
                    alert_stage = 2
                    alert_stage_start = current_time
                elif alert_stage == 2 and current_time - alert_stage_start >= 0.2:
                    # Start second beep + vibration
                    self.safe_gpio_control(self.buzzer, "on", "buzzer")
                    self.safe_gpio_control(self.vibrator, "on", "vibrator")
                    alert_stage = 3
                    alert_stage_start = current_time
                elif alert_stage == 3 and current_time - alert_stage_start >= 0.2:
                    # End second beep + vibration, reset cycle
                    self.safe_gpio_control(self.buzzer, "off", "buzzer")
                    self.safe_gpio_control(self.vibrator, "off", "vibrator")
                    alert_stage = 0
                    last_alert_time = current_time

                if self.stop_gpio_effects.is_set():
                    break

            except Exception as e:
                self.logger.error(f"Error in alert moderate effect: {e}")
                break

        # Cleanup: ensure buzzer and vibrator are off when effect ends
        self.safe_gpio_control(self.buzzer, "off", "buzzer")
        self.safe_gpio_control(self.vibrator, "off", "vibrator")
    
    def alert_severe_effect(self):
        """ALERT_SEVERE: Very rapid red/magenta alternation, continuous rapid beeping and vibration"""
        if not self.gpio_initialized:
            return

        beep_active = False
        beep_cycle_start = time.time()

        while not self.stop_gpio_effects.is_set():
            try:
                current_time = time.time()
                beep_cycle_position = (current_time - beep_cycle_start) % 0.6

                # Continuous rapid beep pattern: 0.3s on, 0.3s off
                if beep_cycle_position < 0.3:
                    if not beep_active:
                        self.safe_gpio_control(self.buzzer, "on", "buzzer")
                        self.safe_gpio_control(self.vibrator, "on", "vibrator")
                        beep_active = True
                else:
                    if beep_active:
                        self.safe_gpio_control(self.buzzer, "off", "buzzer")
                        self.safe_gpio_control(self.vibrator, "off", "vibrator")
                        beep_active = False

                # Very rapid red/magenta alternation
                # Red color (red only)
                self.set_rgb_color(True, False, False)
                time.sleep(0.2)

                if self.stop_gpio_effects.is_set():
                    break

                # Magenta color (red + blue)
                self.set_rgb_color(True, False, True)
                time.sleep(0.2)

            except Exception as e:
                self.logger.error(f"Error in alert severe effect: {e}")
                break

        # Cleanup: ensure buzzer and vibrator are off when effect ends
        self.safe_gpio_control(self.buzzer, "off", "buzzer")
        self.safe_gpio_control(self.vibrator, "off", "vibrator")

    def alcohol_detected_effect(self):
        """ALCOHOL_DETECTED: Alternate red/orange colors, toggle buzzer and vibrator (alcohol alert)"""
        if not self.gpio_initialized:
            return

        while not self.stop_gpio_effects.is_set():
            try:
                # Red color + buzzer + vibrator on
                self.set_rgb_color(True, False, False)
                self.safe_gpio_control(self.buzzer, "on", "buzzer")
                self.safe_gpio_control(self.vibrator, "on", "vibrator")
                time.sleep(0.5)

                if self.stop_gpio_effects.is_set():
                    break

                # Orange color (red + green) + buzzer + vibrator off
                self.set_rgb_color(True, True, False)
                self.safe_gpio_control(self.buzzer, "off", "buzzer")
                self.safe_gpio_control(self.vibrator, "off", "vibrator")
                time.sleep(0.5)

            except Exception as e:
                self.logger.error(f"Error in alcohol detected effect: {e}")
                break

        # Cleanup: ensure buzzer and vibrator are off when effect ends
        self.safe_gpio_control(self.buzzer, "off", "buzzer")
        self.safe_gpio_control(self.vibrator, "off", "vibrator")

    def control_gpio_for_state(self, state: str):
        """Control GPIO hardware based on system state"""
        if not self.gpio_initialized:
            self.logger.warning(f"GPIO not initialized, skipping hardware control for state: {state}")
            return
        
        self.logger.info(f"Activating GPIO effects for state: {state}")
        
        try:
            if state == "scanning":
                self.start_gpio_effect(self.scanning_effect)
            elif state == "intruder_detected":
                self.start_gpio_effect(self.intruder_detected_effect)
            elif state == "monitoring_active":
                self.start_gpio_effect(self.monitoring_active_effect)
            elif state == "system_crashed":
                self.start_gpio_effect(self.system_crashed_effect)
            elif state == "system_error":
                self.start_gpio_effect(self.system_error_effect)
            elif state == "alert_mild":
                self.start_gpio_effect(self.alert_mild_effect)
            elif state == "alert_moderate":
                self.start_gpio_effect(self.alert_moderate_effect)
            elif state == "alert_severe":
                self.start_gpio_effect(self.alert_severe_effect)
            elif state == "alcohol_detected":
                self.start_gpio_effect(self.alcohol_detected_effect)
            else:
                self.logger.warning(f"Unknown state for GPIO control: {state}")
                self.stop_all_gpio_effects()
                
            self.logger.info(f"GPIO effects activated successfully for state: {state}")
            
        except Exception as e:
            self.logger.error(f"Failed to activate GPIO effects for state {state}: {e}")
    
    def set_rgb_color(self, red: bool, green: bool, blue: bool):
        """Set RGB LED color based on channel states with individual channel error handling"""
        if not self.gpio_initialized:
            return
        
        channels = [
            ("red", red, self.red_channel),
            ("green", green, self.green_channel),
            ("blue", blue, self.blue_channel)
        ]
        
        errors = []
        successful_channels = []
        
        for color_name, state, channel in channels:
            try:
                if state:
                    channel.on()
                else:
                    channel.off()
                successful_channels.append(f"{color_name}={state}")
            except Exception as e:
                errors.append(f"{color_name}: {e}")
        
        if errors:
            self.logger.error(f"RGB channel errors: {'; '.join(errors)}")
        
        if successful_channels:
            final_color = self.get_color_name(red, green, blue)
            self.logger.debug(f"RGB LED set to: {final_color} ({', '.join(successful_channels)})")
        
        return len(errors) == 0  # Return success status
    
    def safe_gpio_control(self, device, action, device_name="device"):
        """Safely control a GPIO device with error handling"""
        if not self.gpio_initialized:
            return False

        try:
            if action == "on":
                device.on()
                # Special logging for buzzer to track activity
                if device_name == "buzzer":
                    self.logger.info(f"BUZZER ON - GPIO 24 activated")
            elif action == "off":
                device.off()
                # Special logging for buzzer to track activity
                if device_name == "buzzer":
                    self.logger.info(f"BUZZER OFF - GPIO 24 deactivated")
            else:
                self.logger.warning(f"Unknown GPIO action '{action}' for {device_name}")
                return False
            return True
        except Exception as e:
            self.logger.error(f"Error controlling {device_name} ({action}): {e}")
            return False
    
    def get_color_name(self, red: bool, green: bool, blue: bool) -> str:
        """Get color name from RGB states"""
        if red and green and blue:
            return "White"
        elif red and green:
            return "Yellow"
        elif red and blue:
            return "Magenta"
        elif green and blue:
            return "Cyan"
        elif red:
            return "Red"
        elif green:
            return "Green"
        elif blue:
            return "Blue"
        else:
            return "Off"
    
    def on_state_change(self, state_data):
        """Handle system state changes - control RGB LED and GPIO hardware"""
        try:
            state = state_data.get("state", "unknown")
            message = state_data.get("message", "")
            pilot_id = state_data.get("pilot_id")
            timestamp = state_data.get("timestamp", time.time())
            
            # Unified state change detection
            state_changed = state != self.current_state
            message_changed = message != self.current_message
            
            # Skip only if both state AND message are identical
            if not state_changed and not message_changed:
                self.logger.debug(f"No change: {state} - {message}")
                return
            
            # Special rate limiting for monitoring_active to reduce spam
            # but still allow state transitions and significant message changes
            if (state == "monitoring_active" and 
                state == self.current_state and 
                not message_changed):
                self.logger.debug(f"Skipping frequent monitoring update: {message}")
                return
            
            # Update tracking variables
            prev_state = self.current_state
            self.current_state = state
            self.current_message = message
            
            self.logger.info(f"State change: {prev_state} -> {state}: {message}")
            
            # Control GPIO hardware for the new state (always trigger on actual state change)
            if state_changed or state != "monitoring_active":
                self.control_gpio_for_state(state)
                self.logger.info(f"RGB LED and GPIO updated for state: {state}")
            else:
                self.logger.debug(f"GPIO state maintained for message update: {state}")
            
        except Exception as e:
            self.logger.error(f"Error handling state change (state={state_data.get('state', 'unknown')}): {e}")
    
    def run(self):
        """Main alert manager loop - just keeps running and responding to state changes"""
        self.logger.info("Alert Manager started - waiting for state changes...")
        
        try:
            while True:
                # Just sleep - all work is done via state change callbacks
                time.sleep(1)
        
        except KeyboardInterrupt:
            self.logger.info("Alert Manager stopping...")
            self.stop_all_gpio_effects()
            self.core.shutdown()

def main():
    """Main entry point"""
    try:
        alert_manager = AlertManager()
        
        # Start watchdog notification thread
        def watchdog_worker():
            while True:
                try:
                    systemd.daemon.notify('WATCHDOG=1')
                    time.sleep(5)
                except Exception as e:
                    alert_manager.logger.error(f"Failed to send watchdog notification: {e}")
                    time.sleep(5)
        
        watchdog_thread = threading.Thread(target=watchdog_worker, daemon=True)
        watchdog_thread.start()
        
        alert_manager.run()
        
    except Exception as e:
        print(f"Alert Manager crashed: {e}")

if __name__ == "__main__":
    main()