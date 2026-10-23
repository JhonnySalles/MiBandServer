from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
import re

from app.core.database import (
    get_session, DeviceConfig, IntegrationConfig, ActivityLog,
    SyncHistory, SyncSchedule, WeatherHistory, IntradayActivitySample,
    SleepSummary, get_utc_now
)
from app.core.cache import cache
from app.core.scheduler import execute_sync_workflow, reload_scheduler_jobs
from app.services.miband import miband_service
from app.services.weather import weather_service

router = APIRouter()

class DeviceCreate(BaseModel):
    mac_address: str
    auth_key: str  # Obrigatória para comunicação Huami AES
    device_name: Optional[str] = "Mi Smart Band 6"
    sync_interval_hours: Optional[int] = 1
    sync_intervals: Optional[str] = "08:00,12:00,18:00,22:00"
    auto_weather: Optional[bool] = True
    is_active: Optional[bool] = True

class ScheduleCreate(BaseModel):
    device_mac: str
    scheduled_time: str  # "HH:MM"

class IntegrationUpdate(BaseModel):
    weather_provider: Optional[str] = "open-meteo"
    weather_api_token: Optional[str] = None
    weather_city: Optional[str] = "São Paulo"
    latitude: Optional[float] = -23.5505
    longitude: Optional[float] = -46.6333
    cache_ttl_minutes: Optional[int] = 30

class SyncRequest(BaseModel):
    mac_address: Optional[str] = None

class WeatherRequest(BaseModel):
    temp: Optional[int] = None
    condition: Optional[str] = None
    code: Optional[int] = None
    auto_fetch: Optional[bool] = False

@router.get("/status")
def get_status():
    return {
        "status": "online", 
        "service": "MiBandServer API",
        "redis_connected": cache.is_connected
    }

@router.get("/ble/scan")
async def scan_ble_devices():
    devices = await miband_service.scan_devices(timeout=4.0)
    return {"devices": devices}

# --- Gestão de Dispositivos (Multi-device) ---
@router.get("/devices", response_model=List[DeviceConfig])
def list_devices(session: Session = Depends(get_session)):
    devices = session.exec(select(DeviceConfig).order_by(DeviceConfig.id.desc())).all()
    # Adicionar last_sync_time a partir do Redis se não estiver gravado
    for d in devices:
        if not d.last_sync_time:
            redis_sync = cache.get(f"device:{d.mac_address}:last_sync")
            if redis_sync:
                try:
                    d.last_sync_time = datetime.fromisoformat(redis_sync)
                except Exception:
                    pass
    return devices

@router.get("/config", response_model=Optional[DeviceConfig])
def get_primary_device_config(session: Session = Depends(get_session)):
    device = session.exec(select(DeviceConfig).order_by(DeviceConfig.id.desc())).first()
    if device and not device.last_sync_time:
        redis_sync = cache.get(f"device:{device.mac_address}:last_sync")
        if redis_sync:
            try:
                device.last_sync_time = datetime.fromisoformat(redis_sync)
            except Exception:
                pass
    return device

