import os
import json
import time
import sys
import logging
import math
from pathlib import Path
from collections import deque
import systemd.daemon

# Add project root to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from CogniCore import CogniCore, SystemState
SERVICE_NAME = "predictor"

# Enhanced sliding window for temporal analysis
WINDOW_SIZE = 5  # Increased for better trend analysis
TREND_WINDOW_SIZE = 10  # For detecting progression patterns

# Enhanced threshold system with hysteresis
DEFAULT_THRESHOLD_MILD   = 0.25  # Lowered for earlier detection
DEFAULT_THRESHOLD_MOD    = 0.50  # More conservative thresholds
DEFAULT_THRESHOLD_SEVERE = 0.75
DEFAULT_HYSTERESIS       = 0.05

class EnhancedFatiguePredictor:
    def __init__(self):
        self.fusion_history = deque(maxlen=TREND_WINDOW_SIZE)
        self.hr_baseline_buffer = deque(maxlen=60)  # 1 minute of HR data for dynamic baseline
        self.hrv_baseline_buffer = deque(maxlen=60)
        
    def calculate_enhanced_fusion_score(self, vision_data, hr_data):
        """
        Simplified fusion algorithm using Vision (70%) and Heart Rate (30%) only
        """
        # Initialize component scores
        vision_score = 0.0
        hr_score = 0.0
        
        # Data availability flags for confidence scoring
        has_vision = bool(vision_data)
        has_hr = bool(hr_data and hr_data.get('hr'))
        
        # ===========================================
        # VISION ANALYSIS (70% weight - CRITICAL)
        # ===========================================
        if has_vision:
            vision_score = self._calculate_vision_score(vision_data)
        
        # ===========================================
        # HEART RATE ANALYSIS (30% weight - HIGH)
        # ===========================================
        if has_hr:
            hr_score = self._calculate_hr_score(hr_data)
        
        # ===========================================
        # SIMPLIFIED FUSION (VISION + HR)
        # ===========================================
        
        # Base weights - Vision and HR only
        base_weights = {
            'vision': 0.70,
            'hr': 0.30
        }
        
        # Adjust weights based on data availability
        available_sensors = []
        if has_vision: available_sensors.append('vision')
        if has_hr: available_sensors.append('hr')
        
        if not available_sensors:
            return 0.0, 0.0  # No data, no confidence
        
        # Redistribute weights among available sensors
        adjusted_weights = self._redistribute_weights(base_weights, available_sensors)
        
        # Calculate weighted fusion score (Vision + HR only)
        fusion_score = (
            vision_score * adjusted_weights.get('vision', 0) +
            hr_score * adjusted_weights.get('hr', 0)
        )
        
        # Calculate confidence based on sensor availability and data quality
        confidence = self._calculate_confidence(available_sensors, vision_data, hr_data)
        
        # Apply temporal smoothing and trend analysis
        fusion_score = self._apply_temporal_analysis(fusion_score)
        
        return min(1.0, max(0.0, fusion_score)), confidence
    
    def _calculate_vision_score(self, vision_data):
        """Enhanced vision analysis using all available vision metrics"""
        score = 0.0
        
        # Eye Aspect Ratio Analysis (CRITICAL - 50% of vision score)
        avg_ear = vision_data.get("avg_ear", 0.25)
        if avg_ear < 0.15:  # Severely drooping eyes
            ear_score = 1.0
        elif avg_ear < 0.20:  # Critical drowsiness threshold
            ear_score = 0.8 + (0.20 - avg_ear) * 4.0  # Steep increase
        elif avg_ear < 0.25:  # Mild drowsiness
            ear_score = (0.25 - avg_ear) * 3.2  # 0.25->0, 0.20->0.16
        else:
            ear_score = 0.0
        
        # Eye Closure Duration (CRITICAL - 25% of vision score)
        closure_duration = vision_data.get("closure_duration", 0.0)
        if closure_duration >= 3.0:  # 3+ seconds = severe
            closure_score = 1.0
        elif closure_duration >= 1.0:  # 1-3 seconds = moderate to severe
            closure_score = 0.5 + (closure_duration - 1.0) * 0.25
        elif closure_duration >= 0.5:  # 0.5-1 second = mild
            closure_score = closure_duration * 1.0
        else:
            closure_score = 0.0
        
        # Microsleep Events (CRITICAL - 15% of vision score)
        microsleep_count = vision_data.get("microsleep_count", 0)
        microsleep_score = min(1.0, microsleep_count * 0.3)  # Each microsleep adds 0.3
        
        # Blink Rate Analysis (MEDIUM - 10% of vision score)
        blink_rate = vision_data.get("blink_rate_per_minute", 15.0)
        if blink_rate < 5:  # Very low blinking
            blink_score = 1.0
        elif blink_rate < 10:  # Low blinking (fatigue)
            blink_score = (10 - blink_rate) / 5.0
        elif blink_rate > 40:  # Excessive blinking (stress/fatigue)
            blink_score = min(1.0, (blink_rate - 40) / 20.0)
        else:
            blink_score = 0.0
        
        # Combine vision components
        score = (ear_score * 0.50 + 
                closure_score * 0.25 + 
                microsleep_score * 0.15 + 
                blink_score * 0.10)
        
        return min(1.0, score)
    
    def _calculate_hr_score(self, hr_data):
        """Enhanced heart rate analysis using all available HR metrics"""
        score = 0.0
        
        # Heart Rate Variability (RMSSD) - HIGH impact (40% of HR score)
        rmssd = hr_data.get("rmssd")
        if rmssd is not None:
            if rmssd < 15:  # Severe fatigue/stress
                hrv_score = 1.0
            elif rmssd < 25:  # Moderate fatigue
                hrv_score = (25 - rmssd) / 10.0
            elif rmssd < 35:  # Mild concern
                hrv_score = (35 - rmssd) / 20.0
            else:
                hrv_score = 0.0
        else:
            hrv_score = 0.0
        
        # Stress Index - HIGH impact (30% of HR score)
        stress_index = hr_data.get("stress_index", 0.0)
        stress_score = min(1.0, stress_index)  # Already normalized 0-1
        
        # Baseline Deviation - MEDIUM impact (20% of HR score)
        baseline_deviation = hr_data.get("baseline_deviation", 0.0)
        if baseline_deviation > 0.4:  # >40% deviation is concerning
            deviation_score = min(1.0, (baseline_deviation - 0.2) / 0.3)
        else:
            deviation_score = 0.0
        
        # HR Trend Analysis - MEDIUM impact (10% of HR score)
        hr_trend = hr_data.get("hr_trend", 0)
        if abs(hr_trend) > 15:  # Rapid HR changes
            trend_score = min(1.0, (abs(hr_trend) - 10) / 20.0)
        else:
            trend_score = 0.0
        
        # Update dynamic baseline
        current_hr = hr_data.get("hr")
        current_hrv = hr_data.get("rmssd")
        if current_hr:
            self.hr_baseline_buffer.append(current_hr)
        if current_hrv:
            self.hrv_baseline_buffer.append(current_hrv)
        
        # Combine HR components
        score = (hrv_score * 0.40 + 
                stress_score * 0.30 + 
                deviation_score * 0.20 + 
                trend_score * 0.10)
        
        return min(1.0, score)
    
    def _redistribute_weights(self, base_weights, available_sensors):
        """Redistribute weights when sensors are unavailable"""
        if len(available_sensors) == len(base_weights):
            return base_weights
        
        # Calculate total available weight
        available_weight = sum(base_weights[sensor] for sensor in available_sensors)
        
        # Redistribute proportionally
        adjusted = {}
        for sensor in available_sensors:
            adjusted[sensor] = base_weights[sensor] / available_weight
        
        return adjusted
    
    def _calculate_confidence(self, available_sensors, vision_data, hr_data):
        """Calculate confidence score based on data availability and quality"""
        base_confidence = len(available_sensors) / 2.0  # 2 total sensor types (Vision + HR only)
        
        # Adjust for data quality
        quality_bonus = 0.0
        
        if vision_data:
            # High quality vision data (all metrics available)
            vision_metrics = ['avg_ear', 'eyes_closed', 'closure_duration', 'microsleep_count']
            vision_completeness = sum(1 for metric in vision_metrics if vision_data.get(metric) is not None) / len(vision_metrics)
            quality_bonus += vision_completeness * 0.3  # Increased since vision is more important
        
        if hr_data:
            # High quality HR data (HRV available)
            if hr_data.get('rmssd') is not None:
                quality_bonus += 0.2  # Increased weighting for HRV availability
        
        return min(1.0, base_confidence + quality_bonus)
    
    def _apply_temporal_analysis(self, current_score):
        """Apply temporal smoothing and trend analysis"""
        self.fusion_history.append(current_score)
        
        if len(self.fusion_history) < 2:
            return current_score
        
        # Exponential moving average for smoothing
        weights = [0.4, 0.3, 0.2, 0.07, 0.03][:len(self.fusion_history)]
        weights = weights[::-1]  # Most recent gets highest weight
        
        smoothed_score = sum(score * weight for score, weight in zip(self.fusion_history, weights))
        smoothed_score /= sum(weights)
        
        # Trend analysis - detect rapid deterioration
        if len(self.fusion_history) >= 3:
            recent_trend = self.fusion_history[-1] - self.fusion_history[-3]
            if recent_trend > 0.2:  # Rapid fatigue increase
                smoothed_score += 0.1  # Small boost for trend
        
        return smoothed_score

