import os
import sys
import time
import logging
import threading
from pathlib import Path
from gpiozero import LED, Buzzer, OutputDevice
from threading import Timer
import systemd.daemon

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from CogniCore import CogniCore, SystemState
from CogniCore import config

# Configuration constants

# LCD imports
try:
    from RPLCD.i2c import CharLCD
    LCD_AVAILABLE = True
except ImportError:
    LCD_AVAILABLE = False

# GPIO imports
try:
    from gpiozero import LED, Buzzer, OutputDevice
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

SERVICE_NAME = "alert_manager"

class AlertManager:
    """Alert Manager - Listens to system state changes, displays on LCD and controls GPIO hardware"""
    
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
        
        # Initialize LCD
        self.lcd = None
        if LCD_AVAILABLE:
            try:
                # Standard I2C LCD configuration for 16x2 display
                self.lcd = CharLCD(i2c_expander='PCF8574', address=0x27, port=1, 
                                 cols=16, rows=2, dotsize=8)
                self.lcd.clear()
                self.lcd.write_string("CogniFlight Edge\nInitializing...")
                self.logger.info("LCD initialized successfully")
            except Exception as e:
                self.logger.warning(f"LCD initialization failed: {e}")
                self.lcd = None
        else:
            self.logger.warning("RPLCD not available, LCD functionality disabled")
        
        # Subscribe ONLY to state changes
        self.core.subscribe_to_state_changes(self.on_state_change)
        
        # Notify systemd that service is ready
        systemd.daemon.notify('READY=1')
        self.logger.info("Notified systemd that service is ready")
        
        self.logger.info("Alert Manager initialized - listening to state changes and controlling GPIO")
    
    def initialize_gpio(self):
        """Initialize GPIO hardware components"""
        if not GPIO_AVAILABLE:
            self.logger.warning("GPIO Zero not available, GPIO functionality disabled")
            return
        
        try:
            # Initialize LEDs
            self.green_led = LED(17)    # GPIO 17: Green LED (Active)
            self.blue_led = LED(27)     # GPIO 27: Blue LED (Mild Fatigue)
            self.yellow_led = LED(22)   # GPIO 22: Yellow LED (Moderate Fatigue)
            self.red_led = LED(23)      # GPIO 23: Red LED (Severe Fatigue)
            
            # Initialize buzzer (inverted logic) and vibrator
            self.buzzer = OutputDevice(24, active_high=False)  # GPIO 24: Buzzer (inverted)
            self.vibrator = OutputDevice(25)  # GPIO 25: Vibrator Motor
            
            # Turn off all devices initially
            self.turn_off_all_devices()
            self.gpio_initialized = True
            self.logger.info("GPIO hardware initialized successfully")
            
        except Exception as e:
            self.logger.error(f"GPIO initialization failed: {e}")
            self.gpio_initialized = False
    
    def turn_off_all_devices(self):
        """Turn off all GPIO devices"""
        if not self.gpio_initialized:
            return
        
        try:
            self.green_led.off()
            self.blue_led.off()
            self.yellow_led.off()
            self.red_led.off()
            self.buzzer.off()  # Inverted buzzer - off() actually turns it off
            self.vibrator.off()
            self.logger.debug("All GPIO devices turned off")
        except Exception as e:
            self.logger.error(f"Error turning off devices: {e}")
    
    def stop_all_gpio_effects(self):
        """Stop all running GPIO effects"""
        self.stop_gpio_effects.set()
        # Wait for threads to finish
        for thread in self.gpio_threads:
            if thread.is_alive():
                thread.join(timeout=1.0)
        self.gpio_threads.clear()
        self.stop_gpio_effects.clear()
        self.turn_off_all_devices()
    
    def start_gpio_effect(self, effect_func, *args):
        """Start a GPIO effect in a separate thread"""
        self.stop_all_gpio_effects()
        thread = threading.Thread(target=effect_func, args=args, daemon=True)
        thread.start()
        self.gpio_threads.append(thread)
    
    def scanning_effect(self):
        """SCANNING: Toggle yellow LED continuously with periodic buzzer every 30 seconds"""
        if not self.gpio_initialized:
            return
        
        # Turn off all other LEDs at start
        try:
            self.green_led.off()
            self.blue_led.off()
            self.red_led.off()
            self.buzzer.off()  # Ensure buzzer is off initially
            self.vibrator.off()
        except Exception as e:
            self.logger.error(f"Error initializing scanning effect: {e}")
            return
        
        last_buzzer_time = 0
        
        while not self.stop_gpio_effects.is_set():
            try:
                # Toggle yellow LED
                self.yellow_led.on()
                time.sleep(0.5)
                
                if self.stop_gpio_effects.is_set():
                    break
                    
                self.yellow_led.off()
                time.sleep(0.5)
                
                # Buzzer beep every 30 seconds
                current_time = time.time()
                if current_time - last_buzzer_time >= 30:
                    self.buzzer.on()
                    time.sleep(0.1)
                    self.buzzer.off()
                    last_buzzer_time = current_time
                
            except Exception as e:
                self.logger.error(f"Error in scanning effect: {e}")
                break
    
    def intruder_detected_effect(self):
        """INTRUDER_DETECTED: Alternate red/blue LEDs, toggle buzzer and vibrator (siren-like)"""
        if not self.gpio_initialized:
            return
        
        while not self.stop_gpio_effects.is_set():
            try:
                # Red LED + buzzer + vibrator on
                self.red_led.on()
                self.blue_led.off()
                self.buzzer.on()
                self.vibrator.on()
                time.sleep(0.5)
                
                if self.stop_gpio_effects.is_set():
                    break
                
                # Blue LED + buzzer + vibrator off
                self.red_led.off()
                self.blue_led.on()
                self.buzzer.off()
                self.vibrator.off()
                time.sleep(0.5)
                
            except Exception as e:
                self.logger.error(f"Error in intruder detected effect: {e}")
                break
    
    def monitoring_active_effect(self):
        """MONITORING_ACTIVE: Keep green LED on"""
        if not self.gpio_initialized:
            return
        
        try:
            self.turn_off_all_devices()
            self.green_led.on()
        except Exception as e:
            self.logger.error(f"Error in monitoring active effect: {e}")
    
    def system_crashed_effect(self):
        """SYSTEM_CRASHED: Red LED and buzzer continuously on"""
        if not self.gpio_initialized:
            return
        
        try:
            self.turn_off_all_devices()
            self.red_led.on()
            self.buzzer.on()
        except Exception as e:
            self.logger.error(f"Error in system crashed effect: {e}")
    
    def system_error_effect(self):
        """SYSTEM_ERROR: Toggle red LED and short buzzer beeps"""
        if not self.gpio_initialized:
            return
        
        while not self.stop_gpio_effects.is_set():
            try:
                # Red LED and buzzer on
                self.red_led.on()
                self.buzzer.on()
                time.sleep(0.1)  # Short beep
                self.buzzer.off()
                time.sleep(0.4)  # LED stays on for total 0.5s
                
                if self.stop_gpio_effects.is_set():
                    break
                
                # Red LED off
                self.red_led.off()
                time.sleep(0.5)
                
            except Exception as e:
                self.logger.error(f"Error in system error effect: {e}")
                break
    
    def alert_mild_effect(self):
        """ALERT_MILD: Toggle green LED, blue LED on, long buzzer beep every 15s"""
        if not self.gpio_initialized:
            return
        
        last_buzzer_time = 0
        
        while not self.stop_gpio_effects.is_set():
            try:
                # Blue LED always on
                self.blue_led.on()
                
                # Toggle green LED
                self.green_led.on()
                time.sleep(0.5)
                
                if self.stop_gpio_effects.is_set():
                    break
                
                self.green_led.off()
                time.sleep(0.5)
                
                # Long buzzer beep every 15 seconds
                current_time = time.time()
                if current_time - last_buzzer_time >= 15:
                    self.buzzer.on()
                    time.sleep(1.0)  # Long beep
                    self.buzzer.off()
                    last_buzzer_time = current_time
                
            except Exception as e:
                self.logger.error(f"Error in alert mild effect: {e}")
                break
    
    def alert_severe_effect(self):
        """ALERT_SEVERE: Toggle green LED, red LED on, toggle vibrator and buzzer every 15s"""
        if not self.gpio_initialized:
            return
        
        last_toggle_time = 0
        vibrator_state = False
        
        while not self.stop_gpio_effects.is_set():
            try:
                # Red LED always on
                self.red_led.on()
                
                # Toggle green LED
                self.green_led.on()
                time.sleep(0.5)
                
                if self.stop_gpio_effects.is_set():
                    break
                
                self.green_led.off()
                time.sleep(0.5)
                
                # Toggle vibrator and buzzer every 15 seconds
                current_time = time.time()
                if current_time - last_toggle_time >= 15:
                    vibrator_state = not vibrator_state
                    if vibrator_state:
                        self.vibrator.on()
                        self.buzzer.on()
                    else:
                        self.vibrator.off()
                        self.buzzer.off()
                    last_toggle_time = current_time
                
            except Exception as e:
                self.logger.error(f"Error in alert severe effect: {e}")
                break
    
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
                self.start_gpio_effect(self.alert_mild_effect)  # Use same as mild for now
            elif state == "alert_severe":
                self.start_gpio_effect(self.alert_severe_effect)
            else:
                self.logger.warning(f"Unknown state for GPIO control: {state}")
                self.stop_all_gpio_effects()
                
            self.logger.info(f"GPIO effects activated successfully for state: {state}")
            
        except Exception as e:
            self.logger.error(f"Failed to activate GPIO effects for state {state}: {e}")
    
    def wrap_text_for_lcd(self, text: str, line_width: int = 16) -> list[str]:
        """Wrap text for LCD display with newline support"""
        lines = []
        text_lines = text.split('\n')
        
        for line in text_lines:
            if len(line) <= line_width:
                lines.append(line)
            else:
                # Simple word wrap
                words = line.split(' ')
                current_line = ""
                
                for word in words:
                    test_line = f"{current_line} {word}".strip()
                    if len(test_line) <= line_width:
                        current_line = test_line
                    else:
                        if current_line:
                            lines.append(current_line)
                        current_line = word
                
                if current_line:
                    lines.append(current_line)
        
        return lines
    
    def display_on_lcd(self, message: str):
        """Display message on LCD hardware"""
        if not self.lcd:
            return
        
        try:
            self.lcd.clear()
            
            # Wrap text for 16x2 display
            wrapped_lines = self.wrap_text_for_lcd(message, 16)
            
            # Display up to 2 lines
            for i, line in enumerate(wrapped_lines[:2]):
                self.lcd.cursor_pos = (i, 0)
                self.lcd.write_string(line)
            
            self.logger.debug(f"LCD display updated: {message.replace(chr(10), ' | ')}")
            
        except Exception as e:
            self.logger.error(f"LCD display error: {e}")
    
    def on_state_change(self, state_data):
        """Handle system state changes - update LCD and control GPIO hardware"""
        try:
            state = state_data.get("state", "unknown")
            message = state_data.get("message", "")
            pilot_id = state_data.get("pilot_id")
            timestamp = state_data.get("timestamp", time.time())
            
            # Only update if state has actually changed (ignore message changes for same state)
            # This prevents spam from rapid monitoring_active updates
            if state == self.current_state:
                # For monitoring_active state, only update LCD if message significantly different
                if state == "monitoring_active":
                    # Skip frequent monitoring updates - they cause LCD spam
                    self.logger.debug(f"Skipping frequent monitoring update: {message}")
                    return
                # For other states, check if message actually changed
                elif message == self.current_message:
                    self.logger.debug(f"State unchanged: {state} - {message}")
                    return
            
            # Update tracking variables
            self.current_state = state
            self.current_message = message
            
            self.logger.info(f"State change: {state} -> {message}")
            
            # Control GPIO hardware for the new state (always trigger on state change)
            self.control_gpio_for_state(state)
            
            # Display the message that came with the state
            if message:
                self.display_on_lcd(message)
            else:
                # Fallback if no message provided with state
                self.display_on_lcd(f"State: {state}")
            
            # Log state change
            self.logger.info(f"LCD and GPIO updated for state: {state}")
            
        except Exception as e:
            self.logger.error(f"Error handling state change: {e}")
    
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
            if self.lcd:
                self.lcd.clear()
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