from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Reads environment variables only (DATABASE_URL, DB_PING_TIMEOUT_S), never a .env file."""

    database_url: str
    db_ping_timeout_s: float = 2.0
