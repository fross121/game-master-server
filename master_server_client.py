import aiohttp
import asyncio
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import time

logger = logging.getLogger(__name__)

@dataclass
class MasterServerConfig:
    """Configuration for master server connection"""
    url: str = "http://localhost:8000"  # Master server URL
    api_key: Optional[str] = None  # Optional API key
    heartbeat_interval: int = 30  # Seconds between heartbeats
    timeout: int = 10  # Request timeout
    retry_attempts: int = 3  # Number of retry attempts
    retry_delay: int = 2  # Seconds between retries

class MasterServerClient:
    """Client for interacting with the master server"""
    
    def __init__(self, config: MasterServerConfig):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.server_id: Optional[str] = None
        self.heartbeat_task: Optional[asyncio.Task] = None
        self._running = False
        
    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.disconnect()
    
    async def connect(self):
        """Initialize HTTP session"""
        if self.session is None:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            headers = {}
            if self.config.api_key:
                headers["X-API-Key"] = self.config.api_key
            
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                headers=headers
            )
            logger.info(f"Connected to master server: {self.config.url}")
    
    async def disconnect(self):
        """Close HTTP session and stop heartbeat"""
        if self.heartbeat_task:
            await self.stop_heartbeat()
        
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("Disconnected from master server")
    
    async def _make_request(
        self,
        method: str,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        retry: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Make HTTP request with retry logic"""
        if not self.session:
            await self.connect()
        
        url = f"{self.config.url}{endpoint}"
        attempts = self.config.retry_attempts if retry else 1
        
        for attempt in range(attempts):
            try:
                async with self.session.request(method, url, json=data) as response:
                    if response.status == 200 or response.status == 201:
                        return await response.json()
                    elif response.status == 204:
                        return {"status": "ok"}
                    elif response.status == 404:
                        logger.warning(f"Resource not found: {endpoint}")
                        return None
                    elif response.status == 429:
                        logger.warning("Rate limit exceeded")
                        if attempt < attempts - 1:
                            await asyncio.sleep(self.config.retry_delay * 2)
                            continue
                        return None
                    else:
                        error_text = await response.text()
                        logger.error(f"Request failed: {response.status} - {error_text}")
                        
                        if attempt < attempts - 1:
                            await asyncio.sleep(self.config.retry_delay)
                            continue
                        return None
                        
            except asyncio.TimeoutError:
                logger.error(f"Request timeout: {endpoint}")
                if attempt < attempts - 1:
                    await asyncio.sleep(self.config.retry_delay)
                    continue
                return None
            except Exception as e:
                logger.error(f"Request error: {e}")
                if attempt < attempts - 1:
                    await asyncio.sleep(self.config.retry_delay)
                    continue
                return None
        
        return None
    
    async def register_server(
        self,
        name: str,
        host: str,
        port: int = 8765,
        max_players: int = 4,
        version: str = "1.0.0"
    ) -> Optional[str]:
        """
        Register game server with master server
        
        Returns:
            server_id if successful, None otherwise
        """
        data = {
            "name": name,
            "host": host,
            "port": port,
            "max_players": max_players,
            "version": version
        }
        
        logger.info(f"Registering server: {name} at {host}:{port}")
        response = await self._make_request("POST", "/servers/register", data)
        
        if response and "server_id" in response:
            self.server_id = response["server_id"]
            logger.info(f"Server registered with ID: {self.server_id}")
            return self.server_id
        
        logger.error("Failed to register server")
        return None
    
    async def unregister_server(self, server_id: Optional[str] = None) -> bool:
        """
        Unregister server from master server
        
        Args:
            server_id: Server ID to unregister (uses stored ID if not provided)
        
        Returns:
            True if successful
        """
        server_id = server_id or self.server_id
        if not server_id:
            logger.warning("No server ID to unregister")
            return False
        
        logger.info(f"Unregistering server: {server_id}")
        response = await self._make_request(
            "DELETE",
            f"/servers/{server_id}",
            retry=False
        )
        
        if response:
            self.server_id = None
            logger.info("Server unregistered successfully")
            return True
        
        return False
    
    async def send_heartbeat(
        self,
        server_id: Optional[str] = None,
        players: int = 0,
        game_started: bool = False
    ) -> bool:
        """
        Send heartbeat to master server
        
        Args:
            server_id: Server ID (uses stored ID if not provided)
            players: Current player count
            game_started: Whether game has started
        
        Returns:
            True if successful
        """
        server_id = server_id or self.server_id
        if not server_id:
            logger.warning("No server ID for heartbeat")
            return False
        
        data = {
            "server_id": server_id,
            "players": players,
            "game_started": game_started
        }
        
        response = await self._make_request("POST", "/servers/heartbeat", data, retry=False)
        return response is not None
    
    async def heartbeat_loop(
        self,
        server_id: Optional[str] = None,
        get_player_count_fn = None,
        get_game_started_fn = None
    ):
        """
        Background task that sends periodic heartbeats
        
        Args:
            server_id: Server ID (uses stored ID if not provided)
            get_player_count_fn: Callable that returns current player count
            get_game_started_fn: Callable that returns whether game started
        """
        server_id = server_id or self.server_id
        if not server_id:
            logger.error("No server ID for heartbeat loop")
            return
        
        self._running = True
        logger.info(f"Starting heartbeat loop (interval: {self.config.heartbeat_interval}s)")
        
        while self._running:
            try:
                # Get current game state
                players = get_player_count_fn() if get_player_count_fn else 0
                game_started = get_game_started_fn() if get_game_started_fn else False
                
                # Send heartbeat
                success = await self.send_heartbeat(server_id, players, game_started)
                if not success:
                    logger.warning("Heartbeat failed")
                
                # Wait for next heartbeat
                await asyncio.sleep(self.config.heartbeat_interval)
                
            except asyncio.CancelledError:
                logger.info("Heartbeat loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")
                await asyncio.sleep(self.config.heartbeat_interval)
        
        logger.info("Heartbeat loop stopped")
    
    async def start_heartbeat(
        self,
        server_id: Optional[str] = None,
        get_player_count_fn = None,
        get_game_started_fn = None
    ):
        """Start background heartbeat task"""
        if self.heartbeat_task and not self.heartbeat_task.done():
            logger.warning("Heartbeat already running")
            return
        
        self.heartbeat_task = asyncio.create_task(
            self.heartbeat_loop(server_id, get_player_count_fn, get_game_started_fn)
        )
    
    async def stop_heartbeat(self):
        """Stop background heartbeat task"""
        if self.heartbeat_task:
            self._running = False
            self.heartbeat_task.cancel()
            try:
                await self.heartbeat_task
            except asyncio.CancelledError:
                pass
            self.heartbeat_task = None
            logger.info("Heartbeat stopped")
    
    async def fetch_server_list(
        self,
        include_started: bool = False,
        version: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch list of available servers from master server
        
        Args:
            include_started: Include servers where game has started
            version: Filter by game version
        
        Returns:
            List of server information dictionaries
        """
        params = []
        if include_started:
            params.append("include_started=true")
        if version:
            params.append(f"version={version}")
        
        query_string = "?" + "&".join(params) if params else ""
        endpoint = f"/servers/list{query_string}"
        
        response = await self._make_request("GET", endpoint)
        
        if response and "servers" in response:
            logger.info(f"Fetched {len(response['servers'])} server(s)")
            return response["servers"]
        
        logger.warning("Failed to fetch server list")
        return []
    
    async def get_server_info(self, server_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific server
        
        Args:
            server_id: Server ID to query
        
        Returns:
            Server information dictionary or None
        """
        response = await self._make_request("GET", f"/servers/{server_id}")
        return response
    
    async def check_health(self) -> bool:
        """
        Check if master server is accessible
        
        Returns:
            True if master server is healthy
        """
        response = await self._make_request("GET", "/health", retry=False)
        return response is not None and response.get("status") == "ok"


def get_public_ip() -> str:
    """
    Get public IP address of this machine
    
    Note: This is a simple implementation. In production, you might want to:
    - Use a more reliable service
    - Cache the result
    - Handle errors more gracefully
    - Allow manual override via config
    """
    import socket
    import urllib.request
    
    try:
        # Try to get public IP from external service
        with urllib.request.urlopen('https://api.ipify.org', timeout=5) as response:
            return response.read().decode('utf-8').strip()
    except:
        try:
            # Fallback: Get local IP (won't work for NAT/firewall scenarios)
            s = socket.socket(socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            return local_ip
        except:
            logger.warning("Could not determine public IP, using localhost")
            return "127.0.0.1"