import os
import json
import time
import sys
import logging
import math
from pathlib import Path
from collections import deque
import systemd.daemon

# Add project root to path for imports (deployment flexible)
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from CogniCore import CogniCore, SystemState
SERVICE_NAME = "predictor"

# Window configuration for NORMAL fatigue progression
WINDOW_SIZE = 5  # EMA sliding window for gradual trends
TREND_WINDOW_SIZE = 10  # For detecting longer-term patterns

# Enhanced threshold values with more granular detection
DEFAULT_THRESHOLD_MILD   = 0.25  # Earlier mild detection
DEFAULT_THRESHOLD_MOD    = 0.50  # Moderate threshold
DEFAULT_THRESHOLD_SEVERE = 0.75  # Severe threshold
DEFAULT_HYSTERESIS       = 0.10  # Larger hysteresis to prevent oscillation

# CRITICAL event thresholds for IMMEDIATE response (bypass smoothing)
CRITICAL_EAR_THRESHOLD = 0.15  # EAR below this = immediate concern
CRITICAL_CLOSURE_DURATION = 1.0  # Eyes closed >1s = immediate alert
CRITICAL_MICROSLEEP_THRESHOLD = 2  # 2+ microsleeps = immediate escalation
CRITICAL_YAWN_THRESHOLD = 3  # 3+ yawns = potential fatigue indicator
CRITICAL_YAWN_DURATION = 2.0  # Current yawn >2s = concerning
CRITICAL_STRESS_INDEX = 0.75  # Stress index >0.75 = severe stress
CRITICAL_RMSSD_LOW = 20  # RMSSD <20ms = very low HRV
CRITICAL_HR_TREND = 5  # HR increasing >5 BPM/min = rapid deterioration

# State change rate limiting
MIN_STATE_DURATION = 2.0  # Minimum seconds between NORMAL state changes (not critical)
MAX_CRITICAL_ALERT_RATE = 0.5  # Minimum seconds between critical alerts

