"""
CogniCore - Simple Redis Communication Library

Provides essential Redis-based communication for CogniFlight Edge:
- Data publishing and retrieval via Redis hashes
- System state management
- Pilot profile storage  
- Common utilities (heartbeat, logging setup)
- Standard Python logging (systemd journald compatible)
"""

import json
import time
import redis
import threading
import logging
import os
from typing import Dict, Any, Optional, Callable, List

from .state import SystemState, PilotProfile, SystemStatusMessage, StateSnapshot, get_state_manager
from .exceptions import CogniCoreError, ConnectionError as CogniConnectionError, ValidationError
from . import config

# Configure logging for systemd journald
logging.basicConfig(
    level=logging.INFO,
    format='%(name)s[%(process)d]: %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]  # Goes to systemd journald when run as service
)

logger = logging.getLogger("CogniCore")


class CogniCore:
    """
    Redis-only communication library - Redis connection is required
    """
    
    def __init__(self, service_name: str, redis_host: Optional[str] = None, 
                 redis_port: Optional[int] = None, redis_db: Optional[int] = None, 
                 connection_timeout: Optional[int] = None):
        """
        Initialize CogniCore instance
        
        Args:
            service_name: Name of the service using CogniCore
            redis_host: Redis server host
            redis_port: Redis server port
            redis_db: Redis database number
            connection_timeout: Connection timeout in seconds
            
        Raises:
            redis.ConnectionError: If Redis is not available
        """
        self.service_name = service_name
        
        # Load configuration with environment variable fallbacks
        self.redis_host = redis_host or os.getenv('REDIS_HOST', 'localhost')
        self.redis_port = redis_port or int(os.getenv('REDIS_PORT', '6379'))
        self.redis_db = redis_db or int(os.getenv('REDIS_DB', '0'))
        self.connection_timeout = connection_timeout or int(os.getenv('REDIS_TIMEOUT', '5'))
        
        # Redis configuration
        self.redis_ttl = int(os.getenv('REDIS_TTL', '300'))  # 5 minutes default
        self.history_limit = int(os.getenv('STATE_HISTORY_LIMIT', '1000'))
        self.health_check_interval = int(os.getenv('REDIS_HEALTH_CHECK', '30'))
        
        # Get thread-safe state manager
        self._state_manager = get_state_manager()
        
        # Redis connections - required
        self._redis_client = None
        self._redis_subscriber = None
        
        # Subscribers and callbacks
        self._data_subscribers = {}  # hash_name -> [callbacks]
        self._state_subscribers = []
        self._running = False
        self._subscriber_thread = None
        
        # Connect to Redis - will raise exception if fails
        self._connect()
        
    def _connect(self):
        """Connect to Redis - raises exception if Redis unavailable"""
        try:
            # Main Redis client
            # Use connection pooling for better resource management
            self._redis_pool = redis.ConnectionPool(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True,
                socket_connect_timeout=self.connection_timeout,
                socket_timeout=self.connection_timeout,
                health_check_interval=self.health_check_interval,
                max_connections=10  # Pool size
            )
            
            self._redis_client = redis.Redis(connection_pool=self._redis_pool)
            
            # Test connection - will raise exception if fails
            self._redis_client.ping()
            
            # Subscriber client for keyspace notifications (separate connection)
            self._redis_subscriber = redis.Redis(
                host=self.redis_host,
                port=self.redis_port,
                db=self.redis_db,
                decode_responses=True,
                socket_connect_timeout=self.connection_timeout
            )
            
            # Enable keyspace notifications for hash operations
            self._redis_client.config_set('notify-keyspace-events', 'Kh')
            
            logger.info(f"CogniCore [{self.service_name}] connected to Redis at {self.redis_host}:{self.redis_port}")
            
            # Start keyspace notification subscriber
            self._start_subscriber()
            
        except (redis.ConnectionError, redis.TimeoutError, redis.ResponseError) as e:
            logger.error(f"CogniCore [{self.service_name}] failed to connect to Redis: {e}")
            raise redis.ConnectionError(f"Redis connection required but failed: {e}")
    
    def _start_subscriber(self):
        """Start background thread for keyspace notifications"""
        if self._subscriber_thread is not None:
            return
            
        self._running = True
        self._subscriber_thread = threading.Thread(
            target=self._subscriber_worker,
            daemon=True,
            name=f"CogniCore-{self.service_name}"
        )
        self._subscriber_thread.start()
    
    def _subscriber_worker(self):
        """Background worker for processing keyspace notifications"""
        try:
            pubsub = self._redis_subscriber.pubsub()
            # Subscribe to all hash operations on cognicore keys
            pubsub.psubscribe('__keyspace@0__:cognicore:data:*')
            pubsub.psubscribe('__keyspace@0__:cognicore:state')
            # Subscribe to state change pub/sub channel for inter-process communication
            pubsub.subscribe('cognicore:state_changes')
            
            logger.debug(f"CogniCore [{self.service_name}] subscriber started")
            
            for message in pubsub.listen():
                if not self._running:
                    break
                    
                if message['type'] == 'pmessage':
                    try:
                        # Extract key name from channel
                        # Channel format: __keyspace@0__:cognicore:data:hash_name
                        channel_parts = message['channel'].split(':')
                        if len(channel_parts) >= 4:
                            key = ':'.join(channel_parts[1:])  # Get everything after __keyspace@0__:
                            operation = message['data']  # hset, hdel, etc.
                            
                            if operation in ['hset', 'hmset']:
                                self._handle_hash_change(key)
                                
                    except Exception as e:
                        logger.error(f"Error processing keyspace notification: {e}")
                        
                elif message['type'] == 'message' and message['channel'] == 'cognicore:state_changes':
                    try:
                        # Handle inter-process state change notification
                        state_data = json.loads(message['data'])
                        for callback in self._state_subscribers:
                            try:
                                callback(state_data)
                            except Exception as e:
                                logger.error(f"Error in state subscriber callback: {e}")
                    except Exception as e:
                        logger.error(f"Error processing state change message: {e}")
                        
        except Exception as e:
            logger.error(f"Subscriber worker error: {e}")
    
    def _handle_hash_change(self, key: str):
        """Handle hash change notifications"""
        try:
            if key.startswith('cognicore:data:'):
                # Data hash change
                hash_name = key[15:]  # Remove 'cognicore:data:' prefix
                if hash_name in self._data_subscribers:
                    data = self.get_data(hash_name)
                    # Call callbacks even if data is None (hash deleted/cleared)
                    for callback in self._data_subscribers[hash_name]:
                        try:
                            callback(hash_name, data)
                        except Exception as e:
                            logger.error(f"Error in data subscriber callback: {e}")
            
            elif key == 'cognicore:state':
                # System state change
                state_data = self.get_data('system_state')
                if state_data:
                    for callback in self._state_subscribers:
                        try:
                            callback(state_data)
                        except Exception as e:
                            logger.error(f"Error in state subscriber callback: {e}")
        except Exception as e:
            logger.error(f"Error handling hash change for {key}: {e}")
    
    # ==================== DATA OPERATIONS ====================
    
    def publish_data(self, hash_name: str, data: Dict[str, Any], persistent: bool = None):
        """
        Publish data to a Redis hash
        
        Args:
            hash_name: Name of the data hash (e.g., 'vision', 'hr', 'fusion')
            data: Data to publish
            persistent: Whether to skip TTL. If None, auto-determined by hash_name
            
        Raises:
            ValidationError: If parameters are invalid
            CogniConnectionError: If Redis operation fails
        """
        if not hash_name or not isinstance(hash_name, str):
            raise ValidationError("hash_name must be a non-empty string")
        if not isinstance(data, dict):
            raise ValidationError("data must be a dictionary")
        
        # Auto-determine persistence for specific data types
        if persistent is None:
            persistent_patterns = [
                'pilot_cache:',      # Pilot cache data (persistent)
                'network_outbox',    # Failed MQTT telemetry (persistent)
                'embedding:',        # Face embeddings (persistent)
            ]
            persistent = any(hash_name.startswith(pattern) or hash_name == pattern 
                           for pattern in persistent_patterns)
        
        # Add metadata
        enriched_data = {
            **data,
            'timestamp': time.time(),
            'service': self.service_name
        }
        
        try:
            key = f"cognicore:data:{hash_name}"
            # Convert all values to strings for Redis hash storage
            redis_data = {k: json.dumps(v) if not isinstance(v, str) else v 
                         for k, v in enriched_data.items()}
            
            self._redis_client.hset(key, mapping=redis_data)
            
            # Persistent data survives via Redis built-in persistence (RDB/AOF)
            
        except (redis.ConnectionError, redis.TimeoutError) as e:
            logger.error(f"Failed to publish data to {hash_name}: {e}")
            raise CogniConnectionError(f"Redis operation failed: {e}")
    
    def get_data(self, hash_name: str) -> Optional[Dict[str, Any]]:
        """
        Get data from a Redis hash
        
        Args:
            hash_name: Name of the data hash
            
        Returns:
            Latest data from the hash or None if not available
            
        Raises:
            ValidationError: If hash_name is invalid
            CogniConnectionError: If Redis operation fails
        """
        if not hash_name or not isinstance(hash_name, str):
            raise ValidationError("hash_name must be a non-empty string")
        try:
            key = f"cognicore:data:{hash_name}"
            redis_data = self._redis_client.hgetall(key)
            
            if not redis_data:
                return None
            
            # Convert JSON strings back to Python objects
            data = {}
            for k, v in redis_data.items():
                try:
                    data[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    data[k] = v  # Keep as string if not valid JSON
            
            return data
            
        except (redis.ConnectionError, redis.TimeoutError) as e:
            logger.error(f"Failed to get data from {hash_name}: {e}")
            raise CogniConnectionError(f"Redis operation failed: {e}")
    
    def subscribe_to_data(self, hash_name: str, callback: Callable[[str, Dict[str, Any]], None]):
        """
        Subscribe to changes in a specific data hash
        
        Args:
            hash_name: Name of the hash to monitor
            callback: Function to call when hash changes (hash_name, data)
        """
        if hash_name not in self._data_subscribers:
            self._data_subscribers[hash_name] = []
        self._data_subscribers[hash_name].append(callback)
        logger.debug(f"Subscribed to {hash_name} changes")
    
    def unsubscribe_from_data(self, hash_name: str, callback: Callable):
        """Unsubscribe from hash changes"""
        if hash_name in self._data_subscribers:
            if callback in self._data_subscribers[hash_name]:
                self._data_subscribers[hash_name].remove(callback)
    
    # ==================== STATE MANAGEMENT ====================
    
    def set_system_state(self, state: SystemState, message: str, pilot_id: Optional[str] = None, 
                        data: Optional[Dict[str, Any]] = None):
        """
        Set the single global system state using thread-safe state manager
        
        Args:
            state: New system state
            message: Message to display for this state
            pilot_id: Associated pilot ID
            data: Additional state data
        """
        # Get current state for logging
        current_snapshot = self._state_manager.get_current_state()
        old_state = current_snapshot.state.value if current_snapshot else 'unknown'
        
        # Use centralized thread-safe state manager - single source of truth
        snapshot = self._state_manager.transition_state(
            state=state,
            message=message,
            service=self.service_name,
            pilot_id=pilot_id,
            data=data
        )
        
        # Store in Redis for persistence and inter-process communication
        state_data = snapshot.to_dict()
        self.publish_data('system_state', state_data)
        
        # Notify subscribers about state change
        for callback in self._state_subscribers:
            try:
                callback(state_data)
            except Exception as e:
                logger.error(f"Error in state subscriber callback: {e}")
        
        # Publish to Redis channel for other processes
        try:
            self._redis_client.publish('cognicore:state_changes', json.dumps(state_data))
        except (redis.ConnectionError, redis.TimeoutError) as e:
            logger.error(f"Failed to publish state change to Redis channel: {e}")
        
        # Add to persistent state history
        try:
            history_key = "cognicore:state_history"
            self._redis_client.lpush(history_key, json.dumps(state_data))
            self._redis_client.ltrim(history_key, 0, self.history_limit - 1)
        except (redis.ConnectionError, redis.TimeoutError):
            logger.error("Failed to update state history")
            raise
        
        # Log state change
        logger.info(f"System state: {old_state} → {state.value} (service: {self.service_name}, pilot: {pilot_id})")
    
    def get_system_state(self) -> Optional[SystemState]:
        """Get current global system state from centralized state manager"""
        return self._state_manager.get_current_system_state()
    
    def get_system_state_snapshot(self) -> Optional[StateSnapshot]:
        """Get current system state snapshot with full details"""
        return self._state_manager.get_current_state()
    
    def subscribe_to_state_changes(self, callback: Callable[[Dict[str, Any]], None]):
        """Subscribe to system state changes"""
        self._state_subscribers.append(callback)
    
    # ==================== PILOT PROFILES ====================
    
    def set_pilot_profile(self, profile: PilotProfile):
        """Set active pilot profile (temporary, created from cache or server fetch)"""
        from dataclasses import asdict
        
        profile_data = asdict(profile)
        profile_data['last_updated'] = time.time()
        
        # Store active pilot data (temporary with TTL)
        active_pilot_data = {
            'pilot_id': profile.id,
            'profile_loaded': True, 
            'loaded_by': self.service_name,
            # Include all profile data
            'name': profile.name,
            'flightHours': profile.flightHours,
            'baseline': profile.baseline,
            'environmentPreferences': profile.environmentPreferences
        }
        
        # Use publish_data for active_pilot (will get TTL)
        self.publish_data('active_pilot', active_pilot_data)
        
        logger.info(f"Set active pilot profile: {profile.id} (temporary, TTL applied)")
    
    def get_pilot_profile(self, pilot_id: str) -> Optional[PilotProfile]:
        """Get pilot profile from pilot_cache or active_pilot"""
        # First try pilot_cache
        cache_data = self.get_data(f'pilot_cache:{pilot_id}')
        if cache_data and 'profile_data' in cache_data:
            try:
                profile_data = cache_data['profile_data']
                return PilotProfile(
                    id=profile_data['id'],
                    name=profile_data['name'], 
                    flightHours=profile_data['flightHours'],
                    baseline=profile_data['baseline'],
                    environmentPreferences=profile_data['environmentPreferences']
                )
            except (KeyError, TypeError) as e:
                logger.error(f"Error parsing cached profile data for {pilot_id}: {e}")
        
        # Fallback to active_pilot if it matches
        active_data = self.get_data('active_pilot')
        if active_data and active_data.get('pilot_id') == pilot_id:
            try:
                return PilotProfile(
                    id=active_data['pilot_id'],
                    name=active_data['name'],
                    flightHours=active_data['flightHours'], 
                    baseline=active_data['baseline'],
                    environmentPreferences=active_data['environmentPreferences']
                )
            except (KeyError, TypeError) as e:
                logger.error(f"Error parsing active pilot data for {pilot_id}: {e}")
        return None
    
    def get_active_pilot_profile(self) -> Optional[PilotProfile]:
        """Get currently active pilot profile"""
        active_data = self.get_data('active_pilot')
        if active_data and active_data.get('profile_loaded'):
            try:
                return PilotProfile(
                    id=active_data['pilot_id'],
                    name=active_data['name'],
                    flightHours=active_data['flightHours'], 
                    baseline=active_data['baseline'],
                    environmentPreferences=active_data['environmentPreferences']
                )
            except (KeyError, TypeError) as e:
                logger.error(f"Error parsing active pilot data: {e}")
        return None
    
    def get_active_pilot(self) -> Optional[str]:
        """Get active pilot ID"""
        active_data = self.get_data('active_pilot')
        if active_data:
            pilot_id = active_data.get('pilot_id')
            # Return None for empty pilot_id (cleared state)
            # Convert pilot_id to string to handle both string and integer values from Redis
            if pilot_id:
                pilot_id_str = str(pilot_id)
                return pilot_id_str if pilot_id_str.strip() else None
            return None
        return None
    
    def get_active_pilot_profile(self) -> Optional[PilotProfile]:
        """Get active pilot profile"""
        pilot_id = self.get_active_pilot()
        return self.get_pilot_profile(pilot_id) if pilot_id else None
    
    def clear_active_pilot(self):
        """Clear active pilot by setting empty values to trigger subscriptions"""
        try:
            # Set empty pilot_id to trigger keyspace notifications for subscriptions
            self.publish_data('active_pilot', {
                'pilot_id': '',
                'cleared': True,
                'reason': 'face_recognition_restart'
            })
            logger.info("Active pilot cleared with empty pilot_id to trigger handover")
        except (redis.ConnectionError, redis.TimeoutError):
            logger.error("Failed to clear active pilot")
            raise
    
    def list_pilots(self) -> list[str]:
        """Get list of all stored pilot IDs"""
        try:
            return list(self._redis_client.smembers("cognicore:pilot_index"))
        except (redis.ConnectionError, redis.TimeoutError):
            logger.error("Failed to list pilots")
            raise
    
    # ==================== STATE-ONLY DISPLAY SYSTEM ====================
    # LCD display controlled only via system state changes - alert_manager handles all display
    
    # ==================== COMMON UTILITIES ====================
    
    
    def ensure_directory(self, path: str) -> bool:
        """
        Ensure a directory exists, creating it if necessary.
        
        Args:
            path: Directory path to create
            
        Returns:
            True if directory exists or was created, False on error
        """
        try:
            os.makedirs(path, exist_ok=True)
            return True
        except Exception as e:
            logger.error(f"Failed to create directory {path}: {e}")
            return False
    
    def safe_write_file(self, filepath: str, content: str, atomic: bool = True) -> bool:
        """
        Safely write content to a file with optional atomic write.
        
        Args:
            filepath: Path to write file
            content: Content to write
            atomic: Use atomic write (write to temp file then rename)
            
        Returns:
            True if successful, False on error
        """
        try:
            if atomic:
                temp_file = f"{filepath}.tmp"
                with open(temp_file, 'w') as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                os.rename(temp_file, filepath)
            else:
                with open(filepath, 'w') as f:
                    f.write(content)
                    f.flush()
            return True
        except Exception as e:
            logger.error(f"Failed to write file {filepath}: {e}")
            return False
            
    def get_logger(self, name: Optional[str] = None) -> logging.Logger:
        """
        Get a properly configured logger for the service.
        Uses systemd journald when running as a service.
        
        Args:
            name: Logger name (defaults to service_name)
            
        Returns:
            Configured logger instance
        """
        logger_name = name or self.service_name
        service_logger = logging.getLogger(logger_name)
        
        # Prevent duplicate handlers
        if not service_logger.handlers:
            handler = logging.StreamHandler()
            # Format for systemd journald
            formatter = logging.Formatter(
                f'{logger_name}[%(process)d]: %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            service_logger.addHandler(handler)
            service_logger.setLevel(logging.INFO)
            service_logger.propagate = False
            
        return service_logger

    # ==================== UTILITY METHODS ====================
    
    def is_connected(self) -> bool:
        """Check if Redis connection is active"""
        try:
            self._redis_client.ping()
            return True
        except:
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get CogniCore usage statistics"""
        try:
            info = self._redis_client.info()
            keys = self._redis_client.keys("cognicore:*")
            
            return {
                "connected": True,
                "redis_version": info.get("redis_version"),
                "total_keys": len(keys),
                "memory_used": info.get("used_memory_human"),
                "subscribers": len(self._data_subscribers),
                "service": self.service_name
            }
        except (redis.ConnectionError, redis.TimeoutError):
            logger.error("Failed to get stats")
            raise
    
    def clear_all_data(self):
        """Clear all CogniCore data (for testing/debugging)"""
        try:
            keys = self._redis_client.keys("cognicore:*")
            if keys:
                self._redis_client.delete(*keys)
                logger.info(f"Cleared {len(keys)} CogniCore keys")
        except (redis.ConnectionError, redis.TimeoutError):
            logger.error("Failed to clear data")
            raise
    
    def shutdown(self):
        """Proper shutdown with resource cleanup"""
        logger.info(f"CogniCore [{self.service_name}] shutting down...")
        
        # Stop subscriber thread
        self._running = False
        
        if self._subscriber_thread and self._subscriber_thread.is_alive():
            self._subscriber_thread.join(timeout=2)
            if self._subscriber_thread.is_alive():
                logger.warning("Subscriber thread did not shutdown cleanly")
        
        # Close Redis connections properly
        if self._redis_subscriber:
            try:
                self._redis_subscriber.close()
            except Exception as e:
                logger.error(f"Error closing Redis subscriber: {e}")
        
        if self._redis_client:
            try:
                self._redis_client.close()
            except Exception as e:
                logger.error(f"Error closing Redis client: {e}")
        
        # Close connection pool
        if hasattr(self, '_redis_pool'):
            try:
                self._redis_pool.disconnect()
            except Exception as e:
                logger.error(f"Error closing Redis pool: {e}")
        
        logger.info(f"CogniCore [{self.service_name}] shutdown complete")