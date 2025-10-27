#!/usr/bin/env python3
"""
Test improved motion controller tracking with feedback control and adaptive speed
"""

import time
import redis
import os

def test_improved_tracking():
    print("Testing Improved Motion Controller Tracking")
    print("==========================================")

    # Connect to Redis
    redis_password = os.getenv('REDIS_PASSWORD', '13MyFokKaren79.')
    r = redis.Redis(host='localhost', port=6379, db=0, password=redis_password, decode_responses=True)

    try:
        r.ping()
        print("✓ Connected to Redis")
    except Exception as e:
        print(f"✗ Failed to connect to Redis: {e}")
        return

    # Test scenarios demonstrating improved tracking
    test_scenarios = [
        # (offset_x, offset_y, duration, description)
        (0.0, 0.0, 2, "1. CENTER - Initialize at center"),
        (0.5, 0.0, 8, "2. LARGE ERROR - Face far right (should move fast then slow down)"),
        (0.0, 0.0, 6, "3. RETURN TO CENTER - Should converge smoothly"),
        (0.1, 0.0, 6, "4. SMALL ERROR - Face slightly right (should move slowly)"),
        (0.0, 0.0, 4, "5. FINE CENTERING - Should achieve precise center"),
        (-0.3, 0.3, 8, "6. DIAGONAL MOVEMENT - Bottom-left (adaptive speed)"),
        (0.0, 0.0, 8, "7. FINAL CENTER - Watch convergence detection"),
        (0.0, -0.4, 6, "8. VERTICAL TEST - Face up (should tilt up correctly)"),
        (0.0, 0.0, 6, "9. FINAL CONVERGENCE - Return to perfect center")
    ]

    print("\nStarting tracking test sequence...")
    print("Watch for:")
    print("- Fast movement for large errors, slow for small errors")
    print("- Smooth convergence to center without overshoot")
    print("- Stable positioning when face is centered")
    print("- Correct directions (left/right/up/down)")

    for offset_x, offset_y, duration, description in test_scenarios:
        print(f"\n{description}")
        print(f"Target: offset_x={offset_x:+.1f}, offset_y={offset_y:+.1f}")
        print(f"Duration: {duration}s")

        start_time = time.time()
        while time.time() - start_time < duration:
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
                "service": "improved_tracking_test"
            }

            r.hset("cognicore:data:vision", mapping=vision_data)
            time.sleep(0.1)  # 10Hz update rate

        # Check motion status
        try:
            motion_status = r.hgetall("cognicore:data:motion")
            if motion_status:
                is_converged = motion_status.get('is_converged', 'false') == 'true'
                tracking_error = float(motion_status.get('tracking_error', 0.0))
                pan_angle = float(motion_status.get('pan_angle', 90.0))
                tilt_angle = float(motion_status.get('tilt_angle', 90.0))

                print(f"Status: pan={pan_angle:.1f}°, tilt={tilt_angle:.1f}°, "
                      f"error={tracking_error:.3f}, converged={is_converged}")
        except:
            pass

    print("\n" + "="*50)
    print("✓ Improved tracking test completed!")
    print("\nExpected improvements:")
    print("- Adaptive speed: Fast for large errors, slow for small errors")
    print("- Smooth convergence: No overshoot or oscillation")
    print("- Precise centering: Stops when face is properly centered")
    print("- Feedback control: Continuously adjusts based on error")
    print("- Stable tracking: Minimal jitter when centered")

if __name__ == "__main__":
    test_improved_tracking()