import os
from pydantic import BaseModel

class Settings(BaseModel):
    PORT: int = int(os.getenv("PORT", os.getenv("BACKEND_PORT", "8190")))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    DB_URL: str = os.getenv("DB_URL", "sqlite:///./data/miband.db")
    REDIS_PORT: int = int(os.getenv("REDIS_PORT", "6389"))
    REDIS_URL: str = os.getenv("REDIS_URL", f"redis://localhost:{os.getenv('REDIS_PORT', '6389')}/0")
    WEATHER_PROVIDER: str = os.getenv("WEATHER_PROVIDER", "open-meteo")
    WEATHER_API_KEY: str = os.getenv("WEATHER_API_KEY", "")
    WEATHER_CITY: str = os.getenv("WEATHER_CITY", "São Paulo")
    WEATHER_LAT: float = float(os.getenv("WEATHER_LAT", "-23.5505"))
    WEATHER_LON: float = float(os.getenv("WEATHER_LON", "-46.6333"))
    LOG_DIR: str = os.getenv("LOG_DIR", "./logs")
    LOG_RETENTION_DAYS: int = int(os.getenv("LOG_RETENTION_DAYS", "30"))
    LOG_FILENAME: str = os.getenv("LOG_FILENAME", "MiBandServer.log")

settings = Settings()

