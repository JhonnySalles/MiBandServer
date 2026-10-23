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
    spo2: Optional[int] = None  # Saturação de oxigênio (80-100%)
    stress: Optional[int] = None  # Nível de estresse HRV (1-100)
    pai_today: Optional[int] = None  # Pontos PAI obtidos hoje
    pai_total: Optional[int] = None  # Pontuação PAI acumulada (7 dias)

class SyncHistory(SQLModel, table=True):
    __tablename__ = "sync_history"
    id: Optional[int] = Field(default=None, primary_key=True)
    device_mac: Optional[str] = Field(default=None, index=True)
    timestamp: datetime = Field(default_factory=get_utc_now)
    status: str  # "SUCCESS", "ERROR", "IN_PROGRESS"
    message: Optional[str] = None
    details: Optional[str] = None

class WeatherHistory(SQLModel, table=True):
    __tablename__ = "weather_history"
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=get_utc_now, index=True)
    city: str = Field(index=True)
    temp: int
    temp_min: Optional[int] = None
    temp_max: Optional[int] = None
    condition: str
    humidity: Optional[int] = None
    wind_speed: Optional[int] = None
    weather_code: Optional[int] = None
    provider: str = Field(default="Open-Meteo")
    source: str = Field(default="SYNC")  # "SYNC_AUTO", "SYNC_MANUAL", "PREVIEW"
    created_at: datetime = Field(default_factory=get_utc_now)

class BandSettings(SQLModel, table=True):
    __tablename__ = "band_settings"
    id: Optional[int] = Field(default=None, primary_key=True)
    device_mac: str = Field(index=True, unique=True)
    event_reminders: Optional[str] = Field(default="[]")
    alarms: Optional[str] = Field(default="[]")
    world_clocks: Optional[str] = Field(default='[{"city": "São Paulo", "timezone": -3}, {"city": "Londres", "timezone": 0}, {"city": "Nova York", "timezone": -4}, {"city": "Tóquio", "timezone": 9}]')
    lift_wrist_mode: str = Field(default="all_day")  # "off", "all_day", "scheduled"
    lift_wrist_start: str = Field(default="07:00")
    lift_wrist_end: str = Field(default="22:00")
    lift_wrist_speed: str = Field(default="normal")  # "normal", "fast"
    night_mode: str = Field(default="sunset")  # "off", "sunset", "scheduled"
    night_mode_start: str = Field(default="22:00")
    night_mode_end: str = Field(default="07:00")
    dnd_mode: str = Field(default="smart")  # "off", "always", "smart", "scheduled"
    wear_location: str = Field(default="left")  # "left", "right"
    language: str = Field(default="pt_BR")
    heart_rate_interval: int = Field(default=5)  # Intervalo em minutos (0=desligado, 1, 5, 10, 30)
    step_goal: int = Field(default=8000)  # Meta diária de passos
    calorie_goal: int = Field(default=300)  # Meta diária de calorias (kcal)
    all_day_stress: bool = Field(default=True)  # Monitoramento contínuo de estresse
    stress_interval: int = Field(default=5)  # Intervalo de medição de estresse em minutos
    updated_at: datetime = Field(default_factory=get_utc_now)

class IntradayActivitySample(SQLModel, table=True):
    __tablename__ = "intraday_activity_sample"
    id: Optional[int] = Field(default=None, primary_key=True)
    device_mac: str = Field(index=True)
    timestamp: datetime = Field(index=True)
    category: int = Field(default=0)  # 0=inativo, 1=caminhada, 2=corrida, 80=sono leve, 81=sono profundo, 82=rem, 83=acordado
    steps: int = Field(default=0)
    intensity: int = Field(default=0)
    heart_rate: Optional[int] = None
    spo2: Optional[int] = None
    stress: Optional[int] = None
    created_at: datetime = Field(default_factory=get_utc_now)

class SleepSummary(SQLModel, table=True):
    __tablename__ = "sleep_summary"
    id: Optional[int] = Field(default=None, primary_key=True)
    device_mac: str = Field(index=True)
    date: str = Field(index=True)  # Formato YYYY-MM-DD
    start_time: datetime
    end_time: datetime
    total_sleep_minutes: int = Field(default=0)
    deep_sleep_minutes: int = Field(default=0)
    light_sleep_minutes: int = Field(default=0)
    rem_sleep_minutes: int = Field(default=0)
    awake_minutes: int = Field(default=0)
    created_at: datetime = Field(default_factory=get_utc_now)


# Garantir pasta do banco SQLite se for sqlite
if settings.DB_URL.startswith("sqlite"):
    db_path = settings.DB_URL.replace("sqlite:///", "")
    dir_name = os.path.dirname(db_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

engine = create_engine(
    settings.DB_URL,
    connect_args={"check_same_thread": False, "timeout": 30.0} if "sqlite" in settings.DB_URL else {}
)

def init_db():
    SQLModel.metadata.create_all(engine)
    # Migrações suaves para SQLite: verificar e adicionar colunas ausentes
    try:
        with engine.connect() as conn:
            from sqlalchemy import text
            
            # 1. Tabela band_settings
            res = conn.execute(text("PRAGMA table_info(band_settings)"))
            cols_b = [row[1] for row in res.fetchall()]
            if "heart_rate_interval" not in cols_b and "id" in cols_b:
                conn.execute(text("ALTER TABLE band_settings ADD COLUMN heart_rate_interval INTEGER DEFAULT 5"))
            if "step_goal" not in cols_b and "id" in cols_b:
                conn.execute(text("ALTER TABLE band_settings ADD COLUMN step_goal INTEGER DEFAULT 8000"))
            if "calorie_goal" not in cols_b and "id" in cols_b:
                conn.execute(text("ALTER TABLE band_settings ADD COLUMN calorie_goal INTEGER DEFAULT 300"))
            if "all_day_stress" not in cols_b and "id" in cols_b:
                conn.execute(text("ALTER TABLE band_settings ADD COLUMN all_day_stress BOOLEAN DEFAULT 1"))
            if "stress_interval" not in cols_b and "id" in cols_b:
                conn.execute(text("ALTER TABLE band_settings ADD COLUMN stress_interval INTEGER DEFAULT 5"))
            
            # 2. Tabela activity_log
            res_a = conn.execute(text("PRAGMA table_info(activity_log)"))
            cols_a = [row[1] for row in res_a.fetchall()]
            if "spo2" not in cols_a and "id" in cols_a:
                conn.execute(text("ALTER TABLE activity_log ADD COLUMN spo2 INTEGER"))
            if "stress" not in cols_a and "id" in cols_a:
                conn.execute(text("ALTER TABLE activity_log ADD COLUMN stress INTEGER"))
            if "pai_today" not in cols_a and "id" in cols_a:
                conn.execute(text("ALTER TABLE activity_log ADD COLUMN pai_today INTEGER"))
            if "pai_total" not in cols_a and "id" in cols_a:
                conn.execute(text("ALTER TABLE activity_log ADD COLUMN pai_total INTEGER"))

            # 3. Tabela intraday_activity_sample
            res_i = conn.execute(text("PRAGMA table_info(intraday_activity_sample)"))
            cols_i = [row[1] for row in res_i.fetchall()]
            if "spo2" not in cols_i and "id" in cols_i:
                conn.execute(text("ALTER TABLE intraday_activity_sample ADD COLUMN spo2 INTEGER"))
            if "stress" not in cols_i and "id" in cols_i:
                conn.execute(text("ALTER TABLE intraday_activity_sample ADD COLUMN stress INTEGER"))

            conn.commit()
    except Exception:
        pass

def get_session():
    with Session(engine) as session:
        yield session

