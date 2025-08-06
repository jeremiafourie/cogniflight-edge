# Predictor Service

The Predictor service performs integrated data fusion and fatigue stage classification. It directly subscribes to vision and heart rate data, calculates fusion scores internally, and applies sliding window analysis with personalized thresholds to provide accurate, pilot-specific fatigue detection.

## Key Features

- **Integrated Data Fusion**: Real-time fusion based on EAR, closure duration, microsleeps, and blink patterns (50% EAR, 30% closure, 15% microsleeps, 5% blink + optional 25% HR)
- **Sliding Window Analysis**: 2-sample moving average for faster response
- **Personalized Thresholds**: Pilot-specific sensitivity settings
- **Progressive Alert Stages**: Four-stage fatigue classification system
- **State Management**: Automatic system state updates with LCD messages
- **2-Second Processing**: Continuous analysis with prediction every 2 seconds

## Inputs

### CogniCore Data Sources
- **`vision`**: Real-time vision processing data for fusion calculation
  ```json
  {
    "avg_ear": 0.25,
    "eyes_closed": false,
    "closure_duration": 0.0,
    "microsleep_count": 0,
    "blink_rate_per_minute": 15.0,
    "timestamp": 1234567890.123
  }
  ```
- **`hr_sensor`**: Heart rate data (optional) for multimodal fusion
  ```json
  {
    "hr": 72,
    "timestamp": 1234567890.125
  }
  ```

### Pilot Profile Data
- **Alert Sensitivity**: "high", "medium", or "low" sensitivity setting
- **Pilot ID**: For personalized threshold calculation
- **Medical Conditions**: May influence threshold adjustments

## Processing

### 1. LEAN Data Fusion Processing
```python
def main():
    """Main predictor service loop"""
    fusion_scores = deque(maxlen=WINDOW_SIZE)  # Size = 2 for faster response
    current_stage = "active"
    
    while True:
        # Get latest vision and HR data directly
        vision_data = core.get_data("vision")
        hr_data = core.get_data("hr")
        
        if vision_data:
            # Calculate fusion score directly
            fusion_score = calculate_fusion_score(vision_data, hr_data)
            fusion_scores.append(fusion_score)
            
            # Only predict when we have enough data
            if len(fusion_scores) >= 3:
                avg_score = sum(fusion_scores) / len(fusion_scores)
                # ... continue with prediction
```

### 2. Personalized Threshold Calculation
```python
def get_personalized_thresholds(pilot_profile):
    """Get thresholds based on pilot profile"""
    thresholds = {
        "mild": DEFAULT_THRESHOLD_MILD,      # 0.3
        "moderate": DEFAULT_THRESHOLD_MOD,   # 0.6
        "severe": DEFAULT_THRESHOLD_SEVERE   # 0.8
    }
    
    if pilot_profile:
        sensitivity = pilot_profile.get("alert_sensitivity", "medium").lower()
        
        if sensitivity == "high":
            # Lower thresholds = more sensitive
            for key in thresholds:
                thresholds[key] *= 0.7
        elif sensitivity == "low":
            # Higher thresholds = less sensitive
            for key in thresholds:
                thresholds[key] *= 1.3
    
    return thresholds
```

### 3. Fatigue Stage Classification
```python
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
```

### 4. System State Updates
```python
# Check for stage change
if new_stage != current_stage:
    logger.info(f"Fatigue stage change: {current_stage} → {new_stage}")
    
    # Publish fatigue alert
    alert_data = {
        "stage": new_stage,
        "fusion_score": avg_score,
        "pilot_id": pilot_profile.pilot_id if pilot_profile else None,
        "threshold_used": thresholds.get(new_stage, 0),
        "blink_score": fusion_data.get("blink_score", 0),
        "yawn_score": fusion_data.get("yawn_score", 0)
    }
    
    core.publish_data("fatigue_alert", alert_data)
    
    # Update system state with display message
    state_messages = {
        "active": (SystemState.MONITORING_ACTIVE, "Monitoring Active"),
        "mild": (SystemState.ALERT_MILD, "⚠️ MILD FATIGUE\nScore: {:.2f}".format(avg_score)),
        "moderate": (SystemState.ALERT_MODERATE, "⚠️ MODERATE FATIGUE\nScore: {:.2f}".format(avg_score)),
        "severe": (SystemState.ALERT_SEVERE, "🚨 SEVERE FATIGUE\nScore: {:.2f}".format(avg_score))
    }
    
    if new_stage in state_messages:
        state, message = state_messages[new_stage]
        core.set_system_state(state, message, pilot_id=pilot_profile.pilot_id)
```

## Outputs

### CogniCore Publications

#### `fatigue_alert` Data Hash
```json
{
  "stage": "mild",
  "fusion_score": 0.35,
  "pilot_id": "pilot123",
  "threshold_used": 0.3,
  "blink_score": 0.234,
  "yawn_score": 0.056
}
```

