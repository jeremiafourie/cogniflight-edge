# HTTPS Client Service

The HTTPS Client service manages pilot profile retrieval and authentication with external cloud services. It responds to pilot identification requests from the face recognition system, fetches pilot profiles, and publishes them to CogniCore for system-wide access.

## Key Features

- **Reactive Profile Loading**: Responds to pilot ID requests from face recognition
- **Cloud API Integration**: Secure HTTPS communication with profile backend
- **Persistent Profile Storage**: Redis-based profile storage that survives restarts
- **Authentication Management**: Secure pilot profile access and validation
- **Error Recovery**: Robust handling of network and API failures

## Inputs

### CogniCore Subscriptions

- **`pilot_id_request`**: Pilot identification requests from face recognition
  ```json
  {
    "pilot_id": "pilot123",
    "confidence": 0.856,
    "timestamp": 1234567890.123,
    "source": "face_recognition"
  }
  ```

### Cloud API Data

- **Pilot Profile API**: RESTful API providing pilot profile data
- **Authentication Tokens**: API keys or JWT tokens for secure access
- **Profile Database**: Remote pilot profile storage

## Processing

### 1. Reactive Profile Requests with Offline Fallback

```python
def on_pilot_id_request(self, hash_name, request_data):
    """Handle pilot ID requests from face recognition service"""
    pilot_id = request_data.get("pilot_id")
    confidence = request_data.get("confidence", 0.0)

    try:
        # Try server first
        profile_data = fetch_pilot_profile(self.core, pilot_id)

        if profile_data:
            # Server fetch successful - overwrite existing pilot data
            self.logger.info(f"Fetched online profile for {pilot_id}")
            save_pilot_profile_cache(self.core, pilot_id, profile_data, confidence, self.logger)

            # Save profile to CogniCore and activate
            if save_pilot_profile_to_cognicore(self.core, pilot_id, profile_data, confidence, self.logger):
                self.logger.info(f"Profile updated and activated for {pilot_id}")
        else:
            # Server offline - check if pilot already exists
            existing_pilot = self.core.get_pilot_profile(pilot_id)

            if existing_pilot:
                # Pilot exists - just activate without overwriting data
                self.logger.info(f"Found existing pilot {pilot_id} - activating")
                if self.core.set_pilot_active(pilot_id, active=True):
                    self.core.set_system_state(
                        SystemState.SCANNING,
                        f"Welcome {pilot_id}\\nProfile active",
                        pilot_id=pilot_id
                    )
            else:
                # Try cache as last resort
                cached_result = get_pilot_profile_from_cache(self.core, pilot_id, self.logger)
                if cached_result:
                    _, profile_data = cached_result
                    save_pilot_profile_to_cognicore(self.core, pilot_id, profile_data, confidence, self.logger)
                else:
                    # No profile found anywhere
                    self.core.set_system_state(SystemState.SCANNING, "Pilot not found\\nScanning...")

        self._clear_pilot_id_request()
```

### 2. Cloud API Communication

```python
def fetch_pilot_profile(pilot_id: str) -> Optional[Dict]:
    """Fetch pilot profile from cloud API with fallback to local cache"""
    try:
        # Try cloud API first
        response = requests.get(
            f"{API_BASE_URL}/pilots/{pilot_id}",
            headers={"Authorization": f"Bearer {API_TOKEN}"},
            timeout=10
        )

        if response.status_code == 200:
            profile_data = response.json()

            # Cache profile locally for offline access
            core.cache_pilot_profile(pilot_id, profile_data)

            return create_pilot_profile_object(profile_data)

    except requests.RequestException as e:
        logger.warning(f"API request failed: {e}")

    # Fallback to local cache
    return load_cached_profile(pilot_id)
```

### 3. Profile Data Processing

