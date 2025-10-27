#!/usr/bin/env python3
"""
Simple servo movement test - moves to obvious positions with delays
"""

import time
from adafruit_servokit import ServoKit
import board
import busio

def main():
    print("Simple Servo Movement Test")
    print("==========================")

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

        # Move to center
        print("1. Moving to CENTER (90°, 90°)")
        kit.servo[0].angle = 90
        kit.servo[1].angle = 90
        time.sleep(2)

        # Move pan left
        print("2. Moving PAN LEFT (30°, 90°)")
        kit.servo[0].angle = 30
        kit.servo[1].angle = 90
        time.sleep(2)

        # Move pan right
        print("3. Moving PAN RIGHT (150°, 90°)")
        kit.servo[0].angle = 150
        kit.servo[1].angle = 90
        time.sleep(2)

        # Back to center
        print("4. Back to CENTER (90°, 90°)")
        kit.servo[0].angle = 90
        kit.servo[1].angle = 90
        time.sleep(2)

        # Move tilt up
        print("5. Moving TILT UP (90°, 30°)")
        kit.servo[0].angle = 90
        kit.servo[1].angle = 30
        time.sleep(2)

        # Move tilt down
        print("6. Moving TILT DOWN (90°, 150°)")
        kit.servo[0].angle = 90
        kit.servo[1].angle = 150
        time.sleep(2)

        # Final center
        print("7. Final CENTER position (90°, 90°)")
        kit.servo[0].angle = 90
        kit.servo[1].angle = 90
        time.sleep(1)

        print("\n✓ Movement test complete!")
        print("If you saw no movement, check:")
        print("- External 5V power connected to PCA9685 V+ terminal")
        print("- Servo signal wires connected to channels 0 and 1")
        print("- Servo power wires connected to PCA9685 servo power")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()