class EnhancedFatiguePredictor:
    """
    Hybrid predictor with dual-path processing:
    - CRITICAL PATH: Immediate response to dangerous conditions
    - NORMAL PATH: Smoothed analysis for gradual fatigue trends
    """
    def __init__(self):
        self.fusion_history = deque(maxlen=TREND_WINDOW_SIZE)
        self.hr_baseline_buffer = deque(maxlen=60)  # 1 minute of HR data

    def calculate_fusion_score(self, vision_data, hr_data):
        """
        Calculate fusion score with data validation.
        Returns: (fusion_score, confidence, is_critical_event)
        """
        # Initialize
        vision_score = 0.0
        hr_score = 0.0
        is_critical_event = False

        # Data availability flags
        has_vision = bool(vision_data)
        has_hr = bool(hr_data and hr_data.get('hr'))

        # ==========================================
        # VISION ANALYSIS (70% weight)
        # ==========================================
        if has_vision:
            vision_score, vision_critical = self._calculate_vision_score(vision_data)
            is_critical_event = vision_critical

        # ==========================================
        # HEART RATE ANALYSIS (30% weight)
        # ==========================================
        if has_hr:
            hr_score = self._calculate_hr_score(hr_data)

            # Check for critical HR events
            stress_index = hr_data.get("stress_index")
            rmssd = hr_data.get("rmssd")
            hr_trend = hr_data.get("hr_trend")

            # Critical HR conditions that bypass smoothing
            if stress_index is not None and stress_index >= CRITICAL_STRESS_INDEX:
                is_critical_event = True  # Severe stress detected

            if rmssd is not None and rmssd < CRITICAL_RMSSD_LOW:
                is_critical_event = True  # Very low HRV detected

            if hr_trend is not None and hr_trend > CRITICAL_HR_TREND:
                is_critical_event = True  # Rapid HR deterioration

        # ==========================================
        # FUSION CALCULATION
        # ==========================================
        base_weights = {'vision': 0.70, 'hr': 0.30}

        # Adjust weights based on availability
        available_sensors = []
        if has_vision: available_sensors.append('vision')
        if has_hr: available_sensors.append('hr')

        if not available_sensors:
            return 0.0, 0.0, False  # No data

        adjusted_weights = self._redistribute_weights(base_weights, available_sensors)

        # Calculate weighted fusion
        fusion_score = (
            vision_score * adjusted_weights.get('vision', 0) +
            hr_score * adjusted_weights.get('hr', 0)
        )

        # Calculate confidence
        confidence = self._calculate_confidence(available_sensors, vision_data, hr_data)

        # Apply temporal smoothing ONLY for non-critical events
        if not is_critical_event:
            fusion_score = self._apply_temporal_smoothing(fusion_score)
        else:
            # For critical events, clear history and use raw score
            self.fusion_history.clear()
            self.fusion_history.append(fusion_score)

        return min(1.0, max(0.0, fusion_score)), confidence, is_critical_event

    def _calculate_vision_score(self, vision_data):
        """
        Enhanced vision analysis with critical event detection and yawning integration.
        Returns: (score, is_critical)
        """
        score = 0.0
        is_critical = False

        # Extract metrics
        avg_ear = vision_data.get("avg_ear", 0.25)
        closure_duration = vision_data.get("closure_duration", 0.0)
        microsleep_count = vision_data.get("microsleep_count", 0)
        blink_rate = vision_data.get("blink_rate_per_minute", 15.0)

        # Extract yawning metrics (NEW)
        mar = vision_data.get("mar", 0.25)  # Mouth Aspect Ratio
        is_yawning = vision_data.get("yawning", False)
        yawn_count = vision_data.get("yawn_count", 0)
        yawn_duration = vision_data.get("yawn_duration", 0.0)

        # CRITICAL EVENT DETECTION (bypasses smoothing)
        if avg_ear <= 0.0 or avg_ear > 1.0:
            # Invalid EAR - ignore this sample
            return 0.0, False

        if closure_duration >= CRITICAL_CLOSURE_DURATION or avg_ear < CRITICAL_EAR_THRESHOLD:
            is_critical = True

        if microsleep_count >= CRITICAL_MICROSLEEP_THRESHOLD:
            is_critical = True

        # Add yawning to critical events if excessive (NEW)
        if yawn_count >= CRITICAL_YAWN_THRESHOLD and yawn_duration > CRITICAL_YAWN_DURATION:
            is_critical = True

        # EAR Analysis (40% of vision score - reduced from 50%)
        if avg_ear < 0.15:  # Severely drooping
            ear_score = 1.0
        elif avg_ear < 0.20:  # Critical drowsiness
            ear_score = 0.8 + (0.20 - avg_ear) * 4.0
        elif avg_ear < 0.25:  # Mild drowsiness
            ear_score = (0.25 - avg_ear) * 3.2
        else:
            ear_score = max(0, (0.30 - avg_ear) / 0.20)  # Normalized fatigue score

        # Eye Closure Duration (25% of vision score - reduced from 30%)
        if closure_duration >= 3.0:  # 3+ seconds = severe
            closure_score = 1.0
        elif closure_duration >= 1.0:  # 1-3 seconds = moderate to severe
            closure_score = 0.5 + (closure_duration - 1.0) * 0.25
        elif closure_duration >= 0.5:  # 0.5-1 second = mild
            closure_score = closure_duration * 1.0
        else:
            closure_score = 0.0

        # Microsleep Events (15% of vision score)
        microsleep_score = min(1.0, microsleep_count * 0.3)

        # Yawning Analysis (15% of vision score - NEW)
        yawn_score = 0.0

        # Yawn frequency component (50% of yawn score)
        if yawn_count >= 5:  # Excessive yawning
            yawn_freq_score = 1.0
        elif yawn_count >= 3:  # Frequent yawning
            yawn_freq_score = 0.6 + (yawn_count - 3) * 0.2
        elif yawn_count >= 1:  # Some yawning
            yawn_freq_score = yawn_count * 0.3
        else:
            yawn_freq_score = 0.0

        # Current yawn duration component (30% of yawn score)
        if is_yawning:
            if yawn_duration >= 4.0:  # Very long yawn
                yawn_dur_score = 1.0
            elif yawn_duration >= 2.0:  # Long yawn
                yawn_dur_score = 0.5 + (yawn_duration - 2.0) * 0.25
            elif yawn_duration >= 1.0:  # Normal yawn
                yawn_dur_score = yawn_duration * 0.5
            else:
                yawn_dur_score = 0.2  # Just started yawning
        else:
            yawn_dur_score = 0.0

        # MAR component (20% of yawn score) - mouth openness indicator
        if mar > 0.6:  # Very wide mouth opening
            mar_score = 1.0
        elif mar > 0.5:  # Wide mouth (yawn threshold)
            mar_score = (mar - 0.5) * 10.0
        elif mar > 0.35:  # Slightly open mouth
            mar_score = (mar - 0.35) * 3.33
        else:
            mar_score = 0.0

        # Combine yawn components
        yawn_score = (yawn_freq_score * 0.5 + yawn_dur_score * 0.3 + mar_score * 0.2)

        # Blink Rate Analysis (5% of vision score)
        if blink_rate < 5:  # Very low blinking
            blink_score = 1.0
        elif blink_rate < 10:  # Low blinking
            blink_score = (10 - blink_rate) / 5.0
        elif blink_rate > 40:  # Excessive blinking
            blink_score = min(1.0, (blink_rate - 40) / 20.0)
        else:
            blink_score = 0.0

        # Combine all components with updated weights
        score = (ear_score * 0.40 +         # Reduced from 0.50
                closure_score * 0.25 +       # Reduced from 0.30
                microsleep_score * 0.15 +    # Unchanged
                yawn_score * 0.15 +          # NEW component
                blink_score * 0.05)          # Unchanged

        return min(1.0, score), is_critical

    def _calculate_hr_score(self, hr_data):
        """
        Enhanced heart rate analysis using comprehensive bio_monitor data.
        Incorporates stress index, RMSSD, HR trend, and baseline deviation.
        Returns: score (0.0-1.0) representing HR-based fatigue level
        """
        hr = hr_data.get("hr")
        if not hr:
            return 0.0

        # Extract all available bio_monitor metrics
        stress_index = hr_data.get("stress_index", None)
        rmssd = hr_data.get("rmssd", None)
        hr_trend = hr_data.get("hr_trend", None)
        baseline_deviation = hr_data.get("baseline_deviation", None)
        baseline_hr = hr_data.get("baseline_hr", 70)
        baseline_hrv = hr_data.get("baseline_hrv", 45)

        # Component scores (will be weighted and combined)
        components = []
        weights = []

        # 1. Stress Index Component (40% if available - pre-calculated comprehensive metric)
        if stress_index is not None:
            # Stress index is already normalized 0-1 by bio_monitor
            # Higher stress correlates with fatigue
            stress_score = stress_index
            components.append(stress_score)
            weights.append(0.40)

        # 2. RMSSD/HRV Component (25% if available - parasympathetic tone indicator)
        if rmssd is not None and baseline_hrv > 0:
            # Low RMSSD indicates reduced HRV (fatigue/stress)
            # Normal RMSSD: 20-100ms, lower values = more fatigue
            if rmssd < 20:  # Very low HRV
                hrv_score = 1.0
            elif rmssd < 30:  # Low HRV
                hrv_score = 0.7 + (30 - rmssd) / 10 * 0.3
            elif rmssd < baseline_hrv:  # Below baseline
                hrv_score = (baseline_hrv - rmssd) / baseline_hrv * 0.7
            else:  # At or above baseline (good HRV)
                hrv_score = 0.0

            components.append(hrv_score)
            weights.append(0.25)

        # 3. HR Trend Component (15% if available - fatigue progression indicator)
        if hr_trend is not None:
            # Positive trend = increasing HR = increasing fatigue/stress
            # Typical range: -5 to +5 BPM/minute
            if hr_trend > 3:  # Rapid HR increase
                trend_score = 1.0
            elif hr_trend > 1:  # Moderate increase
                trend_score = 0.5 + (hr_trend - 1) / 4
            elif hr_trend > 0:  # Slight increase
                trend_score = hr_trend / 2
            else:  # Stable or decreasing (recovery)
                trend_score = 0.0

            components.append(trend_score)
            weights.append(0.15)

        # 4. Baseline Deviation Component (20% if available or 100% if only HR)
        if baseline_deviation is not None:
            # Already normalized 0-1 by bio_monitor
            deviation_score = min(1.0, baseline_deviation * 2.0)  # Amplify for sensitivity
        else:
            # Fallback to simple calculation if not provided
            if not self.hr_baseline_buffer:
                hr_baseline = baseline_hr
            else:
                hr_baseline = sum(self.hr_baseline_buffer) / len(self.hr_baseline_buffer)

            deviation = abs(hr - hr_baseline) / hr_baseline
            deviation_score = min(1.0, deviation * 1.5)

            # Update baseline buffer for fallback calculation
            self.hr_baseline_buffer.append(hr)

        components.append(deviation_score)
        weights.append(0.20 if len(components) > 1 else 1.0)

        # Normalize weights to sum to 1.0
        total_weight = sum(weights)
        if total_weight > 0:
            normalized_weights = [w / total_weight for w in weights]

            # Calculate weighted average
            hr_score = sum(c * w for c, w in zip(components, normalized_weights))
        else:
            # Fallback if no components (shouldn't happen)
            hr_score = 0.0

        return min(1.0, hr_score)

    def _redistribute_weights(self, base_weights, available_sensors):
        """Redistribute weights when sensors unavailable"""
        if len(available_sensors) == len(base_weights):
            return base_weights

        available_weight = sum(base_weights[sensor] for sensor in available_sensors)
        adjusted = {}
        for sensor in available_sensors:
            adjusted[sensor] = base_weights[sensor] / available_weight

        return adjusted

    def _calculate_confidence(self, available_sensors, vision_data, hr_data):
        """Calculate confidence based on data quality and completeness"""
        base_confidence = len(available_sensors) / 2.0
        quality_bonus = 0.0

        # Vision data quality assessment
        if vision_data:
            vision_metrics = ['avg_ear', 'eyes_closed', 'closure_duration', 'microsleep_count', 'mar', 'yawn_count']
            completeness = sum(1 for m in vision_metrics if vision_data.get(m) is not None) / len(vision_metrics)
            quality_bonus += completeness * 0.25

        # Enhanced HR data quality assessment
        if hr_data:
            # Check for advanced metrics from bio_monitor
            hr_quality_score = 0.0

            if hr_data.get('stress_index') is not None:
                hr_quality_score += 0.35  # Pre-calculated comprehensive metric

            if hr_data.get('rmssd') is not None:
                hr_quality_score += 0.30  # HRV data available

            if hr_data.get('hr_trend') is not None:
                hr_quality_score += 0.20  # Trend analysis available

            if hr_data.get('baseline_deviation') is not None:
                hr_quality_score += 0.15  # Personalized baseline

            # Maximum 0.25 bonus for HR quality
            quality_bonus += hr_quality_score * 0.25

        return min(1.0, base_confidence + quality_bonus)

    def _apply_temporal_smoothing(self, current_score):
        """Apply exponential moving average for smoothing"""
        self.fusion_history.append(current_score)

        if len(self.fusion_history) < 2:
            return current_score

        # EMA with recent bias
        weights = [0.4, 0.3, 0.2, 0.07, 0.03][:len(self.fusion_history)]
        weights = weights[::-1]  # Most recent gets highest weight

        smoothed = sum(score * weight for score, weight in zip(self.fusion_history, weights))
        smoothed /= sum(weights)

        # Trend detection - boost for rapid deterioration
        if len(self.fusion_history) >= 3:
            recent_trend = self.fusion_history[-1] - self.fusion_history[-3]
            if recent_trend > 0.2:  # Rapid increase
                smoothed += 0.05  # Small boost

        return smoothed


