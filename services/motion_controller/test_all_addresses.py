#!/usr/bin/env python3
"""
Test all possible PCA9685 I2C addresses
"""

import time
from adafruit_servokit import ServoKit
import board
import busio

def test_address(address):
    try:
        i2c = busio.I2C(board.SCL, board.SDA)
        kit = ServoKit(channels=16, i2c=i2c, address=address)

        # Try to set a servo position
        kit.servo[0].set_pulse_width_range(500, 2400)
        kit.servo[0].actuation_range = 180
        kit.servo[0].angle = 90

        print(f"✓ SUCCESS: PCA9685 found at address 0x{address:02X}")
        return True

    except Exception as e:
        print(f"✗ FAILED: Address 0x{address:02X} - {e}")
        return False

def main():
    print("Testing all possible PCA9685 addresses...")
    print("========================================")

    # Test common PCA9685 addresses
    addresses = [0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47,
                 0x60, 0x61, 0x62, 0x63, 0x64, 0x65, 0x66, 0x67,
                 0x70, 0x71, 0x72, 0x73, 0x74, 0x75, 0x76, 0x77,
                 0x78, 0x79, 0x7A, 0x7B, 0x7C, 0x7D, 0x7E, 0x7F]

    found = False
    for addr in addresses:
        if test_address(addr):
            found = True

    if not found:
        print("\n❌ No PCA9685 found at any address!")
        print("Possible issues:")
        print("- PCA9685 board damaged by reverse polarity")
        print("- I2C wiring incorrect (SDA/SCL swapped or loose)")
        print("- PCA9685 not powered properly")
        print("- Board not connected to Raspberry Pi I2C bus 1")

if __name__ == "__main__":
    main()