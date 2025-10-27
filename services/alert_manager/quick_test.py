#!/usr/bin/env python3
"""Quick test to verify state changes are published correctly"""

import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from CogniCore import CogniCore, SystemState

def main():
    core = CogniCore("quick_test")
    logger = core.get_logger("quick_test")

    print("\n=== Testing State Change Publication ===\n")

    # Test 1: Set to monitoring_active
    print("Setting state to MONITORING_ACTIVE...")
    core.set_system_state(
        SystemState.MONITORING_ACTIVE,
        "Test: Monitoring Active",
        pilot_id="TEST",
        data={"test": True}
    )
    print("✓ Published MONITORING_ACTIVE")
    print("  Wait 5 seconds and observe LED (should be GREEN solid)")
    time.sleep(5)

    # Test 2: Set to alert_mild
    print("\nSetting state to ALERT_MILD...")
    core.set_system_state(
        SystemState.ALERT_MILD,
        "Test: Mild Alert",
        pilot_id="TEST",
        data={"test": True}
    )
    print("✓ Published ALERT_MILD")
    print("  Wait 5 seconds and observe LED (should be BLUE breathing)")
    time.sleep(5)

    # Test 3: Set to alert_severe
    print("\nSetting state to ALERT_SEVERE...")
    core.set_system_state(
        SystemState.ALERT_SEVERE,
        "Test: Severe Alert",
        pilot_id="TEST",
        data={"test": True}
    )
    print("✓ Published ALERT_SEVERE")
    print("  Wait 5 seconds and observe LED (should be RED/MAGENTA rapid)")
    time.sleep(5)

    # Test 4: Return to monitoring_active
    print("\nReturning to MONITORING_ACTIVE...")
    core.set_system_state(
        SystemState.MONITORING_ACTIVE,
        "Test Complete",
        pilot_id="TEST",
        data={"test": True}
    )
    print("✓ Published MONITORING_ACTIVE")
    print("  LED should return to GREEN solid")
    time.sleep(2)

    print("\n=== Test Complete ===\n")
    core.shutdown()

if __name__ == "__main__":
    main()
