import os
import sys
import time
import json
import random
import requests
import threading
import logging
import pickle
import numpy as np
from pathlib import Path
import systemd.daemon

# Add parent directories to path for imports
sys.path.append(str(Path(__file__).parent.parent.parent))

# Import shared resources
try:
    from CogniCore import CogniCore, SystemState, config
    from CogniCore.state import PilotProfile
except ImportError as e:
    print(f"Failed to import CogniCore modules: {e}")
    sys.exit(1)

# Configuration constants
SERVER_BASE_URL = config.SERVER_BASE_URL
ENDPOINT_PILOT_PROFILE = config.ENDPOINT_PILOT_PROFILE
ENDPOINT_FACE_EMBEDDINGS = config.ENDPOINT_FACE_EMBEDDINGS
EMBEDDINGS_FILE = config.EMBEDDINGS_FILE
API_KEY = config.API_KEY

# Service configuration
SERVICE_NAME = "https_client"
MAX_RETRIES = 2
BASE_DELAY = 1
JITTER = 0.1
HEARTBEAT_INTERVAL = 5


# Global heartbeat tracking
last_heartbeat = 0


def save_pilot_profile_cache(core, pilot_id, profile_data, confidence, logger):
    """Save pilot profile cache data to Redis"""
    try:
        cache_data = {
            "pilot_id": pilot_id,
            "profile_data": profile_data,
            "confidence": confidence,
            "fetched_at": time.time(),
            "cached_from_server": True
        }
        
        # Note: Pilot profiles are now stored persistently via set_pilot_profile()
        # No separate cache needed - pilot profiles serve as their own cache
        logger.info(f"Pilot profile cached: {pilot_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to cache profile in Redis: {e}")
        return False

def save_pilot_profile_to_cognicore(core, pilot_id, profile_data, confidence, logger):
    """Save pilot profile to CogniCore and activate"""
    try:
        # Create and store PilotProfile with activation
        pilot_profile = create_pilot_profile_from_data(profile_data)
        if not pilot_profile:
            return False
        
        # Set profile and activate (active=True by default)
        core.set_pilot_profile(pilot_profile, activate=True)
        core.set_system_state(
            SystemState.SCANNING,
            f"Welcome {pilot_id}\nProfile loaded",
            pilot_id=pilot_id,
            data={"profile_loaded": True}
        )
        
        logger.info(f"Pilot profile saved and active: {pilot_id}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to save profile: {e}")
        return False

def fetch_pilot_profile(core, pilot_id):
    """Fetch pilot profile from server with exponential backoff"""
    logger = core.get_logger(SERVICE_NAME)
    endpoint = ENDPOINT_PILOT_PROFILE.format(pilot_id=pilot_id)
    url = SERVER_BASE_URL + endpoint
    
    retry = 0
    while retry < MAX_RETRIES:
        try:
            logger.info(f"Attempting to fetch pilot profile for {pilot_id} from server")
            
            response = requests.get(url, timeout=5, verify=True)
            response.raise_for_status()
            
            profile_data = response.json()
            logger.info(f"Successfully fetched profile for pilot {pilot_id}")
            
            return profile_data
            
        except requests.exceptions.ConnectionError:
            logger.warning(f"Server connection failed for {pilot_id}: Server offline")
            break  # Don't retry connection errors in offline mode
        except requests.exceptions.Timeout:
            logger.warning(f"Server timeout for {pilot_id}: Server may be offline")
            break  # Don't retry timeouts in offline mode
        except requests.exceptions.RequestException as e:
            delay = BASE_DELAY * (2 ** retry)
            delay = delay * (1 + random.uniform(-JITTER, JITTER))
            logger.warning(f"Fetch attempt {retry+1} failed for {pilot_id}: {e}")
            if retry < MAX_RETRIES - 1:
                logger.info(f"Retrying in {delay:.1f}s")
                time.sleep(delay)
            retry += 1
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON response for pilot {pilot_id}: {e}")
            break
        except Exception as e:
            logger.error(f"Unexpected error fetching profile for {pilot_id}: {e}")
            break
    
    logger.info(f"Server offline - using local storage for {pilot_id}")
    return None

