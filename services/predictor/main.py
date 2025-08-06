import os
import json
import time
import sys
import logging
from pathlib import Path
from collections import deque
import systemd.daemon

# Add project root to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from CogniCore import CogniCore, SystemState
SERVICE_NAME = "predictor"

# Size of the sliding window (N = 2 samples for faster response)
WINDOW_SIZE = 2

# Default threshold values - can be personalized per pilot
DEFAULT_THRESHOLD_MILD   = 0.3
DEFAULT_THRESHOLD_MOD    = 0.6
DEFAULT_THRESHOLD_SEVERE = 0.8
DEFAULT_HYSTERESIS       = 0.05  # small gap to prevent flapping

def calculate_fusion_score(vision_data, hr_data):
    """
    LEAN fusion score calculation using only the highest-value vision indicators.
    Optimized for speed and accuracy with minimal overhead.
    """
    if not vision_data:
        return 0.0
    
    # Extract lean vision measurements (only the most valuable)
    avg_ear = vision_data.get("avg_ear", 0.25)
    eyes_closed = vision_data.get("eyes_closed", False) 
    closure_duration = vision_data.get("closure_duration", 0.0)
    microsleep_count = vision_data.get("microsleep_count", 0)
    blink_rate = vision_data.get("blink_rate_per_minute", 15.0)
    
    # EAR-based fatigue analysis (50% of score - most reliable indicator)
    # Normal EAR is ~0.25-0.35, fatigue shows as lower values
    ear_fatigue = max(0, (0.30 - avg_ear) / 0.20)  # Normalize to 0-1
    
    # Eye closure duration analysis (30% of score - critical for safety) 
    closure_fatigue = 0.0
    if closure_duration > 0.5:  # Any extended closure is concerning
        closure_fatigue = min(1.0, closure_duration / 3.0)  # 3+ seconds = max fatigue
    
    # Microsleep events (15% of score - direct safety indicator)
    microsleep_fatigue = min(1.0, microsleep_count / 2.0)  # 2+ microsleeps = high fatigue
    
    # Blink pattern analysis (5% of score - behavioral indicator)
    blink_fatigue = 0.0
    if blink_rate < 10:  # Low blink rate (normal is 15-20/min)
        blink_fatigue = (10 - blink_rate) / 10.0
    elif blink_rate > 30:  # Excessive blinking can also indicate fatigue
        blink_fatigue = min(1.0, (blink_rate - 30) / 20.0)
    
    # Combine vision indicators (lean approach - focus on proven metrics)
    vision_fusion = (ear_fatigue * 0.50 + 
                    closure_fatigue * 0.30 + 
                    microsleep_fatigue * 0.15 + 
                    blink_fatigue * 0.05)
    
    # Add heart rate if available (reduce vision weight to 75%)
    if hr_data and "hr" in hr_data:
        hr = hr_data["hr"]
        hr_baseline = 70
        hr_deviation = abs(hr - hr_baseline) / hr_baseline
        hr_score = min(1.0, hr_deviation * 1.5)  # Slightly reduced HR influence
        
        # Combine with HR (75% vision, 25% HR for lean approach)
        fusion_score = vision_fusion * 0.75 + hr_score * 0.25
    else:
        fusion_score = vision_fusion
    
    return min(1.0, max(0.0, fusion_score))

def get_personalized_thresholds(pilot_profile):
    """Get thresholds based on pilot profile - using default medium sensitivity since alert_sensitivity was removed"""
    thresholds = {
        "mild": DEFAULT_THRESHOLD_MILD,
        "moderate": DEFAULT_THRESHOLD_MOD,
        "severe": DEFAULT_THRESHOLD_SEVERE
    }
    
    # With new pilot profile schema, we use standard thresholds
    # Future enhancement: could use environmentPreferences.noiseSensitivity or other factors
    
    return thresholds

def determine_fatigue_stage(avg_score, thresholds):
    """Determine fatigue stage based on fusion score"""
    if avg_score >= thresholds["severe"]:
        return "severe"
    elif avg_score >= thresholds["moderate"]:
        return "moderate"
    elif avg_score >= thresholds["mild"]:
        return "mild"
    else:
        return "active"