@router.post("/config", response_model=DeviceConfig)
def save_device_config(data: DeviceCreate, session: Session = Depends(get_session)):
    clean_mac = data.mac_address.strip().upper()
    if not re.match(r"^([0-9A-F]{2}[:-]){5}([0-9A-F]{2})$", clean_mac):
        raise HTTPException(
            status_code=400,
            detail=f"Endereço MAC inválido ('{clean_mac}'). Formato esperado: XX:XX:XX:XX:XX:XX"
        )

    clean_key = data.auth_key.strip()
    if clean_key.startswith("0x") or clean_key.startswith("0X"):
        clean_key = clean_key[2:]
        
    if len(clean_key) != 32:
        raise HTTPException(
            status_code=400, 
            detail=f"Auth Key inválida ({len(clean_key)} caracteres). Deve conter exatamente 32 caracteres hexadecimais."
        )

    try:
        bytes.fromhex(clean_key)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Auth Key contém caracteres hexadecimais inválidos. Use apenas dígitos 0-9 e letras a-f."
        )

    existing = session.exec(select(DeviceConfig).where(DeviceConfig.mac_address == clean_mac)).first()
    if existing:
        existing.auth_key = clean_key
        existing.device_name = data.device_name or existing.device_name
        if data.sync_interval_hours is not None:
            existing.sync_interval_hours = data.sync_interval_hours
        if data.sync_intervals is not None:
            existing.sync_intervals = data.sync_intervals
        if data.auto_weather is not None:
            existing.auto_weather = data.auto_weather
        if data.is_active is not None:
            existing.is_active = data.is_active
        existing.updated_at = get_utc_now()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        cache.set(f"device:{existing.mac_address}:config", existing.model_dump(mode="json"))
        reload_scheduler_jobs()
        return existing

    new_device = DeviceConfig(
        mac_address=clean_mac,
        auth_key=clean_key,
        device_name=data.device_name or "Mi Smart Band 6",
        sync_interval_hours=data.sync_interval_hours or 1,
        sync_intervals=data.sync_intervals or "08:00,12:00,18:00,22:00",
        auto_weather=data.auto_weather if data.auto_weather is not None else True,
        is_active=data.is_active if data.is_active is not None else True
    )
    session.add(new_device)
    session.commit()
    session.refresh(new_device)
    cache.set(f"device:{new_device.mac_address}:config", new_device.model_dump(mode="json"))
    reload_scheduler_jobs()
    return new_device

@router.delete("/devices/{mac_address}")
def delete_device(mac_address: str, session: Session = Depends(get_session)):
    device = session.exec(select(DeviceConfig).where(DeviceConfig.mac_address == mac_address)).first()
    if not device:
        raise HTTPException(status_code=404, detail="Dispositivo não encontrado")
    
    # Remover horários agendados do dispositivo
    schedules = session.exec(select(SyncSchedule).where(SyncSchedule.device_mac == mac_address)).all()
    for s in schedules:
        session.delete(s)

    session.delete(device)
    session.commit()
    cache.delete(f"device:{mac_address}:config")
    cache.delete(f"device:{mac_address}:last_sync")
    reload_scheduler_jobs()
    return {"success": True, "message": f"Dispositivo {mac_address} removido com sucesso"}

# --- Gestão de Horários Fixos / Grid (SyncSchedule) ---
@router.get("/schedules", response_model=List[SyncSchedule])
def list_schedules(mac: Optional[str] = None, session: Session = Depends(get_session)):
    query = select(SyncSchedule)
    if mac:
        query = query.where(SyncSchedule.device_mac == mac)
    schedules = session.exec(query.order_by(SyncSchedule.scheduled_time.asc())).all()
    return schedules

@router.post("/schedules", response_model=SyncSchedule)
def add_schedule(data: ScheduleCreate, session: Session = Depends(get_session)):
    clean_time = data.scheduled_time.strip()
    existing = session.exec(
        select(SyncSchedule)
        .where(SyncSchedule.device_mac == data.device_mac, SyncSchedule.scheduled_time == clean_time)
    ).first()
    if existing:
        return existing
    
    new_schedule = SyncSchedule(device_mac=data.device_mac, scheduled_time=clean_time, is_active=True)
    session.add(new_schedule)
    session.commit()
    session.refresh(new_schedule)
    reload_scheduler_jobs()
    return new_schedule

@router.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, session: Session = Depends(get_session)):
    sched = session.exec(select(SyncSchedule).where(SyncSchedule.id == schedule_id)).first()
    if not sched:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado")
    session.delete(sched)
    session.commit()
    reload_scheduler_jobs()
    return {"success": True, "message": "Horário removido com sucesso"}

# --- Gestão de Integrações e Tokens (Clima) ---
@router.get("/integrations", response_model=IntegrationConfig)
def get_integration_config(session: Session = Depends(get_session)):
    config = session.exec(select(IntegrationConfig)).first()
    if not config:
        config = IntegrationConfig()
        session.add(config)
        session.commit()
        session.refresh(config)
    return config

