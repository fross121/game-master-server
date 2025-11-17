from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import asyncio
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional
import logging

from models import (
    ServerRegisterRequest, ServerRegisterResponse,
    ServerHeartbeatRequest, ServerHeartbeatResponse,
    ServerInfo, ServerListResponse,
    ServerUnregisterRequest, HealthResponse
)
from database import db
from config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Rate limiting storage (in-memory, use Redis for production)
rate_limit_storage = {}

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("Starting master server...")
    await db.init_db()
    
    # Start cleanup task
    cleanup_task = asyncio.create_task(periodic_cleanup())
    
    logger.info(f"Master server started on {settings.host}:{settings.port}")
    logger.info(f"Heartbeat timeout: {settings.heartbeat_timeout}s")
    logger.info(f"Cleanup interval: {settings.cleanup_interval}s")
    
    yield
    
    # Shutdown
    logger.info("Shutting down master server...")
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

app = FastAPI(
    title="Game Master Server",
    description="Central server list for multiplayer game discovery",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Simple rate limiting based on IP address"""
    if request.url.path.startswith("/servers/register"):
        client_ip = request.client.host
        current_time = time.time()
        
        # Clean old entries
        if client_ip in rate_limit_storage:
            rate_limit_storage[client_ip] = [
                t for t in rate_limit_storage[client_ip]
                if current_time - t < settings.rate_limit_window
            ]
        
        # Check rate limit
        if client_ip in rate_limit_storage:
            if len(rate_limit_storage[client_ip]) >= settings.max_registrations_per_ip:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Rate limit exceeded. Please try again later."}
                )
        
        # Add current request
        if client_ip not in rate_limit_storage:
            rate_limit_storage[client_ip] = []
        rate_limit_storage[client_ip].append(current_time)
    
    response = await call_next(request)
    return response

# Optional API key authentication
def verify_api_key(request: Request) -> bool:
    """Verify API key if configured"""
    if settings.api_key is None:
        return True
    
    api_key = request.headers.get("X-API-Key")
    return api_key == settings.api_key

async def periodic_cleanup():
    """Periodically clean up dead servers"""
    while True:
        try:
            await asyncio.sleep(settings.cleanup_interval)
            removed = await db.cleanup_dead_servers()
            if removed > 0:
                logger.info(f"Cleaned up {removed} dead server(s)")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")

@app.get("/", response_model=HealthResponse)
async def root():
    """Root endpoint - health check"""
    active_count = await db.count_active_servers()
    return HealthResponse(
        status="ok",
        timestamp=time.time(),
        active_servers=active_count
    )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    active_count = await db.count_active_servers()
    return HealthResponse(
        status="ok",
        timestamp=time.time(),
        active_servers=active_count
    )

@app.post("/servers/register", response_model=ServerRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_server(server: ServerRegisterRequest, request: Request):
    """Register a new game server"""
    if not verify_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    # Check if host already has too many servers
    existing_servers = await db.get_servers_by_host(server.host)
    if len(existing_servers) >= settings.max_registrations_per_ip:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum {settings.max_registrations_per_ip} servers per host"
        )
    
    # Generate unique server ID
    server_id = str(uuid.uuid4())
    current_time = time.time()
    
    # Create server record
    server_data = {
        "server_id": server_id,
        "name": server.name,
        "host": server.host,
        "port": server.port,
        "players": 0,
        "max_players": server.max_players,
        "game_started": False,
        "version": server.version,
        "registered_at": current_time,
        "last_heartbeat": current_time
    }
    
    try:
        await db.add_server(server_data)
        logger.info(f"Registered server: {server.name} ({server_id}) from {server.host}:{server.port}")
        
        return ServerRegisterResponse(
            server_id=server_id,
            registered_at=current_time
        )
    except Exception as e:
        logger.error(f"Error registering server: {e}")
        raise HTTPException(status_code=500, detail="Failed to register server")

@app.post("/servers/heartbeat", response_model=ServerHeartbeatResponse)
async def heartbeat(heartbeat_data: ServerHeartbeatRequest, request: Request):
    """Update server heartbeat and status"""
    if not verify_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    success = await db.update_heartbeat(
        heartbeat_data.server_id,
        heartbeat_data.players,
        heartbeat_data.game_started
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Server not found")
    
    return ServerHeartbeatResponse(status="ok")

@app.get("/servers/list", response_model=ServerListResponse)
async def list_servers(
    include_started: bool = False,
    version: Optional[str] = None
):
    """Get list of active game servers"""
    servers = await db.get_active_servers()
    current_time = time.time()
    
    # Filter and transform servers
    server_list = []
    for server in servers:
        # Filter out started games unless requested
        if server.game_started and not include_started:
            continue
        
        # Filter by version if specified
        if version and server.version != version:
            continue
        
        server_list.append(ServerInfo(
            server_id=server.server_id,
            name=server.name,
            host=server.host,
            port=server.port,
            players=server.players,
            max_players=server.max_players,
            game_started=server.game_started,
            version=server.version,
            last_heartbeat=server.last_heartbeat,
            uptime=current_time - server.registered_at
        ))
    
    return ServerListResponse(
        servers=server_list,
        total=len(server_list),
        timestamp=current_time
    )

@app.delete("/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_server(server_id: str, request: Request):
    """Unregister a game server"""
    if not verify_api_key(request):
        raise HTTPException(status_code=401, detail="Invalid API key")
    
    success = await db.remove_server(server_id)
    if not success:
        raise HTTPException(status_code=404, detail="Server not found")
    
    logger.info(f"Unregistered server: {server_id}")
    return None

@app.get("/servers/{server_id}", response_model=ServerInfo)
async def get_server_info(server_id: str):
    """Get information about a specific server"""
    server = await db.get_server(server_id)
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    current_time = time.time()
    
    # Check if server is still active
    if current_time - server.last_heartbeat > settings.heartbeat_timeout:
        raise HTTPException(status_code=410, detail="Server is no longer active")
    
    return ServerInfo(
        server_id=server.server_id,
        name=server.name,
        host=server.host,
        port=server.port,
        players=server.players,
        max_players=server.max_players,
        game_started=server.game_started,
        version=server.version,
        last_heartbeat=server.last_heartbeat,
        uptime=current_time - server.registered_at
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info"
    )