#!/usr/bin/env python3
"""
Alert Manager State Testing Script
Allows manual testing of each alert state by simulating state changes via CogniCore
"""

import sys
import time
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from CogniCore import CogniCore, SystemState

SERVICE_NAME = "state_tester"

class StateTester:
    """Test utility to trigger different alert states"""

    def __init__(self):
        self.core = CogniCore(SERVICE_NAME)
        self.logger = self.core.get_logger(SERVICE_NAME)
        self.logger.info("State Tester initialized")

    def trigger_state(self, state: str, message: str, duration: int = 10):
        """Trigger a specific state for testing"""
        try:
            self.logger.info(f"Triggering state: {state} - {message} (duration: {duration}s)")

            # Map string state names to SystemState enums
            state_mapping = {
                "scanning": SystemState.SCANNING,
                "monitoring_active": SystemState.MONITORING_ACTIVE,
                "alert_mild": SystemState.ALERT_MILD,
                "alert_moderate": SystemState.ALERT_MODERATE,
                "alert_severe": SystemState.ALERT_SEVERE,
                "intruder_detected": SystemState.INTRUDER_DETECTED,
                "alcohol_detected": SystemState.ALCOHOL_DETECTED,
                "system_error": SystemState.SYSTEM_ERROR,
                "system_crashed": SystemState.SYSTEM_CRASHED
            }

            # Get the SystemState enum for this state
            state_enum = state_mapping.get(state, SystemState.MONITORING_ACTIVE)

            # Set the system state
            self.core.set_system_state(
                state_enum,
                message,
                pilot_id="TEST_PILOT",
                data={"test_mode": True, "duration": duration}
            )

            print(f"\n✓ State '{state}' activated")
            print(f"  Message: {message}")
            print(f"  Duration: {duration} seconds")
            print(f"  Observe the RGB LED, buzzer, and vibrator behavior...")

            # Wait for the specified duration
            for remaining in range(duration, 0, -1):
                print(f"  Time remaining: {remaining}s", end='\r')
                time.sleep(1)

            print("\n")

        except Exception as e:
            self.logger.error(f"Error triggering state {state}: {e}")
            print(f"✗ Error: {e}")

    def return_to_monitoring(self):
        """Return to normal monitoring state"""
        self.trigger_state(
            state="monitoring_active",
            message="Test complete - returning to monitoring",
            duration=3
        )

    def run_interactive_test(self):
        """Interactive menu for testing states"""
        states_menu = {
            '1': ('scanning', 'Scanning for activity', 15),
            '2': ('monitoring_active', 'Monitoring Active - Normal Operation', 10),
            '3': ('alert_mild', 'MILD fatigue detected - Early Warning', 25),
            '4': ('alert_moderate', 'MODERATE fatigue detected - Take Action', 20),
            '5': ('alert_severe', 'SEVERE fatigue detected - CRITICAL', 15),
            '6': ('intruder_detected', 'Intruder Detected - Security Alert', 15),
            '7': ('alcohol_detected', 'Alcohol Detected - Safety Alert', 15),
            '8': ('system_error', 'System Error - Check Logs', 10),
            '9': ('system_crashed', 'System Crashed - Critical Failure', 10),
        }

        print("\n" + "="*70)
        print("  ALERT MANAGER STATE TESTING UTILITY")
        print("="*70)
        print("\nThis tool allows you to test each alert state individually.")
        print("Observe the RGB LED, buzzer, and vibrator for each state.\n")

        while True:
            print("\nAvailable States:")
            print("-" * 70)
            print("  1. Scanning (Yellow toggle, periodic buzzer)")
            print("  2. Monitoring Active (Green solid)")
            print("  3. Alert Mild (Blue breathing, triple beeps every 20s)")
            print("  4. Alert Moderate (Yellow strobe, double beeps/pulses every 12s)")
            print("  5. Alert Severe (Red/Magenta rapid, continuous beeps/vibration)")
            print("  6. Intruder Detected (Red/Blue siren)")
            print("  7. Alcohol Detected (Red/Orange siren)")
            print("  8. System Error (Red toggle, short beeps)")
            print("  9. System Crashed (Red solid, continuous buzzer)")
            print("-" * 70)
            print("  A. Auto-test all fatigue states (3, 4, 5)")
            print("  Q. Quit")
            print("-" * 70)

            choice = input("\nSelect state to test (1-9, A, Q): ").strip().upper()

            if choice == 'Q':
                print("\nReturning to monitoring state before exit...")
                self.return_to_monitoring()
                print("✓ Test session complete. Goodbye!")
                break

            elif choice == 'A':
                print("\n" + "="*70)
                print("  AUTO-TEST: FATIGUE ALERT STATES")
                print("="*70)
                print("\nThis will test all three fatigue levels in sequence.")
                print("Observe the distinct patterns for each level:\n")

                input("Press ENTER to start auto-test...")

                # Test Mild
                print("\n" + "-"*70)
                print("TEST 1/3: ALERT_MILD")
                print("-"*70)
                print("Expected: Slow blue breathing, triple beeps every 20s")
                self.trigger_state('alert_mild', 'MILD fatigue - Early Warning', 25)

                # Test Moderate
                print("\n" + "-"*70)
                print("TEST 2/3: ALERT_MODERATE")
                print("-"*70)
                print("Expected: Yellow strobe with pause, double beeps/pulses every 12s")
                self.trigger_state('alert_moderate', 'MODERATE fatigue - Take Action', 20)

                # Test Severe
                print("\n" + "-"*70)
                print("TEST 3/3: ALERT_SEVERE")
                print("-"*70)
                print("Expected: Rapid red/magenta alternation, continuous beeps/vibration")
                self.trigger_state('alert_severe', 'SEVERE fatigue - CRITICAL', 15)

                print("\n" + "="*70)
                print("  AUTO-TEST COMPLETE")
                print("="*70)
                self.return_to_monitoring()

            elif choice in states_menu:
                state, message, duration = states_menu[choice]
                self.trigger_state(state, message, duration)
                self.return_to_monitoring()

            else:
                print("\n✗ Invalid choice. Please select 1-9, A, or Q.")

    def shutdown(self):
        """Clean shutdown"""
        self.logger.info("State Tester shutting down")
        self.core.shutdown()


def main():
    """Main entry point"""
    try:
        tester = StateTester()
        tester.run_interactive_test()
        tester.shutdown()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Cleaning up...")
        try:
            tester.return_to_monitoring()
            tester.shutdown()
        except:
            pass
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
