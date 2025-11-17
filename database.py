from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy import Column, String, Integer, Float, Boolean, Index
from datetime import datetime
import time
from typing import Optional, List
from config import settings

Base = declarative_base()

class ServerRecord(Base):
    __tablename__ = "servers"
    
    server_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    host = Column(String, nullable=False, index=True)
    port = Column(Integer, nullable=False)
    players = Column(Integer, default=0)
    max_players = Column(Integer, default=4)
    game_started = Column(Boolean, default=False)
    version = Column(String, nullable=False)
    registered_at = Column(Float, nullable=False)
    last_heartbeat = Column(Float, nullable=False, index=True)
    
    __table_args__ = (
        Index('idx_active_servers', 'last_heartbeat', 'game_started'),
    )

class Database:
    def __init__(self):
        self.engine = create_async_engine(
            settings.database_url,
            echo=False,
            future=True
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
    
    async def init_db(self):
        """Initialize database tables"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    
    async def add_server(self, server_data: dict) -> str:
        """Add a new server to the database"""
        async with self.async_session() as session:
            server = ServerRecord(**server_data)
            session.add(server)
            await session.commit()
            return server.server_id
    
    async def update_heartbeat(self, server_id: str, players: int, game_started: bool) -> bool:
        """Update server heartbeat and status"""
        async with self.async_session() as session:
            result = await session.get(ServerRecord, server_id)
            if result:
                result.last_heartbeat = time.time()
                result.players = players
                result.game_started = game_started
                await session.commit()
                return True
            return False
    
    async def get_server(self, server_id: str) -> Optional[ServerRecord]:
        """Get a specific server by ID"""
        async with self.async_session() as session:
            return await session.get(ServerRecord, server_id)
    
    async def get_active_servers(self) -> List[ServerRecord]:
        """Get all active servers (heartbeat within timeout)"""
        from sqlalchemy import select
        
        cutoff_time = time.time() - settings.heartbeat_timeout
        
        async with self.async_session() as session:
            result = await session.execute(
                select(ServerRecord)
                .where(ServerRecord.last_heartbeat >= cutoff_time)
                .order_by(ServerRecord.registered_at.desc())
            )
            return result.scalars().all()
    
    async def remove_server(self, server_id: str) -> bool:
        """Remove a server from the database"""
        async with self.async_session() as session:
            result = await session.get(ServerRecord, server_id)
            if result:
                await session.delete(result)
                await session.commit()
                return True
            return False
    
    async def cleanup_dead_servers(self) -> int:
        """Remove servers that haven't sent heartbeat within timeout"""
        from sqlalchemy import delete
        
        cutoff_time = time.time() - settings.heartbeat_timeout
        
        async with self.async_session() as session:
            result = await session.execute(
                delete(ServerRecord)
                .where(ServerRecord.last_heartbeat < cutoff_time)
            )
            await session.commit()
            return result.rowcount
    
    async def count_active_servers(self) -> int:
        """Count active servers"""
        from sqlalchemy import select, func
        
        cutoff_time = time.time() - settings.heartbeat_timeout
        
        async with self.async_session() as session:
            result = await session.execute(
                select(func.count(ServerRecord.server_id))
                .where(ServerRecord.last_heartbeat >= cutoff_time)
            )
            return result.scalar() or 0
    
    async def get_servers_by_host(self, host: str) -> List[ServerRecord]:
        """Get all servers from a specific host IP"""
        from sqlalchemy import select
        
        async with self.async_session() as session:
            result = await session.execute(
                select(ServerRecord).where(ServerRecord.host == host)
            )
            return result.scalars().all()

# Global database instance
db = Database()