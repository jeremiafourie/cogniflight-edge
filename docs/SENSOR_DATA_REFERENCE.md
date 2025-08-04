# CogniFlight Edge - Sensor Data Reference

## All Sensor Fields & Fatigue Impact

| Field                     | Source      | Value Range        | Fatigue Impact | Description                                      |
| ------------------------- | ----------- | ------------------ | -------------- | ------------------------------------------------ |
| **hr**                    | HR Monitor  | 40-200 BPM         | Medium         | Heart rate - elevated indicates stress/alertness |
| **rr_interval**           | HR Monitor  | 0.4-2.0s           | Low            | Beat-to-beat interval for HRV calculation        |
| **baseline_deviation**    | HR Monitor  | 0.0-1.0            | Medium         | % deviation from pilot's baseline HR             |
| **rmssd**                 | HR Monitor  | 10-200ms           | **High**       | Heart rate variability - lower = more fatigued   |
| **hr_trend**              | HR Monitor  | -20 to +20 BPM/min | Medium         | HR change rate - rapid increases indicate stress |
| **stress_index**          | HR Monitor  | 0.0-1.0            | **High**       | Combined HR/HRV stress indicator                 |
| **baseline_hr**           | HR Monitor  | 50-100 BPM         | Low            | Reference baseline for comparison                |
| **baseline_hrv**          | HR Monitor  | 20-80ms            | Low            | Reference HRV baseline                           |
| **temp**                  | Environment | 10-40°C            | Medium         | Temperature - >25°C increases fatigue            |
| **humidity**              | Environment | 20-90%             | Medium         | Humidity - >70% or <30% affects comfort          |
| **avg_ear**               | Vision      | 0.05-0.6           | **Critical**   | Eye aspect ratio - <0.20 = eyes closing          |
| **eyes_closed**           | Vision      | true/false         | **Critical**   | Boolean eye closure state                        |
| **closure_duration**      | Vision      | 0-60s              | **Critical**   | Time eyes stay closed - >1s = microsleep         |
| **microsleep_count**      | Vision      | 0-100              | **Critical**   | Number of 1+ second eye closures                 |
| **blink_rate_per_minute** | Vision      | 5-40/min           | Medium         | Blink frequency - <10 or >30 abnormal            |
| **fusion_score**          | Predictor   | 0.0-1.0            | **Critical**   | Combined fatigue score from all sensors          |

## Fatigue Level Classification

| Fusion Score | Fatigue Level | Action Required     |
| ------------ | ------------- | ------------------- |
| 0.0 - 0.3    | **Active**    | Normal monitoring   |
| 0.3 - 0.6    | **Mild**      | Increased attention |
| 0.6 - 0.8    | **Moderate**  | Warning alerts      |
| 0.8 - 1.0    | **Severe**    | Immediate action    |

## Critical Thresholds

| Metric        | Warning Level | Critical Level |
| ------------- | ------------- | -------------- |
| EAR (avg_ear) | < 0.25        | < 0.20         |
| Eye Closure   | > 0.5s        | > 1.0s         |
| Microsleeps   | 1 event       | 3+ events      |
| HRV (RMSSD)   | < 30ms        | < 20ms         |
| Temperature   | > 26°C        | > 30°C         |
| HR Deviation  | > 15%         | > 25%          |

## Data Summary

**Most Critical for Safety:** EAR, closure_duration, microsleep_count, fusion_score  
**Most Predictive:** RMSSD (HRV), stress_index, temperature  
**Fastest Updates:** Vision data (30fps), HR data (real-time)  
**Environmental Impact:** Temperature >25°C and humidity >70% compound fatigue effects
