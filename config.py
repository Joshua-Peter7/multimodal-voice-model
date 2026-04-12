# Centralized Configuration Loader
# Single unified config for all services

import os
import yaml
from typing import Optional, Any, Dict
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class Config:
    """Centralized configuration manager for all services"""
    
    _instance = None
    _config = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize configuration from YAML files"""
        if self._config is None:
            self._load_config()
    
    def _load_config(self):
        """Load configuration from YAML files"""
        env = os.getenv("APP_ENV", "development")
        config_dir = Path(__file__).parent / "config"
        
        # Load default config
        default_config = self._load_yaml(config_dir / "default.yml")
        
        # Load environment-specific config
        env_config = self._load_yaml(config_dir / f"{env}.yml") or {}
        
        # Load API config
        api_config = self._load_yaml(config_dir / "api-config.yml") or {}
        
        # Load services config
        services_config = self._load_yaml(config_dir / "services-config.yml") or {}
        
        # Load logging config
        logging_config = self._load_yaml(config_dir / "logging.yml") or {}
        
        # Merge configurations (env-specific overrides default)
        self._config = {
            **default_config,
            **env_config,
            "api": api_config,
            "services": services_config,
            "logging": logging_config
        }
        
        logger.info(f"Configuration loaded for environment: {env}")
    
    @staticmethod
    def _load_yaml(filepath: Path) -> Optional[Dict]:
        """Load YAML file"""
        try:
            if filepath.exists():
                with open(filepath, 'r') as f:
                    return yaml.safe_load(f) or {}
            else:
                logger.warning(f"Config file not found: {filepath}")
                return {}
        except Exception as e:
            logger.error(f"Error loading config file {filepath}: {e}")
            return {}
    
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value using dot notation"""
        keys = key.split(".")
        value = self._config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            if default is not None:
                return default
            raise KeyError(f"Configuration key not found: {key}")
    
    def get_safe(self, key: str, default: Any = None) -> Any:
        """Get configuration value safely (returns default if not found)"""
        try:
            return self.get(key, default)
        except KeyError:
            return default
    
    def get_service_config(self, service_name: str) -> Dict:
        """Get configuration for a specific service"""
        return self.get_safe(f"services.{service_name}", {})
    
    def get_api_config(self, provider: str, service: str = None) -> Dict:
        """Get API configuration for a provider"""
        if service:
            return self.get_safe(f"api.{service}.{provider}", {})
        return self.get_safe(f"api.{provider}", {})
    
    def get_database_config(self, db_type: str = "postgres") -> Dict:
        """Get database configuration"""
        return self.get_safe(f"database.{db_type}", {})
    
    def get_cache_config(self, cache_type: str = "redis") -> Dict:
        """Get cache configuration"""
        return self.get_safe(f"cache.{cache_type}", {})
    
    def get_queue_config(self, queue_type: str = "redis_pubsub") -> Dict:
        """Get queue configuration"""
        return self.get_safe(f"queue.{queue_type}", {})
    
    def get_logging_config(self) -> Dict:
        """Get logging configuration"""
        return self.get_safe("logging", {})
    
    def get_languages(self) -> list:
        """Get list of supported languages"""
        return self.get_safe("languages.supported", [])
    
    def is_feature_enabled(self, feature_name: str) -> bool:
        """Check if a feature is enabled"""
        return self.get_safe(f"features.{feature_name}", False)
    
    def __repr__(self) -> str:
        return f"<Config env={os.getenv('APP_ENV', 'development')}>"


# Singleton instance
_config_instance = None

def load_config() -> Config:
    """Get or create config instance"""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance


def get_config() -> Config:
    """Alias for load_config"""
    return load_config()


# Convenience functions for common config access

def get_asr_config() -> Dict:
    """Get ASR service configuration"""
    config = load_config()
    return config.get_safe("api.asr", {})

def get_translation_config() -> Dict:
    """Get translation service configuration"""
    config = load_config()
    return config.get_safe("api.translation", {})

def get_tts_config() -> Dict:
    """Get TTS service configuration"""
    config = load_config()
    return config.get_safe("api.tts", {})

def get_moderation_config() -> Dict:
    """Get moderation service configuration"""
    config = load_config()
    return config.get_safe("api.moderation", {})

def get_redis_config() -> Dict:
    """Get Redis configuration"""
    config = load_config()
    return config.get_cache_config("redis")

def get_postgres_config() -> Dict:
    """Get PostgreSQL configuration"""
    config = load_config()
    return config.get_database_config("postgres")

def get_kafka_config() -> Dict:
    """Get Kafka configuration"""
    config = load_config()
    return config.get_queue_config("kafka")

def get_env() -> str:
    """Get current environment"""
    return os.getenv("APP_ENV", "development")

def is_production() -> bool:
    """Check if running in production"""
    return get_env() == "production"

def is_development() -> bool:
    """Check if running in development"""
    return get_env() == "development"

def get_service_port(service_name: str) -> int:
    """Get port for a service"""
    config = load_config()
    service_config = config.get_service_config(service_name)
    return service_config.get("port", 5000)

def get_service_max_instances(service_name: str) -> int:
    """Get max instances for a service"""
    config = load_config()
    service_config = config.get_service_config(service_name)
    return service_config.get("max_instances", 10)