def calculate_fusion_score(vision_data, hr_data):
    """
    Simplified fusion score calculation using Vision (70%) and Heart Rate (30%) only
    """
    global predictor
    
    if 'predictor' not in globals():
        predictor = EnhancedFatiguePredictor()
    
    fusion_score, confidence = predictor.calculate_enhanced_fusion_score(vision_data, hr_data)
    
    return fusion_score, confidence

def get_personalized_thresholds(pilot_profile):
    """Enhanced threshold calculation with pilot adaptation"""
    base_thresholds = {
        "mild": DEFAULT_THRESHOLD_MILD,
        "moderate": DEFAULT_THRESHOLD_MOD,
        "severe": DEFAULT_THRESHOLD_SEVERE
    }
    
    # Future enhancement: Use pilot profile for personalization
    # Could consider: age, experience level, recent flight history, etc.
    
    return base_thresholds

def determine_fatigue_stage(avg_score, thresholds, confidence):
    """Enhanced fatigue stage determination with confidence weighting"""
    # Adjust thresholds based on confidence
    confidence_factor = 0.8 + (confidence * 0.4)  # 0.8 to 1.2 multiplier
    
    adjusted_thresholds = {
        "mild": thresholds["mild"] * confidence_factor,
        "moderate": thresholds["moderate"] * confidence_factor,
        "severe": thresholds["severe"] * confidence_factor
    }
    
    if avg_score >= adjusted_thresholds["severe"]:
        return "severe"
    elif avg_score >= adjusted_thresholds["moderate"]:
        return "moderate"
    elif avg_score >= adjusted_thresholds["mild"]:
        return "mild"
    else:
        return "active"

