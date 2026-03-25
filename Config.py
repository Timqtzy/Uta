"""
Configuration loader with .env file support
"""

import os
from pathlib import Path


def load_config():
    """Load configuration from .env file or environment variables"""

    # Try to load from .env file
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip())

    return {
        'DISCORD_TOKEN': os.getenv('DISCORD_TOKEN', ''),
        'SPOTIFY_CLIENT_ID': os.getenv('SPOTIFY_CLIENT_ID', ''),
        'SPOTIFY_CLIENT_SECRET': os.getenv('SPOTIFY_CLIENT_SECRET', ''),
    }


if __name__ == "__main__":
    config = load_config()
    print("Current configuration:")
    for key, value in config.items():
        masked = value[:4] + '...' + value[-4:] if len(value) > 8 else '***'
        print(f"  {key}: {masked if value else 'NOT SET'}")