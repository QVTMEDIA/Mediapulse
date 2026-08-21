import os
from dataclasses import dataclass

# Local-dev-only default. Real deployments must set DATABASE_URL explicitly
# (see services/api/README.md and docker-compose.yml).
DEFAULT_DATABASE_URL = 'postgresql://mediapulse:mediapulse@localhost:5432/mediapulse'


@dataclass(frozen=True)
class Settings:
    database_url: str
    repository_backend: str  # 'postgres' | 'memory'


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get('DATABASE_URL', DEFAULT_DATABASE_URL),
        repository_backend=os.environ.get('API_REPOSITORY', 'postgres').strip().lower(),
    )