def get_personalized_thresholds(pilot_profile):
    """Get thresholds based on pilot profile"""
    thresholds = {
        "mild": DEFAULT_THRESHOLD_MILD,
        "moderate": DEFAULT_THRESHOLD_MOD,
        "severe": DEFAULT_THRESHOLD_SEVERE
    }

    # Future: Use pilot preferences for sensitivity adjustments
    return thresholds


def determine_fatigue_stage(avg_score, thresholds, confidence, current_stage="active"):
    """
    Determine fatigue stage with hysteresis and confidence weighting
    """
    # Adjust thresholds based on confidence (80-120% multiplier)
    confidence_factor = 0.8 + (confidence * 0.4)

    # Apply hysteresis bands
    mild_up = thresholds["mild"] * confidence_factor
    mild_down = mild_up - DEFAULT_HYSTERESIS
    moderate_up = thresholds["moderate"] * confidence_factor
    moderate_down = moderate_up - DEFAULT_HYSTERESIS
    severe_up = thresholds["severe"] * confidence_factor
    severe_down = severe_up - DEFAULT_HYSTERESIS

    # State machine with hysteresis
    if current_stage == "severe":
        if avg_score < severe_down:
            return "moderate" if avg_score >= moderate_down else ("mild" if avg_score >= mild_down else "active")
        return "severe"
    elif current_stage == "moderate":
        if avg_score >= severe_up:
            return "severe"
        elif avg_score < moderate_down:
            return "mild" if avg_score >= mild_down else "active"
        return "moderate"
    elif current_stage == "mild":
        if avg_score >= moderate_up:
            return "moderate"
        elif avg_score < mild_down:
            return "active"
        return "mild"
    else:  # active
        if avg_score >= severe_up:
            return "severe"
        elif avg_score >= moderate_up:
            return "moderate"
        elif avg_score >= mild_up:
            return "mild"
        return "active"