```python
def create_pilot_profile_object(profile_data: dict) -> PilotProfile:
    """Create PilotProfile object from API response"""
    return PilotProfile(
        id=profile_data.get('id', profile_data.get('pilot_id')),
        name=profile_data['name'],
        flightHours=profile_data.get('flightHours', profile_data.get('flight_history', {}).get('total_hours', 0)),
        baseline=profile_data.get('baseline', {"heart_rate": 70, "heart_rate_variability": 50}),
        environmentPreferences=profile_data.get('environmentPreferences', {
            "cabinTemperaturePreferences": {
                "optimalTemperature": 22,
                "toleranceRange": 3
            },
            "noiseSensitivity": "medium",
            "lightSensitivity": "medium"
        })
    )
```

## Outputs

### CogniCore Publications

#### Pilot Profile Storage and Activation

- **Method**: `core.set_pilot_profile(pilot_profile, activate=True)` - stores profile and activates pilot
- **Fallback**: If server fails but pilot exists, use `core.set_pilot_active(pilot_id, active=True)`
- **Triggers**: Vision Processing and other services react to `pilot:{pilot_id}` activation
- **Storage**: Persistent Redis storage that survives service restarts

#### System State Updates

- **Success**: No immediate state change - predictor service handles state transitions based on fatigue
- **Failure**: Sets `SystemState.SCANNING` with "Pilot not found" message

### Profile Data Structure

```json
{
  "id": "pilot123",
  "name": "John Doe",
  "flightHours": 2500.0,
  "baseline": {
    "heart_rate": 72,
    "heart_rate_variability": 50
  },
  "environmentPreferences": {
    "cabinTemperaturePreferences": {
      "optimalTemperature": 22,
      "toleranceRange": 3
    },
    "noiseSensitivity": "medium",
    "lightSensitivity": "low"
  }
}
```

## Cloud API Integration

### API Endpoints

```python
# Profile retrieval endpoint
GET /api/v1/pilots/{pilot_id}

# Response format
{
  "id": "string",
  "name": "string",
  "flightHours": "number",
  "baseline": {
    "heart_rate": "number",
    "heart_rate_variability": "number"
  },
  "environmentPreferences": {
    "cabinTemperaturePreferences": {
      "optimalTemperature": "number",
      "toleranceRange": "number"
    },
    "noiseSensitivity": "string",
    "lightSensitivity": "string"
  },
  "last_updated": "2023-07-23T12:34:56Z"
}
```

### Authentication

```python
# API authentication headers
headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json",
    "X-API-Key": cfg.API_KEY
}
```

### Error Handling

- **Network Failures**: Automatic fallback to local cache
- **API Errors**: Log error, continue with cached data
- **Timeout**: 10-second request timeout with retry logic
- **Rate Limiting**: Respect API rate limits and retry after delays

## Local Caching

### Cache Strategy

```python
def cache_pilot_profile(pilot_id: str, profile_data: dict):
    """Cache pilot profile locally for offline access"""
    cache_key = f"pilot_profile:{pilot_id}"

    # Store with TTL (24 hours)
    core._redis_client.setex(
        cache_key,
        86400,  # 24 hours
        json.dumps(profile_data)
    )

    logger.info(f"Cached profile for pilot: {pilot_id}")
```

### Cache Retrieval

```python
def load_cached_profile(pilot_id: str) -> Optional[PilotProfile]:
    """Load pilot profile from local cache"""
    cache_key = f"pilot_profile:{pilot_id}"

    try:
        cached_data = core._redis_client.get(cache_key)
        if cached_data:
            profile_data = json.loads(cached_data)
            logger.info(f"Using cached profile for pilot: {pilot_id}")
            return create_pilot_profile_object(profile_data)
    except Exception as e:
        logger.error(f"Cache retrieval failed: {e}")

    return None
```

## Configuration

### API Settings

```python
API_BASE_URL = "https://api.cogniflight.com"
API_TOKEN = "your_api_token_here"
API_TIMEOUT = 10                    # seconds
MAX_RETRIES = 3                     # API retry attempts
```

### Service Parameters

