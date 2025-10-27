#!/usr/bin/env python3
"""
Test servo direction mapping to verify left/right/up/down movements
"""

import time
import redis
import os

def test_direction_mapping():
    print("Testing Servo Direction Mapping")
    print("===============================")

    # Connect to Redis
    redis_password = os.getenv('REDIS_PASSWORD', '13MyFokKaren79.')
    r = redis.Redis(host='localhost', port=6379, db=0, password=redis_password, decode_responses=True)

    try:
        r.ping()
        print("✓ Connected to Redis")
    except Exception as e:
        print(f"✗ Failed to connect to Redis: {e}")
        return

    # Test scenarios with clear expected movements
    test_cases = [
        # (offset_x, offset_y, expected_movement)
        (0.0, 0.0, "CENTER - no movement"),
        (0.5, 0.0, "Face is RIGHT - servo should turn RIGHT to follow"),
        (-0.5, 0.0, "Face is LEFT - servo should turn LEFT to follow"),
        (0.0, 0.5, "Face is DOWN - servo should tilt DOWN to follow"),
        (0.0, -0.5, "Face is UP - servo should tilt UP to follow"),
        (0.0, 0.0, "Return to CENTER")
    ]

    for offset_x, offset_y, description in test_cases:
        print(f"\n{description}")
        print(f"Publishing: face_offset_x={offset_x}, face_offset_y={offset_y}")

        vision_data = {
            "timestamp": str(time.time()),
            "face_detected": "true",
            "face_offset_x": str(offset_x),
            "face_offset_y": str(offset_y),
            "avg_ear": "0.25",
            "eyes_closed": "false",
            "closure_duration": "0.0",
            "microsleep_count": "0",
            "blink_rate_per_minute": "20.0",
            "service": "direction_test"
        }

        r.hset("cognicore:data:vision", mapping=vision_data)
        print("⏱️  Watch the servos and verify the movement matches the description...")
        time.sleep(4)  # Give time to observe movement

    print("\n✓ Direction test complete!")
    print("\nDid the movements match the descriptions?")
    print("- Face RIGHT → Servo turns RIGHT")
    print("- Face LEFT → Servo turns LEFT")
    print("- Face DOWN → Servo tilts DOWN")
    print("- Face UP → Servo tilts UP")

if __name__ == "__main__":
    test_direction_mapping()