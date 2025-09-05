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
| **temp**                  | Environment | -40 to +50°C       | Medium         | Cabin temperature - extremes increase fatigue    |
| **humidity**              | Environment | 5-95%              | Medium         | Humidity - <20% or >80% affects comfort          |
| **avg_ear**               | Vision      | 0.05-0.6           | **Critical**   | Eye aspect ratio - <0.20 = eyes closing          |
| **eyes_closed**           | Vision      | true/false         | **Critical**   | Boolean eye closure state                        |
| **closure_duration**      | Vision      | 0-60s              | **Critical**   | Time eyes stay closed - >1s = microsleep         |
| **microsleep_count**      | Vision      | 0-100              | **Critical**   | Number of 1+ second eye closures                 |
| **blink_rate_per_minute** | Vision      | 5-40 blinks/min    | Medium         | Abnormal rates indicate fatigue                  |
| **accel_x**               | MPU9250     | -16 to +16g        | Medium         | X-axis acceleration                              |
| **accel_y**               | MPU9250     | -16 to +16g        | Medium         | Y-axis acceleration                              |
| **accel_z**               | MPU9250     | -16 to +16g        | Medium         | Z-axis acceleration - vibration indicator        |
| **gyro_x**                | MPU9250     | -2000 to +2000°/s  | **High**       | Roll rate - excessive = loss of control          |
| **gyro_y**                | MPU9250     | -2000 to +2000°/s  | **High**       | Pitch rate - sudden changes = alertness issue    |
| **gyro_z**                | MPU9250     | -2000 to +2000°/s  | Medium         | Yaw rate                                          |
| **mag_x**                 | MPU9250     | -4800 to +4800μT   | Low            | X-axis magnetic field                            |
| **mag_y**                 | MPU9250     | -4800 to +4800μT   | Low            | Y-axis magnetic field                            |
| **mag_z**                 | MPU9250     | -4800 to +4800μT   | Low            | Z-axis magnetic field                            |
| **heading**               | MPU9250     | 0-360°             | Low            | Compass heading from magnetometer                |
| **pressure**              | BMP280      | 200-1100 hPa       | Low            | Atmospheric pressure (up to FL200)               |
| **altitude**              | BMP280      | -500 to 6100m      | Medium         | Pressure altitude (up to 20,000 ft)              |
| **altitude_change_rate**  | BMP280      | -100 to +100 m/min | **High**       | Rapid altitude changes = critical situation      |
| **fusion_score**          | System      | 0.0-1.0            | **Critical**   | Combined fatigue assessment from all sensors     |

## Fatigue Levels

| Fusion Score | Level    | Description                           | Recommended Action         |
| ------------ | -------- | ------------------------------------- | -------------------------- |
| 0.0-0.3      | Active   | Pilot is alert and performing well   | Continue normal monitoring |
| 0.3-0.6      | Mild     | Early signs of fatigue detected       | Increased attention needed |
| 0.6-0.8      | Moderate | Clear fatigue indicators present      | Consider rest/intervention |
| 0.8-1.0      | Severe   | Critical fatigue - immediate risk    | Immediate action required  |

## Critical Thresholds

| Metric                | Critical Value       | Alert Type | Description                           |
| -------------------- | -------------------- | ---------- | ------------------------------------- |
| Eye Closure          | > 3 seconds          | CRITICAL   | Likely falling asleep                |
| Microsleep           | Any occurrence       | CRITICAL   | 1+ second involuntary sleep          |
| HRV (RMSSD)          | < 20ms for 5+ min    | WARNING    | Severe fatigue/stress                |
| Temperature          | < -20°C or > 40°C    | WARNING    | Extreme cabin temperature             |
| Heart Rate Deviation | > 50% from baseline  | WARNING    | Significant physiological change      |
| Altitude Change      | > 50 m/min unplanned | CRITICAL   | Unexpected altitude change            |
| Angular Velocity     | > 500°/s (any axis)  | CRITICAL   | Excessive rotation - loss of control  |
| Vibration (accel_z)  | > 4g sustained       | WARNING    | Excessive vibration affecting pilot   |
| Cabin Pressure       | < 500 hPa            | CRITICAL   | Dangerous low pressure (hypoxia risk) |

## Data Collection Notes

- **Sampling Rates**: HR @ 1Hz, Vision @ 10Hz, Environment @ 0.5Hz, MPU9250 @ 100Hz, BMP280 @ 1Hz
- **Baseline Period**: First 60 seconds used for HR/HRV baseline calibration
- **Fusion Algorithm**: Weighted average with emphasis on vision (40%), HR (30%), motion (20%), environment (10%)
- **Alert Priority**: Critical > High > Medium > Low impact metrics
- **Confidence Score**: Requires minimum 3 active sensor types for reliable fusion score
- **Aviation Note**: Temperature/pressure ranges account for unpressurized cabins up to 20,000ft service ceiling typical of single-prop aircraft
