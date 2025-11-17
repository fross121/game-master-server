from pydantic import BaseModel, Field, validator
from datetime import datetime
from typing import Optional
import re

class ServerRegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    host: str = Field(..., description="Public IP address")
    port: int = Field(default=8765, ge=1024, le=65535)
    max_players: int = Field(default=4, ge=2, le=8)
    version: str = Field(default="1.0.0")
    
    @validator('name')
    def validate_name(cls, v):
        # Remove any potentially malicious characters
        if not re.match(r'^[\w\s\-\.]+$', v):
            raise ValueError('Server name contains invalid characters')
        return v.strip()
    
    @validator('host')
    def validate_host(cls, v):
        # Basic IP validation
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', v):
            raise ValueError('Invalid IP address format')
        return v

class ServerRegisterResponse(BaseModel):
    server_id: str
    registered_at: float
    message: str = "Server registered successfully"

class ServerHeartbeatRequest(BaseModel):
    server_id: str
    players: int = Field(ge=0, le=8)
    game_started: bool = False

class ServerHeartbeatResponse(BaseModel):
    status: str
    message: str = "Heartbeat received"

class ServerInfo(BaseModel):
    server_id: str
    name: str
    host: str
    port: int
    players: int
    max_players: int
    game_started: bool
    version: str
    last_heartbeat: float
    uptime: float  # Seconds since registration

class ServerListResponse(BaseModel):
    servers: list[ServerInfo]
    total: int
    timestamp: float

class ServerUnregisterRequest(BaseModel):
    server_id: str

class HealthResponse(BaseModel):
    status: str
    timestamp: float
    active_servers: int
    version: str = "1.0.0"