@router.post("/integrations", response_model=IntegrationConfig)
def save_integration_config(data: IntegrationUpdate, session: Session = Depends(get_session)):
    config = session.exec(select(IntegrationConfig)).first()
    if not config:
        config = IntegrationConfig(**data.model_dump())
        session.add(config)
    else:
        if data.weather_provider is not None:
            config.weather_provider = data.weather_provider
        if data.weather_api_token is not None:
            config.weather_api_token = data.weather_api_token
        if data.weather_city is not None:
            config.weather_city = data.weather_city
        if data.latitude is not None:
            config.latitude = data.latitude
        if data.longitude is not None:
            config.longitude = data.longitude
        if data.cache_ttl_minutes is not None:
            config.cache_ttl_minutes = data.cache_ttl_minutes
        config.updated_at = get_utc_now()
        session.add(config)
    
    session.commit()
    session.refresh(config)
    # Limpa o cache antigo para forçar atualização imediata com os novos dados/tokens
    cache.delete("weather:forecast:*")
    cache.delete("weather:extended_forecast:*")
    cache.set("system:integration:config", config.model_dump(mode="json"))
    return config

# --- Sincronização e Operações BLE ---
@router.post("/sync")
async def trigger_manual_sync(req: SyncRequest, session: Session = Depends(get_session)):
    mac = req.mac_address
    auth_key = None
    auto_weather = True
    if mac:
        dev = session.exec(select(DeviceConfig).where(DeviceConfig.mac_address == mac)).first()
        if dev:
            auth_key = dev.auth_key
            auto_weather = dev.auto_weather
    else:
        dev = session.exec(select(DeviceConfig).order_by(DeviceConfig.id.desc())).first()
        if not dev:
            raise HTTPException(status_code=400, detail="Nenhum dispositivo configurado")
        mac = dev.mac_address
        auth_key = dev.auth_key
        auto_weather = dev.auto_weather

    # Executa o pipeline completo (Clima -> Conexão BLE -> Métricas -> Redis)
    result = await execute_sync_workflow(
        mac_address=mac,
        auth_key=auth_key,
        auto_weather=auto_weather,
        source="MANUAL"
    )
    return result