```python
MIN_CONFIDENCE_THRESHOLD = 0.5      # Minimum face recognition confidence
CACHE_TTL = 86400                   # 24 hours cache expiration
HEARTBEAT_INTERVAL = 10             # Watchdog heartbeat frequency
SERVICE_NAME = "https_client"
```

## Error Handling

### Network Failures

```python
def handle_network_error(pilot_id: str, error: Exception):
    """Handle network communication failures"""
    logger.warning(f"Network error for pilot {pilot_id}: {error}")

    # Try local cache
    cached_profile = load_cached_profile(pilot_id)
    if cached_profile:
        logger.info(f"Using cached profile for offline operation")
        return cached_profile

    # No cache available
    logger.error(f"No cached profile available for pilot: {pilot_id}")
    return None
```

### API Response Errors

- **401 Unauthorized**: Check API token validity
- **404 Not Found**: Pilot not registered in system
- **429 Rate Limited**: Implement backoff and retry
- **500 Server Error**: Temporary API issues, use cache

### Profile Validation

```python
def validate_profile_data(profile_data: dict) -> bool:
    """Validate required profile fields"""
    required_fields = ['pilot_id', 'name']

    for field in required_fields:
        if field not in profile_data:
            logger.error(f"Missing required field: {field}")
            return False

    return True
```

## Performance

- **API Response Time**: ~200-500ms for profile retrieval
- **Cache Access**: <10ms for local profile access
- **Memory Usage**: ~10MB including HTTP client libraries
- **CPU Usage**: <2% during profile operations
- **Network Bandwidth**: Minimal (only on pilot changes)

## Security

### Data Protection

- **HTTPS Only**: All API communication encrypted
- **Token Authentication**: Secure API access with bearer tokens
- **Local Encryption**: Profile cache encrypted in Redis
- **Access Control**: Device-specific authentication

### Privacy Compliance

- **Local Processing**: Profile data cached locally
- **Data Minimization**: Only necessary profile fields retrieved
- **Secure Storage**: Encrypted local profile storage
- **Audit Logging**: All profile access logged

## Dependencies

- **Requests**: HTTP client library for API communication
- **CogniCore**: Redis communication and profile management
- **JSON**: Profile data serialization
- **Standard Libraries**: Time, logging, exception handling

### Network Requirements

- **Internet Connectivity**: Required for initial profile retrieval
- **HTTPS Support**: TLS 1.2+ for secure communication
- **DNS Resolution**: API endpoint resolution
- **Firewall**: Outbound HTTPS (port 443) access

## Usage

The service runs as a systemd unit with reactive operation:

1. **Startup**: Initialize API client and CogniCore subscriptions
2. **Wait**: Listen for pilot identification requests
3. **Fetch**: Retrieve pilot profile from API or cache
4. **Publish**: Make profile available system-wide via CogniCore
5. **Cache**: Store profile locally for offline access

## Logging

Comprehensive logging includes:

- Pilot identification requests and responses
- API communication status and errors
- Profile caching operations
- Authentication and security events
- Performance metrics and timing

## Troubleshooting

### Common Issues

1. **API Connection Failures**

   - Check internet connectivity and DNS resolution
   - Verify API endpoint URL and authentication token
   - Check firewall settings for HTTPS outbound

2. **Profile Not Found**

   - Verify pilot is registered in cloud database
   - Check pilot ID format and face recognition accuracy
   - Review API authentication and permissions

3. **Cache Issues**
   - Verify Redis connectivity for profile caching
   - Check cache TTL settings and expiration
   - Monitor cache storage usage and limits

## File Structure

```
https_client/
├── main.py           # Main service implementation
├── README.md         # This documentation
└── systemd/          # Service configuration files
```

## Integration

### Upstream Services

- **Face Recognition**: Provides pilot identification requests

### Downstream Services

- **HR Monitor**: Receives pilot profile with sensor MAC
- **Vision Processing**: Receives pilot activation signal
- **Predictor**: Receives pilot profile for personalized thresholds

### Supporting Services

- **CogniCore**: Provides profile storage and system communication
- **Watchdog**: Monitors service health via heartbeat
