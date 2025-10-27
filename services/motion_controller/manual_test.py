#!/usr/bin/env python3
"""
Manual servo positioning test
"""

import time
from adafruit_servokit import ServoKit
import board
import busio

def main():
    print("Manual Servo Test - Specific Positions")
    print("=====================================")

    try:
        # Initialize
        i2c = busio.I2C(board.SCL, board.SDA)
        kit = ServoKit(channels=16, i2c=i2c, address=0x7F)

        # Configure servos
        kit.servo[0].set_pulse_width_range(500, 2400)
        kit.servo[1].set_pulse_width_range(500, 2400)
        kit.servo[0].actuation_range = 180
        kit.servo[1].actuation_range = 180

        print("✓ PCA9685 initialized")

        positions = [
            (90, 90, "CENTER - both servos at 90°"),
            (45, 90, "PAN LEFT - pan at 45°, tilt at 90°"),
            (135, 90, "PAN RIGHT - pan at 135°, tilt at 90°"),
            (90, 45, "TILT UP - pan at 90°, tilt at 45°"),
            (90, 135, "TILT DOWN - pan at 90°, tilt at 135°"),
            (90, 90, "CENTER AGAIN - back to 90°/90°")
        ]

        for pan, tilt, description in positions:
            print(f"\n{description}")
            print(f"Setting pan={pan}°, tilt={tilt}°")
            kit.servo[0].angle = pan
            kit.servo[1].angle = tilt
            input("Press Enter when you've verified this position...")

        print("\n✓ Manual test complete")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()