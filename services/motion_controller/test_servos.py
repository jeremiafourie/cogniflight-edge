#!/usr/bin/env python3
"""
Test script for PCA9685 servo control

This script tests the servo connections and movement without requiring
the full CogniFlight system to be running.

Usage:
    python3 test_servos.py [--address 0x40|0x7F]
"""

import time
import sys
import argparse
from adafruit_servokit import ServoKit
import board
import busio

def test_servo_sweep(kit, channel, name):
    """Test a single servo with a sweep pattern"""
    print(f"\n=== Testing {name} on channel {channel} ===")
    
    # Set servo properties
    kit.servo[channel].set_pulse_width_range(500, 2400)  # SG90 typical range
    kit.servo[channel].actuation_range = 180
    
    # Center
    print(f"Centering {name}...")
    kit.servo[channel].angle = 90
    time.sleep(1)
    
    # Sweep test
    print(f"Sweeping {name} (0° -> 180° -> 0°)...")
    
    # Slow sweep from 0 to 180
    for angle in range(0, 181, 10):
        kit.servo[channel].angle = angle
        print(f"  {angle}°", end='\r')
        time.sleep(0.1)
    
    time.sleep(0.5)
    
    # Sweep back from 180 to 0
    for angle in range(180, -1, -10):
        kit.servo[channel].angle = angle
        print(f"  {angle}°", end='\r')
        time.sleep(0.1)
    
    # Return to center
    print(f"\n{name} returning to center...")
    kit.servo[channel].angle = 90
    time.sleep(1)
    
    print(f"✓ {name} test complete")

def test_coordinated_movement(kit):
    """Test coordinated movement of both servos"""
    print("\n=== Testing Coordinated Movement ===")
    
    # Center both
    print("Centering both servos...")
    kit.servo[0].angle = 90
    kit.servo[1].angle = 90
    time.sleep(1)
    
    # Box pattern
    print("Drawing box pattern...")
    movements = [
        (45, 45, "Top-left"),
        (45, 135, "Bottom-left"),
        (135, 135, "Bottom-right"),
        (135, 45, "Top-right"),
        (90, 90, "Center")
    ]
    
    for pan, tilt, position in movements:
        print(f"  Moving to {position} (pan={pan}°, tilt={tilt}°)")
        kit.servo[0].angle = pan
        kit.servo[1].angle = tilt
        time.sleep(1)
    
    print("✓ Coordinated movement test complete")

def main():
    parser = argparse.ArgumentParser(description='Test PCA9685 servo control')
    parser.add_argument('--address', type=str, default='0x40',
                        help='I2C address (0x40 or 0x7F)')
    parser.add_argument('--bus', type=int, default=1,
                        help='I2C bus number (default: 1)')
    args = parser.parse_args()
    
    # Parse address
    if args.address.startswith('0x'):
        address = int(args.address, 16)
    else:
        address = int(args.address)
    
    print(f"PCA9685 Servo Test Script")
    print(f"========================")
    print(f"I2C Bus: {args.bus}")
    print(f"I2C Address: 0x{address:02X}")
    
    try:
        # Initialize I2C and ServoKit
        print("\nInitializing PCA9685...")
        i2c = busio.I2C(board.SCL, board.SDA)
        kit = ServoKit(channels=16, i2c=i2c, address=address)
        print("✓ PCA9685 initialized successfully")
        
        # Test each servo
        test_servo_sweep(kit, 0, "Pan Servo (Horizontal)")
        test_servo_sweep(kit, 1, "Tilt Servo (Vertical)")
        
        # Test coordinated movement
        test_coordinated_movement(kit)
        
        # Final center
        print("\n=== Test Complete ===")
        print("Centering servos...")
        kit.servo[0].angle = 90
        kit.servo[1].angle = 90
        
        print("\n✓ All tests passed successfully!")
        print("\nServo control is working correctly.")
        print("You can now start the motion_controller service.")
        
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("\nTroubleshooting:")
        print("1. Check I2C is enabled: sudo raspi-config")
        print("2. Verify connections:")
        print("   - SDA: Pin 3 (GPIO 2)")
        print("   - SCL: Pin 5 (GPIO 3)")
        print("   - VCC: Pin 4 (5V)")
        print("   - GND: Pin 6")
        print("3. Check I2C devices: sudo i2cdetect -y 1")
        print("4. Ensure external 5V power is connected to V+ on PCA9685")
        sys.exit(1)

if __name__ == "__main__":
    main()