def main():
    """Simplified predictor service using Vision (70%) and HR (30%) only"""
    core = CogniCore(SERVICE_NAME)
    logger = core.get_logger(SERVICE_NAME)
    logger.info("Simplified Predictor service started - Vision (70%) + HR (30%) only")
    
    # Notify systemd that service is ready
    systemd.daemon.notify('READY=1')
    logger.info("Notified systemd that service is ready")
    
    fusion_scores = deque(maxlen=WINDOW_SIZE)
    current_stage = "active"
    last_heartbeat = 0
    last_fusion_heartbeat = 0
    
    try:
        while True:
            current_time = time.time()
            
            # Collect vision and HR data only
            vision_data = core.get_data("vision")
            hr_data = core.get_data("hr_sensor")
            
            # Check if vision data is fresh (primary sensor)
            vision_timestamp = vision_data.get("timestamp", 0) if vision_data else 0
            vision_age = current_time - vision_timestamp
            is_vision_fresh = vision_age < 10
            
            if vision_data and is_vision_fresh:
                # Calculate fusion score (Vision + HR only)
                fusion_score, confidence = calculate_fusion_score(vision_data, hr_data)
                
                # Simplified fusion data publication (Vision + HR only)
                fusion_data = {
                    "fusion_score": fusion_score,
                    "confidence": confidence,
                    # Vision metrics
                    "avg_ear": vision_data.get("avg_ear", 0),
                    "eyes_closed": vision_data.get("eyes_closed", False),
                    "closure_duration": vision_data.get("closure_duration", 0),
                    "microsleep_count": vision_data.get("microsleep_count", 0),
                    "blink_rate": vision_data.get("blink_rate_per_minute", 0),
                    # HR metrics
                    "hr": hr_data.get("hr") if hr_data else None,
                    "rmssd": hr_data.get("rmssd") if hr_data else None,
                    "stress_index": hr_data.get("stress_index") if hr_data else None,
                    # Timestamps
                    "vision_timestamp": vision_data.get("timestamp"),
                    "hr_timestamp": hr_data.get("timestamp") if hr_data else None
                }
                
                core.publish_data("fusion", fusion_data)
                
                # Add to sliding window
                fusion_scores.append((fusion_score, confidence))
                
                # Make predictions with sufficient data
                if len(fusion_scores) >= 3:  # Need more data for enhanced algorithm
                    # Calculate weighted average (more recent data weighted higher)
                    weights = [0.5, 0.3, 0.2][:len(fusion_scores)]
                    weights = weights[::-1]  # Reverse for recent-first
                    
                    avg_score = sum(score * weight for (score, conf), weight in zip(fusion_scores, weights))
                    avg_score /= sum(weights)
                    
                    # Average confidence
                    avg_confidence = sum(conf for score, conf in fusion_scores) / len(fusion_scores)
                    
                    # Get personalized thresholds
                    pilot_profile = core.get_active_pilot_profile()
                    thresholds = get_personalized_thresholds(pilot_profile)
                    
                    # Determine fatigue stage with confidence weighting
                    new_stage = determine_fatigue_stage(avg_score, thresholds, avg_confidence)
                    
                    # Update display and alerts
                    if new_stage != current_stage:
                        logger.info(f"Fatigue stage change: {current_stage} → {new_stage} (confidence: {avg_confidence:.2f})")
                        current_stage = new_stage
                        
                        # Simplified alert data (Vision + HR factors only)
                        alert_data = {
                            "stage": new_stage,
                            "fusion_score": avg_score,
                            "confidence": avg_confidence,
                            "pilot_id": pilot_profile.id if pilot_profile else None,
                            "threshold_used": thresholds.get(new_stage, 0),
                            "contributing_factors": {
                                "vision": fusion_data.get("avg_ear", 0) < 0.20,
                                "heart_rate": fusion_data.get("rmssd", 100) < 25
                            }
                        }
                        
                        core.publish_data("fatigue_alert", alert_data)
                    
                    # Simplified system state display (Vision + HR only)
                    stage_messages = {
                        "active": ("Alert & Ready", SystemState.MONITORING_ACTIVE),
                        "mild": ("Mild Fatigue", SystemState.ALERT_MILD),
                        "moderate": ("Moderate Fatigue", SystemState.ALERT_MODERATE),
                        "severe": ("SEVERE FATIGUE", SystemState.ALERT_SEVERE)
                    }
                    
                    state_line, state_enum = stage_messages[current_stage]
                    
                    # Display only Vision and HR readings
                    ear_display = f"{fusion_data.get('avg_ear', 0):.2f}".lstrip('0')
                    blink_rate = int(fusion_data.get("blink_rate", 0))
                    hr_display = int(fusion_data.get("hr", 0)) if fusion_data.get("hr") else "N/A"
                    
                    display_message = f"{state_line} ({avg_confidence:.1f})\n{ear_display} {blink_rate} {hr_display}"
                    
                    core.set_system_state(
                        state_enum,
                        display_message,
                        pilot_id=pilot_profile.id if pilot_profile else None,
                        data={
                            "fusion_score": avg_score,
                            "confidence": avg_confidence,
                            "sensor_readings": fusion_data
                        }
                    )
                
                # Simplified periodic logging (Vision + HR only)
                if current_time - last_fusion_heartbeat > 5:
                    stage_log_map = {
                        "active": "MONITORING_ACTIVE",
                        "mild": "ALERT_MILD",
                        "moderate": "ALERT_MODERATE", 
                        "severe": "ALERT_SEVERE"
                    }
                    
                    logger.info(f"{stage_log_map[current_stage]} (confidence: {fusion_data.get('confidence', 0):.2f})")
                    
                    # Vision and HR readings only
                    readings = []
                    readings.append(f"EAR:{fusion_data.get('avg_ear', 0):.3f}")
                    readings.append(f"BLINK:{int(fusion_data.get('blink_rate', 0))}")
                    readings.append(f"HR:{fusion_data.get('hr', 'N/A')}")
                    if fusion_data.get('rmssd'):
                        readings.append(f"HRV:{fusion_data.get('rmssd'):.0f}")
                    
                    logger.info(" | ".join(readings))
                    last_fusion_heartbeat = current_time
                
                # Watchdog notification
                if current_time - last_heartbeat > 10:
                    systemd.daemon.notify('WATCHDOG=1')
                    last_heartbeat = current_time
            
            elif vision_data and not is_vision_fresh:
                # Stale data warning
                if not hasattr(main, '_last_stale_warning') or current_time - main._last_stale_warning > 30:
                    logger.warning(f"Vision data is stale ({vision_age:.1f}s old) - prediction unavailable")
                    main._last_stale_warning = current_time
            
            # Regular watchdog
            if current_time - last_heartbeat > 10:
                systemd.daemon.notify('WATCHDOG=1')
                last_heartbeat = current_time
            
            time.sleep(0.05)  # 20Hz processing
    
    except KeyboardInterrupt:
        logger.info("Simplified Predictor service stopping...")
        core.shutdown()

if __name__ == "__main__":
    main()