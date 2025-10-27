#!/usr/bin/env python3
"""
Test motion controller tracking by simulating face detection data
"""

import time
import redis
import json
import os

def main():
    print("Testing Motion Controller Face Tracking")
    print("======================================")

    # Connect to Redis with authentication
    redis_password = os.getenv('REDIS_PASSWORD', '13MyFokKaren79.')
    r = redis.Redis(host='localhost', port=6379, db=0, password=redis_password, decode_responses=True)

    try:
        # Test Redis connection
        r.ping()
        print("✓ Connected to Redis")
    except Exception as e:
        print(f"✗ Failed to connect to Redis: {e}")
        return

    # Simulate face tracking data
    tracking_scenarios = [
        # (face_offset_x, face_offset_y, description)
        (0.0, 0.0, "Face centered - no movement expected"),
        (0.3, 0.0, "Face right - pan should move right"),
        (-0.3, 0.0, "Face left - pan should move left"),
        (0.0, 0.3, "Face down - tilt should move down"),
        (0.0, -0.3, "Face up - tilt should move up"),
        (0.2, 0.2, "Face bottom-right - both should move"),
        (-0.2, -0.2, "Face top-left - both should move"),
        (0.0, 0.0, "Face centered again - return to center"),
    ]

    for offset_x, offset_y, description in tracking_scenarios:
        print(f"\n{description}")
        print(f"Publishing: face_offset_x={offset_x}, face_offset_y={offset_y}")

        # Publish vision data to Redis (convert all values to strings)
        vision_data = {
            "timestamp": str(time.time()),
            "face_detected": "true",  # Key: motion controller only tracks when this is True
            "face_offset_x": str(offset_x),
            "face_offset_y": str(offset_y),
            "avg_ear": "0.25",
            "eyes_closed": "false",
            "closure_duration": "0.0",
            "microsleep_count": "0",
            "blink_rate_per_minute": "20.0",
            "service": "test_tracking"
        }

        # Publish to the same hash the vision processor uses
        r.hset("cognicore:data:vision", mapping=vision_data)

        print("Data published - servos should move now...")
        time.sleep(3)  # Wait for motion controller to process and move

    print("\n✓ Tracking test complete!")
    print("Check if the servos moved during the test.")

if __name__ == "__main__":
    main()