def main():
    """Main predictor service with integrated data fusion and fatigue prediction"""
    core = CogniCore(SERVICE_NAME)
    logger = core.get_logger(SERVICE_NAME)
    logger.info("Predictor service started with integrated data fusion and enhanced HR analysis")
    
    # Notify systemd that service is ready
    systemd.daemon.notify('READY=1')
    logger.info("Notified systemd that service is ready")
    
    fusion_scores = deque(maxlen=WINDOW_SIZE)
    current_stage = "active"
    last_heartbeat = 0
    last_fusion_heartbeat = 0
    
    try:
        while True:
            # Get latest vision data for fusion processing
            vision_data = core.get_data("vision")
            
            # Check if vision data is fresh (within last 10 seconds)
            current_time = time.time()
            vision_timestamp = vision_data.get("timestamp", 0) if vision_data else 0
            vision_age = current_time - vision_timestamp
            is_vision_fresh = vision_age < 10  # 10 second threshold
            
            if vision_data and is_vision_fresh:
                # Get latest HR data (optional)
                hr_data = core.get_data("hr_sensor")
                
                # Calculate fusion score using enhanced HR metrics
                fusion_score = calculate_fusion_score(vision_data, hr_data)
                
                # Publish fusion result with lean vision data
                fusion_data = {
                    "fusion_score": fusion_score,
                    "avg_ear": vision_data.get("avg_ear", 0),
                    "eyes_closed": vision_data.get("eyes_closed", False),
                    "closure_duration": vision_data.get("closure_duration", 0),
                    "microsleep_count": vision_data.get("microsleep_count", 0),
                    "blink_rate": vision_data.get("blink_rate_per_minute", 0),
                    "vision_timestamp": vision_data.get("timestamp"),
                    "hr_timestamp": hr_data.get("timestamp") if hr_data else None,
                    "hr": hr_data.get("hr") if hr_data else None
                }
                
                core.publish_data("fusion", fusion_data)
                
                # Add to sliding window for prediction
                fusion_scores.append(fusion_score)
                
                # Only make predictions when we have enough data
                if len(fusion_scores) >= 2:
                    # Calculate sliding window average
                    avg_score = sum(fusion_scores) / len(fusion_scores)
                    
                    # Get pilot profile for personalization
                    pilot_profile = core.get_active_pilot_profile()
                    thresholds = get_personalized_thresholds(pilot_profile)
                    
                    # Determine fatigue stage
                    new_stage = determine_fatigue_stage(avg_score, thresholds)
                    
                    # Always update system state and display current status with all sensor readings
                    # Get all sensor readings
                    hr_reading = hr_data.get("hr") if hr_data else "N/A"
                    ear_reading = vision_data.get("avg_ear", 0)
                    # Lean approach - no MAR reading (removed for performance)
                    mar_display = "N/A"
                    
                    # Get environmental data
                    env_data = core.get_data("env_sensor")
                    temp_reading = int(float(env_data.get("temp", 0))) if env_data and env_data.get("temp") else "N/A"
                    humidity_reading = int(float(env_data.get("humidity", 0))) if env_data and env_data.get("humidity") else "N/A"
                    
                    # Check for stage change  
                    if new_stage != current_stage:
                        logger.info(f"Fatigue stage change: {current_stage} → {new_stage}")
                        current_stage = new_stage
                        
                        # Publish fatigue alert with lean vision indicators
                        alert_data = {
                            "stage": new_stage,
                            "fusion_score": avg_score,
                            "pilot_id": pilot_profile.id if pilot_profile else None,
                            "threshold_used": thresholds.get(new_stage, 0),
                            "avg_ear": fusion_data.get("avg_ear", 0),
                            "closure_duration": fusion_data.get("closure_duration", 0),
                            "microsleep_count": fusion_data.get("microsleep_count", 0),
                            "blink_rate": fusion_data.get("blink_rate", 0)
                        }
                        
                        core.publish_data("fatigue_alert", alert_data)
                    
                    # Always update system state with current status and readings
                    # Format the state display messages
                    if current_stage == "active":
                        state_line = "I'm watching"
                        state_enum = SystemState.MONITORING_ACTIVE
                    elif current_stage == "mild":
                        state_line = "Mild"
                        state_enum = SystemState.ALERT_MILD
                    elif current_stage == "moderate":
                        state_line = "Moderate"
                        state_enum = SystemState.ALERT_MODERATE
                    elif current_stage == "severe":
                        state_line = "Severe"
                        state_enum = SystemState.ALERT_SEVERE
                    else:
                        state_line = "I'm still here"
                        state_enum = SystemState.MONITORING_ACTIVE
                    
                    # Create display message with state and readings (EAR, BLINK, HR, TEMP, HUMIDITY)
                    # Format EAR to remove "0." prefix to save LCD space
                    ear_display = f"{ear_reading:.2f}".lstrip('0') if ear_reading < 1.0 else f"{ear_reading:.2f}"
                    blink_rate = vision_data.get("blink_rate_per_minute", 0)
                    
                    display_message = f"{state_line}\n{ear_display} {int(blink_rate)} {temp_reading} {humidity_reading}"
                    
                    # Set system state
                    core.set_system_state(
                        state_enum,
                        display_message,
                        pilot_id=pilot_profile.id if pilot_profile else None,
                        data={"fusion_score": avg_score, "hr": hr_reading, "ear": ear_reading, "blink_rate": blink_rate, "temp": temp_reading, "humidity": humidity_reading}
                    )
                
                # Log state and readings periodically (every 5 seconds to reduce overhead)
                current_time = time.time()
                if current_time - last_fusion_heartbeat > 5:
                    # Print the state with HR and EAR readings as requested
                    if current_stage == "active":
                        logger.info("MONITORING_ACTIVE")
                    elif current_stage == "mild":
                        logger.info("ALERT_MILD")  
                    elif current_stage == "moderate":
                        logger.info("ALERT_MODERATE")
                    elif current_stage == "severe":
                        logger.info("ALERT_SEVERE")
                    
                    # Print all sensor readings on second line (EAR, BLINK, HR, TEMP, HUMIDITY)
                    hr_reading = hr_data.get("hr") if hr_data else "N/A"
                    ear_reading = vision_data.get("avg_ear", 0)
                    blink_reading = vision_data.get("blink_rate_per_minute", 0)
                    
                    # Get environmental data
                    env_data = core.get_data("env_sensor")
                    temp_reading = int(float(env_data.get("temp", 0))) if env_data and env_data.get("temp") else "N/A"
                    humidity_reading = int(float(env_data.get("humidity", 0))) if env_data and env_data.get("humidity") else "N/A"
                    
                    logger.info(f"{ear_reading:.2f} {int(blink_reading)} {hr_reading} {temp_reading} {humidity_reading}")
                    
                    last_fusion_heartbeat = current_time
                
                # Send watchdog notification periodically (every 10 seconds)
                if len(fusion_scores) >= 2 and current_time - last_heartbeat > 10:
                    systemd.daemon.notify('WATCHDOG=1')
                    last_heartbeat = current_time
            
            elif vision_data and not is_vision_fresh:
                # Vision data exists but is stale - log warning periodically
                if not hasattr(main, '_last_stale_warning') or current_time - main._last_stale_warning > 30:
                    logger.warning(f"Vision data is stale ({vision_age:.1f}s old) - not setting system state")
                    main._last_stale_warning = current_time
            
            # Send watchdog notification even when not processing
            if current_time - last_heartbeat > 10:
                systemd.daemon.notify('WATCHDOG=1')
                last_heartbeat = current_time
            
            time.sleep(0.05)  # 20Hz processing for faster fatigue detection
    
    except KeyboardInterrupt:
        logger.info("Predictor service stopping...")
        core.shutdown()

if __name__ == "__main__":
    main()