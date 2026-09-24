import os
from dataclasses import dataclass

# Local-dev-only default. Real deployments must set DATABASE_URL explicitly
# (see services/api/README.md and docker-compose.yml).
DEFAULT_DATABASE_URL = 'postgresql://mediapulse:mediapulse@localhost:5432/mediapulse'


@dataclass(frozen=True)
class Settings:
    database_url: str
    repository_backend: str  # 'postgres' | 'memory'
    # Shared secret gating self-registration -- '' (the default) means no
    # gate at all, so an unconfigured deployment keeps today's open
    # signup behavior rather than silently locking everyone out. Set this
    # in the deployment's env once you want /api/auth/register to require
    # it (see CHANGELOG.md).
    register_invite_code: str


def get_settings() -> Settings:
    return Settings(
        database_url=os.environ.get('DATABASE_URL', DEFAULT_DATABASE_URL),
        repository_backend=os.environ.get('API_REPOSITORY', 'postgres').strip().lower(),
        register_invite_code=os.environ.get('REGISTER_INVITE_CODE', '').strip(),
    )