def create_pilot_profile_from_data(pilot_data):
    """Convert profile data to CogniCore PilotProfile"""
    defaults = {
        "baseline": {"heart_rate": 70, "heart_rate_variability": 50},
        "environmentPreferences": {
            "cabinTemperaturePreferences": {"optimalTemperature": 22, "toleranceRange": 3},
            "noiseSensitivity": "medium",
            "lightSensitivity": "medium"
        }
    }
    
    try:
        pilot_id = pilot_data.get("id", pilot_data.get("pilot_id", "unknown"))
        return PilotProfile(
            id=pilot_id,
            name=pilot_data.get("name", pilot_id),
            flightHours=pilot_data.get("flightHours", pilot_data.get("flight_history", {}).get("total_hours", 0)),
            baseline=pilot_data.get("baseline", defaults["baseline"]),
            environmentPreferences=pilot_data.get("environmentPreferences", defaults["environmentPreferences"])
        )
    except Exception:
        return None

def get_pilot_profile_from_cache(core, pilot_id, logger):
    """Get pilot profile from persistent storage (no separate cache needed)"""
    try:
        # Check if pilot profile already exists (persistent storage)
        existing_pilot = core.get_pilot_profile(pilot_id)
        if existing_pilot:
            logger.info(f"Found existing pilot profile for {pilot_id}")
            # Convert PilotProfile back to dict format for compatibility
            profile_data = {
                'id': existing_pilot.id,
                'name': existing_pilot.name,
                'flightHours': existing_pilot.flightHours,
                'baseline': existing_pilot.baseline,
                'environmentPreferences': existing_pilot.environmentPreferences
            }
            return (pilot_id, profile_data)
        return None
    except Exception as e:
        logger.error(f"Error retrieving pilot profile: {e}")
        return None

def load_pilot_embeddings_from_file(logger):
    """Load pilot embeddings from local pkl file as fallback"""
    try:
        if os.path.exists(EMBEDDINGS_FILE):
            with open(EMBEDDINGS_FILE, 'rb') as f:
                embeddings_data = pickle.load(f)
            logger.info(f"Loaded {len(embeddings_data)} pilot embeddings from file: {list(embeddings_data.keys())}")
            return embeddings_data
        else:
            logger.warning(f"Pilot embeddings file not found at {EMBEDDINGS_FILE}")
            return {}
    except Exception as e:
        logger.error(f"Failed to load pilot embeddings from file: {e}")
        return {}

def get_existing_pilot_embeddings(core, logger):
    """Get currently stored pilot embeddings from CogniCore to avoid duplicates"""
    try:
        existing_embeddings = {}
        redis_client = core._redis_client
        
        # Get all embedding keys
        embedding_keys = redis_client.keys("cognicore:data:embedding:*")
        
        for key in embedding_keys:
            # Extract pilot_id from key: "cognicore:data:embedding:pilot_id"
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            pilot_id = key_str.split(":")[-1]
            embedding_data = core.get_data(f'embedding:{pilot_id}')
            if embedding_data and 'embedding' in embedding_data:
                existing_embeddings[pilot_id] = embedding_data
        
        logger.info(f"Found {len(existing_embeddings)} existing pilot embeddings in CogniCore")
        return existing_embeddings
    except Exception as e:
        logger.error(f"Failed to get existing pilot embeddings: {e}")
        return {}

