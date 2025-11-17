# Server Configuration
HOST=0.0.0.0
PORT=8000

# Database
DATABASE_URL=sqlite+aiosqlite:///./game_servers.db

# Timing
HEARTBEAT_TIMEOUT=60
CLEANUP_INTERVAL=30

# Rate Limiting
MAX_REGISTRATIONS_PER_IP=5
RATE_LIMIT_WINDOW=300

# Security (optional)
# API_KEY=your-secret-key-here

# CORS (comma-separated origins)
ALLOWED_ORIGINS=*

# Game Settings
MIN_GAME_VERSION=1.0.0