def main():
    """Main predictor service with dual-path processing"""
    core = CogniCore(SERVICE_NAME)
    logger = core.get_logger(SERVICE_NAME)
    logger.info("Enhanced Predictor service started - Dual-path: Critical (immediate) + Normal (smoothed)")

    # Notify systemd ready
    systemd.daemon.notify('READY=1')
    logger.info("Service ready")

    # Initialize predictor
    predictor = EnhancedFatiguePredictor()
    fusion_scores = deque(maxlen=WINDOW_SIZE)

    # State tracking
    current_stage = "active"
    current_system_state = None
    last_state_change_time = 0
    last_critical_alert_time = 0
    last_heartbeat = 0
    last_status_log = 0

    try:
        while True:
            current_time = time.time()

            # Get latest data
            alcohol_data = core.get_data("alcohol_detected")
            vision_data = core.get_data("vision")
            hr_data = core.get_data("hr_sensor")
            env_data = core.get_data("env_sensor")
            pilot_profile = core.get_authenticated_pilot_profile()

            # PRIORITY 1: Alcohol detection (immediate override)
            if alcohol_data:
                alcohol_timestamp = alcohol_data.get("timestamp", 0)
                alcohol_age = current_time - alcohol_timestamp

                if alcohol_age < 10 and current_system_state != SystemState.ALCOHOL_DETECTED:
                    logger.critical(f"ALCOHOL DETECTED! Age: {alcohol_age:.1f}s")

                    core.set_system_state(
                        SystemState.ALCOHOL_DETECTED,
                        f"ALCOHOL DETECTED\n{alcohol_data.get('detection_time', 'Unknown')}",
                        pilot_username=None,
                        data={"alcohol_timestamp": alcohol_timestamp}
                    )
                    current_system_state = SystemState.ALCOHOL_DETECTED

                    if current_time - last_heartbeat > 10:
                        systemd.daemon.notify('WATCHDOG=1')
                        last_heartbeat = current_time
                    continue

            # PRIORITY 2: Fatigue detection
            if vision_data:
                # Validate vision data freshness and quality
                vision_timestamp = vision_data.get("timestamp", 0)
                vision_age = current_time - vision_timestamp

                # Check for valid data
                avg_ear = vision_data.get("avg_ear", 0)
                if vision_age > 5.0 or avg_ear <= 0 or avg_ear > 1.0:
                    # Invalid or stale data - skip
                    if current_time - last_status_log > 30:
                        logger.warning(f"Invalid vision data: age={vision_age:.1f}s, EAR={avg_ear:.3f}")
                        last_status_log = current_time

                    # Still send watchdog notification even with invalid data
                    if current_time - last_heartbeat > 10:
                        systemd.daemon.notify('WATCHDOG=1')
                        last_heartbeat = current_time

                    time.sleep(0.1)
                    continue

                # Calculate fusion score
                fusion_score, confidence, is_critical = predictor.calculate_fusion_score(vision_data, hr_data)

                # Publish fusion data with enhanced HR metrics
                fusion_data = {
                    "fusion_score": fusion_score,
                    "confidence": confidence,
                    "is_critical_event": is_critical,
                    # Vision metrics
                    "avg_ear": avg_ear,
                    "mar": vision_data.get("mar", 0.25),
                    "eyes_closed": vision_data.get("eyes_closed", False),
                    "closure_duration": vision_data.get("closure_duration", 0),
                    "microsleep_count": vision_data.get("microsleep_count", 0),
                    "blink_rate": vision_data.get("blink_rate_per_minute", 0),
                    "yawning": vision_data.get("yawning", False),
                    "yawn_count": vision_data.get("yawn_count", 0),
                    "yawn_duration": vision_data.get("yawn_duration", 0.0),
                    # Enhanced HR metrics
                    "hr": hr_data.get("hr") if hr_data else None,
                    "stress_index": hr_data.get("stress_index") if hr_data else None,
                    "rmssd": hr_data.get("rmssd") if hr_data else None,
                    "hr_trend": hr_data.get("hr_trend") if hr_data else None,
                    "baseline_deviation": hr_data.get("baseline_deviation") if hr_data else None,
                    # Timestamps
                    "vision_timestamp": vision_timestamp,
                    "hr_timestamp": hr_data.get("timestamp") if hr_data else None
                }

                core.publish_data("fusion", fusion_data)

                # Add to window
                fusion_scores.append((fusion_score, confidence))

                # Process if sufficient data
                if len(fusion_scores) >= 3:
                    # Calculate weighted average (recent bias)
                    weights = [0.5, 0.3, 0.2][:len(fusion_scores)]
                    weights = weights[::-1]  # Reverse for recent-first

                    avg_score = sum(score * weight for (score, conf), weight in zip(fusion_scores, weights))
                    avg_score /= sum(weights)

                    avg_confidence = sum(conf for score, conf in fusion_scores) / len(fusion_scores)

                    # Get thresholds
                    thresholds = get_personalized_thresholds(pilot_profile)

                    # Determine stage
                    new_stage = determine_fatigue_stage(avg_score, thresholds, avg_confidence, current_stage)

                    # CRITICAL PATH: Immediate state change for critical events
                    if is_critical:
                        time_since_last_critical = current_time - last_critical_alert_time

                        # Force escalation on critical events (bypass normal rate limiting)
                        if new_stage in ["severe", "moderate"] and time_since_last_critical >= MAX_CRITICAL_ALERT_RATE:
                            # Build critical event details
                            yawn_info = f" | Yawns: {vision_data.get('yawn_count', 0)}" if vision_data.get('yawn_count', 0) > 0 else ""

                            hr_info = ""
                            if hr_data:
                                stress = hr_data.get('stress_index')
                                rmssd = hr_data.get('rmssd')
                                trend = hr_data.get('hr_trend')

                                if stress is not None and stress >= CRITICAL_STRESS_INDEX:
                                    hr_info += f" | STRESS: {stress:.2f}"
                                if rmssd is not None and rmssd < CRITICAL_RMSSD_LOW:
                                    hr_info += f" | HRV: {rmssd:.0f}ms"
                                if trend is not None and trend > CRITICAL_HR_TREND:
                                    hr_info += f" | HR↑: {trend:.1f}bpm/min"

                            logger.warning(f"CRITICAL EVENT! Immediate escalation to {new_stage} | "
                                         f"EAR: {avg_ear:.3f} | Closure: {vision_data.get('closure_duration', 0):.1f}s"
                                         f"{yawn_info}{hr_info}")

                            current_stage = new_stage
                            last_state_change_time = current_time
                            last_critical_alert_time = current_time

                            # Publish alert
                            alert_data = {
                                "stage": new_stage,
                                "fusion_score": avg_score,
                                "confidence": avg_confidence,
                                "is_critical": True,
                                "pilot_username": pilot_profile.username if pilot_profile else None
                            }
                            core.publish_data("fatigue_alert", alert_data)

                    # NORMAL PATH: Rate-limited state changes with hysteresis
                    elif new_stage != current_stage:
                        time_since_last_change = current_time - last_state_change_time

                        # Apply rate limiting for normal transitions
                        if time_since_last_change >= MIN_STATE_DURATION:
                            logger.info(f"Fatigue stage change: {current_stage} → {new_stage} | "
                                      f"Score: {avg_score:.3f} | Confidence: {avg_confidence:.2f} | "
                                      f"EAR: {avg_ear:.3f} | Blink: {int(fusion_data['blink_rate'])}")

                            current_stage = new_stage
                            last_state_change_time = current_time

                            # Publish alert
                            alert_data = {
                                "stage": new_stage,
                                "fusion_score": avg_score,
                                "confidence": avg_confidence,
                                "is_critical": False,
                                "pilot_username": pilot_profile.username if pilot_profile else None
                            }
                            core.publish_data("fatigue_alert", alert_data)

                    # Update system state display
                    hr_reading = hr_data.get("hr") if hr_data else "N/A"
                    temp_reading = int(float(env_data.get("temp", 0))) if env_data and env_data.get("temp") else "N/A"
                    humidity_reading = int(float(env_data.get("humidity", 0))) if env_data and env_data.get("humidity") else "N/A"

                    # State messages
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

                    # Format display
                    ear_display = f"{avg_ear:.2f}".lstrip('0') if avg_ear < 1.0 else f"{avg_ear:.2f}"
                    blink_rate = vision_data.get("blink_rate_per_minute", 0)

                    display_message = f"{state_line}\n{ear_display} {int(blink_rate)} {temp_reading} {humidity_reading}"

                    # Update state if changed
                    if current_system_state != state_enum:
                        core.set_system_state(
                            state_enum,
                            display_message,
                            pilot_username=pilot_profile.username if pilot_profile else None,
                            data={"fusion_score": avg_score, "confidence": avg_confidence}
                        )
                        current_system_state = state_enum

                    # Periodic status logging (every 5 seconds)
                    if current_time - last_status_log > 5:
                        yawn_count = vision_data.get("yawn_count", 0)
                        yawn_status = f" | Yawns: {yawn_count}" if yawn_count > 0 else ""

                        # Enhanced HR status with bio_monitor metrics
                        hr_status = f" | HR: {hr_reading}"
                        if hr_data:
                            stress = hr_data.get('stress_index')
                            rmssd = hr_data.get('rmssd')
                            if stress is not None:
                                hr_status += f" | Stress: {stress:.2f}"
                            if rmssd is not None:
                                hr_status += f" | HRV: {rmssd:.0f}ms"

                        logger.info(f"Status: {current_stage.upper()} | Score: {avg_score:.3f} | "
                                  f"Confidence: {avg_confidence:.2f} | EAR: {avg_ear:.3f} | "
                                  f"Blink: {int(blink_rate)}{hr_status}{yawn_status}")
                        last_status_log = current_time

            # Watchdog heartbeat
            if current_time - last_heartbeat > 10:
                systemd.daemon.notify('WATCHDOG=1')
                last_heartbeat = current_time

            # Controlled loop rate (10Hz)
            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("Simplified Predictor service stopping...")
        core.shutdown()


if __name__ == "__main__":
    main()