def store_pilot_embeddings_in_cognicore(core, embeddings_data, logger, source="file"):
    """Store pilot embeddings in CogniCore, avoiding duplicates"""
    try:
        # Get existing embeddings to avoid duplicates
        existing_embeddings = get_existing_pilot_embeddings(core, logger)
        
        stored_count = 0
        skipped_count = 0
        
        for pilot_id, embedding in embeddings_data.items():
            # Skip if embedding already exists
            if pilot_id in existing_embeddings:
                skipped_count += 1
                continue
                
            # Convert embedding to JSON string for CogniCore storage
            if isinstance(embedding, np.ndarray):
                embedding_str = json.dumps(embedding.tolist())
            else:
                embedding_str = json.dumps(embedding)
            
            # Store pilot embedding with CogniCore (persists across restarts)
            core.publish_data(f'embedding:{pilot_id}', {
                'pilot_id': pilot_id,
                'embedding': embedding_str,
                'source': source,
                'timestamp': time.time()
            })
            stored_count += 1
        
        if stored_count > 0:
            logger.info(f"Stored {stored_count} new pilot embeddings in CogniCore (source: {source})")
        if skipped_count > 0:
            logger.info(f"Skipped {skipped_count} pilot embeddings (already exist in CogniCore)")
            
        return stored_count
    except Exception as e:
        logger.error(f"Failed to store pilot embeddings in CogniCore: {e}")
        return 0

def stream_pilot_embeddings_from_server(core, logger):
    """Stream pilot embeddings from server using SSE connection"""
    url = SERVER_BASE_URL + ENDPOINT_FACE_EMBEDDINGS
    headers = {
        'Authorization': f'Bearer {API_KEY}',
        'Accept': 'text/event-stream',
        'Cache-Control': 'no-cache'
    }
    
    try:
        logger.info("Starting SSE connection to stream pilot embeddings...")
        
        with requests.get(url, headers=headers, stream=True, timeout=30) as response:
            response.raise_for_status()
            
            count = 0
            for line in response.iter_lines(decode_unicode=True):
                if line.startswith('data: '):
                    try:
                        data = json.loads(line[6:])
                        pilot_id = data.get('pilot_id')
                        embedding = data.get('embedding')
                        
                        if pilot_id and embedding:
                            core.publish_data(f'embedding:{pilot_id}', {
                                'pilot_id': pilot_id,
                                'embedding': json.dumps(embedding),
                                'source': 'server_stream',
                                'timestamp': time.time()
                            })
                            count += 1
                            
                            if count % 10 == 0:
                                logger.info(f"Streamed {count} embeddings...")
                    except json.JSONDecodeError:
                        continue
                elif line.startswith('event: complete'):
                    logger.info(f"SSE stream completed. Total embeddings: {count}")
                    break
            
            return count
            
    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
        logger.warning("Server unavailable - using local embeddings fallback")
        return None
    except Exception as e:
        logger.error(f"SSE streaming failed: {e}")
        return None

def sync_pilot_embeddings_on_startup(core):
    """Sync pilot embeddings on startup - server first, then local file fallback"""
    logger = core.get_logger(SERVICE_NAME)
    logger.info("Starting pilot embeddings sync...")
    
    # Check existing embeddings
    existing_embeddings = get_existing_pilot_embeddings(core, logger)
    if existing_embeddings:
        logger.info(f"Found {len(existing_embeddings)} existing embeddings (persisted)")
    
    # Try server first
    server_count = stream_pilot_embeddings_from_server(core, logger)
    
    if server_count:
        logger.info(f"Synced {server_count} embeddings from server")
        # Also load local file for completeness
        local_embeddings = load_pilot_embeddings_from_file(logger)
        if local_embeddings:
            additional = store_pilot_embeddings_in_cognicore(core, local_embeddings, logger, source="file")
            if additional > 0:
                logger.info(f"Added {additional} embeddings from local file")
    else:
        # Server failed - use local file if we don't have embeddings
        if not existing_embeddings:
            logger.info("Using local embeddings file as fallback...")
            local_embeddings = load_pilot_embeddings_from_file(logger)
            if local_embeddings:
                stored = store_pilot_embeddings_in_cognicore(core, local_embeddings, logger, source="file")
                logger.info(f"Loaded {stored} embeddings from local file")
            else:
                logger.error("No embeddings available from any source")
        else:
            logger.info("Server unavailable, using existing embeddings")

