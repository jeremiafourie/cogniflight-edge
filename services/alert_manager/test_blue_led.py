#!/usr/bin/env python3
"""Test blue LED channel directly"""

import time
from gpiozero import LED

# Test GPIO 22 (Blue channel)
print("Testing BLUE LED (GPIO 22)...")
print("The LED should turn BLUE solid for 5 seconds")

blue_channel = LED(22)

try:
    print("Turning BLUE ON...")
    blue_channel.on()
    time.sleep(5)

    print("Turning BLUE OFF...")
    blue_channel.off()
    print("Test complete!")

except KeyboardInterrupt:
    print("\nTest interrupted")
    blue_channel.off()
except Exception as e:
    print(f"Error: {e}")
    blue_channel.off()