### System State Changes
- **SystemState.MONITORING_ACTIVE**: Normal operation, no fatigue detected
- **SystemState.ALERT_MILD**: Early fatigue warning (fusion ~0.3)
- **SystemState.ALERT_MODERATE**: Escalated fatigue warning (fusion ~0.6)
- **SystemState.ALERT_SEVERE**: Critical fatigue alert (fusion ~0.8)

## Fatigue Classification System

### Stage Definitions

1. **Active** (< 0.3): Normal alertness level
   - **Indicators**: Normal blink patterns, no yawning
   - **Action**: Continue monitoring
   - **Display**: "Monitoring Active"

2. **Mild** (0.3-0.6): Early fatigue indicators
   - **Indicators**: Slightly increased blink duration or frequency
   - **Action**: Early warning to pilot
   - **Display**: "⚠️ MILD FATIGUE\nScore: X.XX"

3. **Moderate** (0.6-0.8): Significant fatigue detected
   - **Indicators**: Extended eye closures, occasional yawning
   - **Action**: Clear warning, recommend rest
   - **Display**: "⚠️ MODERATE FATIGUE\nScore: X.XX"

4. **Severe** (> 0.8): Critical fatigue requiring immediate attention
   - **Indicators**: Prolonged blinks, frequent yawning
   - **Action**: Urgent alert, immediate intervention required
   - **Display**: "🚨 SEVERE FATIGUE\nScore: X.XX"

### Threshold Personalization

#### Default Thresholds
```python
DEFAULT_THRESHOLD_MILD = 0.3
DEFAULT_THRESHOLD_MOD = 0.6
DEFAULT_THRESHOLD_SEVERE = 0.8
```

#### Sensitivity Adjustments
- **High Sensitivity**: Thresholds × 0.7 (more sensitive, earlier alerts)
- **Medium Sensitivity**: Default thresholds (balanced approach)
- **Low Sensitivity**: Thresholds × 1.3 (less sensitive, fewer false positives)

## Configuration

### Window Parameters
```python
WINDOW_SIZE = 2                    # Sliding window size
DEFAULT_HYSTERESIS = 0.05         # Prevents alert flapping
```

### Processing Parameters
```python
PROCESSING_INTERVAL = 2.0         # Check every 2 seconds
HEARTBEAT_INTERVAL = 10.0         # Watchdog heartbeat frequency
```

### Personalization Settings
```python
SENSITIVITY_MULTIPLIERS = {
    "high": 0.7,      # More sensitive
    "medium": 1.0,    # Default
    "low": 1.3        # Less sensitive
}
```

## Performance

- **Processing Latency**: <1ms for stage determination
- **Memory Usage**: ~5MB minimal footprint
- **CPU Usage**: <1% on Raspberry Pi 4
- **Update Frequency**: Every 2 seconds (configurable)
- **Window Stability**: 2-sample average provides stable predictions

## Error Handling

### Missing Fusion Data
- **Graceful Degradation**: Continue with last known state
- **Timeout Handling**: Switch to error state if no data for extended period
- **Recovery**: Resume normal operation when data returns

### Profile Loading Failures
- **Default Thresholds**: Fall back to medium sensitivity defaults
- **Error Logging**: Log profile access issues
- **Continued Operation**: System continues with reduced personalization

### State Change Failures
- **Retry Logic**: Attempt state updates multiple times
- **Fallback Messaging**: Use generic messages if personalization fails
- **System Stability**: Maintain core functionality despite minor failures

## Dependencies

### Service Dependencies
- **Vision Processing**: Must be active for vision data generation  
- **HR Monitor**: Provides heart rate data for multimodal fusion (optional)
- **HTTPS Client**: Must set active pilot for proper operation

### Library Dependencies
- **CogniCore**: Redis communication and state management
- **Collections**: Deque for sliding window implementation
- **Standard Libraries**: Time, logging, mathematical operations

## Usage

The service runs as a systemd unit with continuous monitoring:

1. **Startup**: Initialize CogniCore and load pilot profile
2. **Monitor**: Continuously check for fusion score updates
3. **Analyze**: Apply sliding window analysis when sufficient data available
4. **Classify**: Determine fatigue stage using personalized thresholds
5. **Alert**: Update system state and publish fatigue alerts on stage changes

## Logging

Comprehensive logging includes:
- Fatigue stage changes and fusion scores
- Personalized threshold calculations
- Sliding window analysis results
- System state update confirmations
- Error conditions and recovery actions

## File Structure

```
predictor/
├── main.py           # Main service implementation
├── README.md         # This documentation
└── systemd/          # Service configuration files
```

## Integration

### Upstream Services  
- **Vision Processing**: Provides EAR/MAR data for fusion calculation
- **HR Monitor**: Provides heart rate data for multimodal fusion (optional)
- **HTTPS Client**: Provides pilot profiles for personalization

### Downstream Services
- **Alert Manager**: Receives system state changes for display
- **Network Connector**: Receives fatigue alerts for telemetry

### Supporting Services
- **CogniCore**: Manages system state and data communication
- **Watchdog**: Monitors service health via heartbeat
