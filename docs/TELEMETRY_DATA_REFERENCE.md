# CogniFlight Edge - MQTT Telemetry Data Reference

**Transmission Interval:** Every 2 seconds
**Protocol:** MQTT over TLS (port 8883)
**Topic:** `cogniflight/telemetry/{edge_username}`
**Format:** JSON payload with flattened structure

---

## Vision Processing Data

| Field | Value Range | Fatigue Impact | Description |
|-------|-------------|----------------|-------------|
| `avg_ear` | 0.0 - 0.4 | **High** (50% weight) | Average Eye Aspect Ratio - primary drowsiness indicator |
| `mar` | 0.0 - 1.0 | Low | Mouth Aspect Ratio - yawning detection |
| `eyes_closed` | true/false | High | Current eye closure state |
| `closure_duration` | 0.0+ seconds | **Critical** (30% weight) | Duration of current/last eye closure event |
| `microsleep_count` | 0+ integer | **Critical** (15% weight) | Count of 1+ second eye closures |
| `blink_rate` | 0.0+ per minute | Low (5% weight) | Blink frequency indicator |
| `yawning` | true/false | Low | Current yawn detection state |
| `yawn_count` | 0+ integer | Low | Total yawn count |
| `yawn_duration` | 0.0+ seconds | Low | Duration of current/last yawn |

---

## Cardiovascular Data

| Field | Value Range | Fatigue Impact | Description |
|-------|-------------|----------------|-------------|
| `heart_rate` | 40-220 BPM | Medium (25% weight) | Current heart rate |
| `rr_interval` | 273-1500 ms | Medium | Beat-to-beat interval |
| `rmssd` | 0.0+ ms | Medium | Root Mean Square of Successive Differences (HRV) |
| `baseline_deviation` | -∞ to +∞ BPM | Medium | Deviation from pilot baseline HR |
| `hr_trend` | -∞ to +∞ | Medium | Rate of HR change (stress detection) |
| `stress_index` | 0.0+ | Medium | Combined HR elevation + HRV reduction |

---

## Environmental Data

| Field | Value Range | Fatigue Impact | Description |
|-------|-------------|----------------|-------------|
| `temperature` | -40 to +85 °C | Low | Cabin temperature |
| `humidity` | 0-100% | Low | Relative humidity |
| `altitude` | 0.0 meters | None | Hardcoded ground level (testing) |
| `pressure` | 1013.25 hPa | None | Hardcoded sea level pressure (testing) |

---

## Inertial Measurement Unit (IMU)

| Field | Value Range | Fatigue Impact | Description |
|-------|-------------|----------------|-------------|
| `accel_x/y/z` | -16 to +16 g | None | Linear acceleration (m/s²) |
| `gyro_x/y/z` | -2000 to +2000 °/s | None | Angular velocity (rad/s) |
| `mag_x/y/z` | -4800 to +4800 µT | None | Magnetic field strength |
| `roll` | -180 to +180° | None | Aircraft roll angle |
| `pitch` | -90 to +90° | None | Aircraft pitch angle |
| `yaw` | 0 to 360° | None | Aircraft heading |

---

## Safety & Alerts

| Field | Value Range | Fatigue Impact | Description |
|-------|-------------|----------------|-------------|
| `alcohol_detected` | true/false | **Critical** | MQ3 sensor alcohol vapor detection |
| `fusion_score` | 0.0 - 1.0 | **Critical** | Combined fatigue prediction score |
| `confidence` | 0.0 - 1.0 | N/A | Prediction confidence level |
| `is_critical_event` | true/false | **Critical** | Severe fatigue or safety alert flag |

---

## System Metadata

| Field | Value Range | Fatigue Impact | Description |
|-------|-------------|----------------|-------------|
| `collection_time` | Unix timestamp | N/A | Data collection timestamp |
| `predictor_version` | String | N/A | Predictor algorithm version |
| `system_state` | Enum | N/A | Current system state (scanning, monitoring_active, alert_mild, etc.) |
| `state_message` | String | N/A | Human-readable state description |
| `pilot_username` | String | N/A | Authenticated pilot identifier |
| `flight_id` | String | N/A | Current flight session ID |

---

## Data Freshness

**Important:** Sensor data is only included if fresh (timestamp within 2 seconds). System state and pilot info are always included as they represent current state.

## Fatigue Scoring Weights

- **Vision Data:** 70% total weight
  - Eye Aspect Ratio: 40%
  - Closure Duration: 25%
  - Microsleep Count: 15%
  - Yawning Analysis: 15%
  - Blink Rate: 5%
- **Cardiovascular Data:** 30% total weight (when available)

**Fusion Score Thresholds:**
- **< 0.3:** Active (normal alertness)
- **0.3-0.6:** Mild fatigue
- **0.6-0.8:** Moderate fatigue
- **> 0.8:** Severe fatigue (critical)
