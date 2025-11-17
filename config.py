from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # Master server configuration
    host: str = "0.0.0.0"
    port: int = 8000
    
    # Database
    database_url: str = "sqlite+aiosqlite:///./game_servers.db"
    
    # Server cleanup
    heartbeat_timeout: int = 60  # Seconds before server considered dead
    cleanup_interval: int = 30   # How often to clean up dead servers
    
    # Rate limiting
    max_registrations_per_ip: int = 5
    rate_limit_window: int = 300  # 5 minutes
    
    # API Security (optional)
    api_key: Optional[str] = None  # Set to enable API key auth
    
    # CORS
    allowed_origins: list = ["*"]  # Restrict in production
    
    # Game version compatibility
    min_game_version: str = "1.0.0"
    
    class Config:
        env_file = ".env"

settings = Settings()