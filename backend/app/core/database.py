from datetime import datetime, timezone
from typing import Optional
from sqlmodel import Field, SQLModel, create_engine, Session
from app.core.config import settings
import os

def get_utc_now() -> datetime:
    return datetime.now(timezone.utc)

class DeviceConfig(SQLModel, table=True):
    __tablename__ = "device_config"
    id: Optional[int] = Field(default=None, primary_key=True)
    mac_address: str = Field(index=True, unique=True)
    auth_key: Optional[str] = None
    device_name: Optional[str] = "Mi Smart Band 6"
    is_active: bool = Field(default=True)
    sync_interval_hours: int = Field(default=1)  # Sincronizar a cada X horas (ex: 1, 3, 5)
    sync_intervals: Optional[str] = Field(default="08:00,12:00,18:00,22:00")  # Horários específicos separados por vírgula (ex: 07:15, 12:00)
    auto_weather: bool = Field(default=True)
    last_sync_time: Optional[datetime] = None  # Timestamp da última sincronização bem sucedida
    created_at: datetime = Field(default_factory=get_utc_now)
    updated_at: datetime = Field(default_factory=get_utc_now)

class SyncSchedule(SQLModel, table=True):
    __tablename__ = "sync_schedule"
    id: Optional[int] = Field(default=None, primary_key=True)
    device_mac: str = Field(index=True)
    scheduled_time: str = Field(index=True)  # Formato "HH:MM", ex: "07:30"
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=get_utc_now)

class IntegrationConfig(SQLModel, table=True):
    __tablename__ = "integration_config"
    id: Optional[int] = Field(default=None, primary_key=True)
    weather_provider: str = Field(default="open-meteo")  # "open-meteo", "openweathermap", "weatherapi"
    weather_api_token: Optional[str] = None
    weather_city: Optional[str] = "São Paulo"
    latitude: Optional[float] = -23.5505
    longitude: Optional[float] = -46.6333
    cache_ttl_minutes: int = Field(default=30)
    updated_at: datetime = Field(default_factory=get_utc_now)

class ActivityLog(SQLModel, table=True):
    __tablename__ = "activity_log"
    id: Optional[int] = Field(default=None, primary_key=True)
    device_mac: str = Field(index=True)
    timestamp: datetime = Field(default_factory=get_utc_now, index=True)
    steps: int = Field(default=0)
    distance_meters: int = Field(default=0)
    calories: int = Field(default=0)
    heart_rate: Optional[int] = None
    battery_level: Optional[int] = None

class SyncHistory(SQLModel, table=True):
    __tablename__ = "sync_history"
    id: Optional[int] = Field(default=None, primary_key=True)
    device_mac: Optional[str] = Field(default=None, index=True)
    timestamp: datetime = Field(default_factory=get_utc_now)
    status: str  # "SUCCESS", "ERROR", "IN_PROGRESS"
    message: Optional[str] = None
    details: Optional[str] = None

# Garantir pasta do banco SQLite se for sqlite
if settings.DB_URL.startswith("sqlite"):
    db_path = settings.DB_URL.replace("sqlite:///", "")
    dir_name = os.path.dirname(db_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

engine = create_engine(settings.DB_URL, connect_args={"check_same_thread": False} if "sqlite" in settings.DB_URL else {})

def init_db():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