class HTTPSClientService:
    """HTTPS Client Service using CogniCore for communication"""
    
    def __init__(self):
        self.core = CogniCore("https_client")
        self.logger = self.core.get_logger(SERVICE_NAME)
        self.core.subscribe_to_data("pilot_id_request", self.on_pilot_id_request)
        
        # Test Redis connection
        if not self.core.is_connected():
            raise Exception("Redis connection failed")
        self.logger.info("Redis storage initialized")
        
        # Notify systemd that service is ready
        systemd.daemon.notify('READY=1')
        self.logger.info("Notified systemd that service is ready")
        
        # Sync embeddings on startup
        threading.Thread(target=sync_pilot_embeddings_on_startup, args=(self.core,), daemon=True).start()
        
    def on_pilot_id_request(self, hash_name, request_data):
        """Handle pilot ID requests from face recognition service"""
        pilot_id = request_data.get("pilot_id")
        confidence = request_data.get("confidence", 0.0)
        
        if not pilot_id:
            self.logger.warning("Empty pilot ID received")
            self._clear_pilot_id_request()
            return
        
        self.logger.info(f"Processing pilot: {pilot_id} (confidence: {confidence:.3f})")
        
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
                    self.logger.error(f"Failed to activate updated profile for {pilot_id}")
            else:
                # Server offline - check if pilot already exists
                self.logger.info(f"Server offline - checking for existing pilot {pilot_id}")
                existing_pilot = self.core.get_pilot_profile(pilot_id)
                
                if existing_pilot:
                    # Pilot exists - just activate
                    self.logger.info(f"Found existing pilot {pilot_id} - activating")
                    if self.core.set_pilot_active(pilot_id, active=True):
                        self.logger.info(f"Existing pilot {pilot_id} activated")
                        self.core.set_system_state(
                            SystemState.SCANNING,
                            f"Welcome {pilot_id}\nProfile active",
                            pilot_id=pilot_id,
                            data={"profile_loaded": True}
                        )
                    else:
                        self.logger.error(f"Failed to activate existing pilot {pilot_id}")
                else:
                    # Try cache as last resort
                    cached_result = get_pilot_profile_from_cache(self.core, pilot_id, self.logger)
                    
                    if cached_result:
                        _, profile_data = cached_result
                        self.logger.info(f"Using cached profile for {pilot_id}")
                        
                        # Save cached profile to CogniCore and activate
                        if save_pilot_profile_to_cognicore(self.core, pilot_id, profile_data, confidence, self.logger):
                            self.logger.info(f"Cached profile activated for {pilot_id}")
                        else:
                            self.logger.error(f"Failed to activate cached profile for {pilot_id}")
                    else:
                        # No profile found anywhere
                        self.logger.error(f"Profile not found for {pilot_id}")
                        self.core.set_system_state(
                            SystemState.SCANNING,
                            "Pilot not found\nScanning...",
                            data={"error": "profile_not_found", "failed_pilot_id": pilot_id}
                        )
                        self._clear_pilot_id_request()
                        return
            
            self._clear_pilot_id_request()
            
        except Exception as e:
            self.logger.error(f"Error processing pilot request: {e}")
            self._clear_pilot_id_request()
    
    def _clear_pilot_id_request(self):
        """Clear pilot_id_request to restart face recognition"""
        try:
            self.core._redis_client.delete("cognicore:data:pilot_id_request")
            self.logger.debug("Cleared pilot_id_request")
        except Exception as e:
            self.logger.error(f"Failed to clear pilot_id_request: {e}")
    
    def run(self):
        """Main service loop"""
        self.logger.info("HTTPS Client service started with CogniCore")
        try:
            while True:
                systemd.daemon.notify('WATCHDOG=1')
                time.sleep(5)
        except KeyboardInterrupt:
            self.logger.info("HTTPS Client service stopping...")
        finally:
            self.core.shutdown()

def main():
    """Main HTTPS client service"""
    try:
        service = HTTPSClientService()
        service.logger.info("HTTPS Client service starting...")
        service.run()
    except KeyboardInterrupt:
        print("HTTPS Client service interrupted")
    except Exception as e:
        print(f"HTTPS Client service failed: {e}")

if __name__ == "__main__":
    main()