# --- Cidades e Geolocalização ---
@router.get("/weather/cities/search")
def search_cities(
    query: str,
    provider: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """Pesquisa cidades no provedor de clima ativo ou Open-Meteo"""
    integration = session.exec(select(IntegrationConfig)).first()
    prov = provider or (integration.weather_provider if integration else "open-meteo")
    token = integration.weather_api_token if integration else None
    return weather_service.search_cities(query=query, provider=prov, api_token=token)

@router.get("/weather/cities/reverse")
def reverse_geocode(
    latitude: float,
    longitude: float,
    provider: Optional[str] = None,
    session: Session = Depends(get_session)
):
    """Converte latitude e longitude no nome da cidade e detalhes"""
    integration = session.exec(select(IntegrationConfig)).first()
    prov = provider or (integration.weather_provider if integration else "open-meteo")
    token = integration.weather_api_token if integration else None
    res = weather_service.reverse_geocode(latitude=latitude, longitude=longitude, provider=prov, api_token=token)
    if not res:
        return {
            "name": "Localização Atual",
            "region": "",
            "country": "",
            "latitude": latitude,
            "longitude": longitude,
            "display_name": f"Lat: {latitude:.4f}, Lon: {longitude:.4f}"
        }
    return res

@router.get("/weather/cities/detect-ip")
def detect_location_by_ip():
    """Detecta a localização do usuário a partir do IP"""
    res = weather_service.detect_location_by_ip()
    if not res:
        return {
            "name": "São Paulo",
            "region": "São Paulo",
            "country": "Brasil",
            "latitude": -23.5505,
            "longitude": -46.6333,
            "display_name": "São Paulo, SP - Brasil"
        }
    return res

@router.get("/weather/current")
def get_current_weather_forecast(session: Session = Depends(get_session)):
    """Consulta a previsão do tempo com suporte aos tokens configurados"""
    integration = session.exec(select(IntegrationConfig)).first()
    provider = integration.weather_provider if integration else None
    token = integration.weather_api_token if integration else None
    city = integration.weather_city if integration else None
    lat = integration.latitude if integration else None
    lon = integration.longitude if integration else None

    forecast = weather_service.get_extended_forecast(
        latitude=lat,
        longitude=lon,
        provider=provider,
        api_token=token,
        city=city
    )

    # Gravar registro de histórico se não houver registro recente nos últimos 15 min
    if forecast:
        try:
            from datetime import timedelta
            target_city = city or "São Paulo"
            cutoff = get_utc_now() - timedelta(minutes=15)
            recent = session.exec(
                select(WeatherHistory)
                .where(WeatherHistory.city == target_city)
                .where(WeatherHistory.timestamp >= cutoff)
            ).first()

            if not recent:
                cur = forecast.get("current", {})
                daily0 = (forecast.get("daily_forecast") or [{}])[0]
                w_log = WeatherHistory(
                    timestamp=get_utc_now(),
                    city=target_city,
                    temp=int(cur.get("temp", 24)),
                    temp_min=daily0.get("temp_min"),
                    temp_max=daily0.get("temp_max"),
                    condition=str(cur.get("condition", "Ensolarado")),
                    humidity=cur.get("humidity"),
                    wind_speed=cur.get("wind_speed"),
                    weather_code=cur.get("code"),
                    provider=forecast.get("provider", provider or "Open-Meteo"),
                    source="PREVIEW"
                )
                session.add(w_log)
                session.commit()
        except Exception:
            pass

        forecast["city"] = target_city

    return forecast

@router.get("/weather/history", response_model=List[WeatherHistory])
def get_weather_history(limit: int = 30, session: Session = Depends(get_session)):
    """Retorna histórico de leituras meteorológicas capturadas e enviadas à Mi Band"""
    logs = session.exec(select(WeatherHistory).order_by(WeatherHistory.timestamp.desc()).limit(limit)).all()
    return logs

@router.post("/weather")
async def send_weather(req: WeatherRequest, session: Session = Depends(get_session)):
    dev = session.exec(select(DeviceConfig).order_by(DeviceConfig.id.desc())).first()
    if not dev:
        raise HTTPException(status_code=400, detail="Nenhum dispositivo configurado")

    integration = session.exec(select(IntegrationConfig)).first()
    provider = integration.weather_provider if integration else None
    token = integration.weather_api_token if integration else None
    city = integration.weather_city if integration else None
    lat = integration.latitude if integration else None
    lon = integration.longitude if integration else None

    # Obter dados estendidos completos para garantir previsão de vários dias, vento e sol
    weather_data = weather_service.get_extended_forecast(
        latitude=lat,
        longitude=lon,
        provider=provider,
        api_token=token,
        city=city
    )
    if weather_data:
        weather_data["city"] = city or "São Paulo"

    # Se o usuário especificou temperatura ou condição customizada manualmente no corpo da requisição:
    if not req.auto_fetch:
        if "current" in weather_data:
            if req.temp is not None:
                weather_data["current"]["temp"] = req.temp
            if req.condition:
                weather_data["current"]["condition"] = req.condition
            if req.code is not None:
                weather_data["current"]["code"] = req.code
            elif req.condition:
                # Remove código antigo do provedor para que o motor semântico deduza o código correto Huami da condição fornecida
                weather_data["current"]["code"] = None

    cur = weather_data.get("current", {})
    temp = cur.get("temp", 24)
    condition = cur.get("condition", "Ensolarado")

    success = await miband_service.send_weather_info(
        mac_address=dev.mac_address,
        temp=temp,
        condition=condition,
        auth_key=dev.auth_key,
        weather_data=weather_data
    )

    if success and weather_data:
        try:
            daily0 = (weather_data.get("daily_forecast") or [{}])[0]
            w_log = WeatherHistory(
                timestamp=get_utc_now(),
                city=weather_data.get("city", city or "São Paulo"),
                temp=int(temp),
                temp_min=daily0.get("temp_min"),
                temp_max=daily0.get("temp_max"),
                condition=str(condition),
                humidity=cur.get("humidity"),
                wind_speed=cur.get("wind_speed"),
                weather_code=cur.get("code"),
                provider=weather_data.get("provider", provider or "Open-Meteo"),
                source="MANUAL" if not req.auto_fetch else "AUTO"
            )
            session.add(w_log)
            session.commit()
        except Exception:
            pass

    return {"success": success, "sent_to": dev.mac_address, "temp": temp, "condition": condition}

@router.post("/vibrate")
async def trigger_vibrate(session: Session = Depends(get_session)):
    dev = session.exec(select(DeviceConfig).order_by(DeviceConfig.id.desc())).first()
    if not dev:
        raise HTTPException(status_code=400, detail="Nenhum dispositivo configurado")
    
    if not dev.auth_key:
        raise HTTPException(status_code=400, detail="Dispositivo não possui Auth Key cadastrada")

    success = await miband_service.send_vibrate_alert(dev.mac_address, dev.auth_key)
    if not success:
        return {
            "success": False, 
            "mac": dev.mac_address, 
            "message": "Não foi possível conectar à pulseira. Certifique-se de que o Bluetooth do celular está desconectado da Mi Band ou que ela está ao alcance."
        }
    return {"success": True, "mac": dev.mac_address, "message": "Comando de vibração enviado com sucesso!"}

@router.post("/stop-vibrate")
@router.post("/device/stop-vibrate")
async def stop_vibrate(session: Session = Depends(get_session)):
    """Interrompe imediatamente qualquer padrão de vibração/chamada ativo na Mi Smart Band 6"""
    dev = session.exec(select(DeviceConfig).order_by(DeviceConfig.id.desc())).first()
    if not dev:
        raise HTTPException(status_code=400, detail="Nenhum dispositivo configurado")
    
    success = await miband_service.stop_vibrate_alert(dev.mac_address, dev.auth_key)
    return {
        "success": success,
        "mac": dev.mac_address,
        "message": "Comando de parada de vibração (Stop Find) transmitido com sucesso!" if success else "Falha ao enviar cancelamento."
    }

@router.get("/metrics/latest", response_model=Optional[ActivityLog])
def get_latest_metrics(mac: Optional[str] = None, session: Session = Depends(get_session)):
    # 1. Tenta recuperar do cache Redis para economizar I/O no disco do Raspberry Pi
    if mac:
        cached = cache.get(f"latest_metrics:{mac}")
        if cached:
            return cached
            
    query = select(ActivityLog)
    if mac:
        query = query.where(ActivityLog.device_mac == mac)
    log = session.exec(query.order_by(ActivityLog.timestamp.desc())).first()
    return log

@router.get("/metrics/history", response_model=List[ActivityLog])
def get_metrics_history(limit: int = 30, mac: Optional[str] = None, session: Session = Depends(get_session)):
    query = select(ActivityLog)
    if mac:
        query = query.where(ActivityLog.device_mac == mac)
    logs = session.exec(query.order_by(ActivityLog.timestamp.desc()).limit(limit)).all()
    return logs

@router.get("/activity/intraday", response_model=List[IntradayActivitySample])
def get_intraday_activity(
    mac: Optional[str] = None,
    date: Optional[str] = None,
    limit: int = 500,
    session: Session = Depends(get_session)
):
    """Retorna amostras intradiárias de atividade e sono minuto a minuto extraídas da pulseira"""
    query = select(IntradayActivitySample)
    if mac:
        query = query.where(IntradayActivitySample.device_mac == mac)
    if date:
        try:
            start_d = datetime.strptime(date, "%Y-%m-%d")
            end_d = start_d + timedelta(days=1)
            query = query.where(IntradayActivitySample.timestamp >= start_d).where(IntradayActivitySample.timestamp < end_d)
        except Exception:
            pass
    samples = session.exec(query.order_by(IntradayActivitySample.timestamp.desc()).limit(limit)).all()
    return samples

@router.get("/activity/sleep", response_model=List[SleepSummary])
def get_sleep_history(mac: Optional[str] = None, limit: int = 30, session: Session = Depends(get_session)):
    """Retorna o histórico de sessões e estágios de sono (leve, profundo, REM, acordado)"""
    query = select(SleepSummary)
    if mac:
        query = query.where(SleepSummary.device_mac == mac)
    records = session.exec(query.order_by(SleepSummary.date.desc()).limit(limit)).all()
    return records

@router.get("/sync/history", response_model=List[SyncHistory])
def get_sync_history(limit: int = 20, session: Session = Depends(get_session)):
    logs = session.exec(select(SyncHistory).order_by(SyncHistory.timestamp.desc()).limit(limit)).all()
    return logs


