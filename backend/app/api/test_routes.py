from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import Optional, List, Dict, Any
from pydantic import BaseModel

from app.core.database import get_session, DeviceConfig, IntegrationConfig
from app.services.miband_test import miband_test_service
from app.services.weather import weather_service

router = APIRouter()

class BaseTestRequest(BaseModel):
    mac_address: Optional[str] = None
    auth_key: Optional[str] = None

class WeatherSendRequest(BaseTestRequest):
    city: Optional[str] = "São Paulo"
    current: Dict[str, Any]
    daily_forecast: List[Dict[str, Any]]

class NotifyRequest(BaseTestRequest):
    category: Optional[int] = 3
    title: Optional[str] = "MiBand Server"
    text: Optional[str] = "Mensagem de Teste"

class VibrateRequest(BaseTestRequest):
    count: Optional[int] = 2
    text: Optional[str] = "Localizar MiBand"

def _resolve_device_credentials(req: BaseTestRequest, session: Session) -> tuple[str, str]:
    mac = req.mac_address
    auth_key = req.auth_key

    if not mac or not auth_key:
        query = select(DeviceConfig)
        if mac:
            query = query.where(DeviceConfig.mac_address == mac.strip().upper())
        else:
            query = query.order_by(DeviceConfig.id.desc())
        
        dev = session.exec(query).first()
        if not dev:
            raise HTTPException(status_code=400, detail="Nenhum dispositivo encontrado no banco de dados.")
        
        mac = mac or dev.mac_address
        auth_key = auth_key or dev.auth_key

    if not mac or not auth_key:
        raise HTTPException(status_code=400, detail="Endereço MAC e Auth Key são obrigatórios.")

    return mac.strip().upper(), auth_key.strip()

@router.get("/weather/preview")
def preview_weather(session: Session = Depends(get_session)):
    """Obtém a previsão do tempo estendida (Open-Meteo ou API configurada) para visualização e edição nos cards de teste"""
    integration = session.exec(select(IntegrationConfig)).first()
    provider = integration.weather_provider if integration else None
    token = integration.weather_api_token if integration else None
    city = integration.weather_city if integration else None
    lat = integration.latitude if integration else None
    lon = integration.longitude if integration else None

    return weather_service.get_extended_forecast(
        latitude=lat,
        longitude=lon,
        provider=provider,
        api_token=token,
        city=city
    )

@router.post("/read-all")
async def test_read_all(req: BaseTestRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_read_all(mac, key)

@router.post("/read/activity")
async def test_read_activity(req: BaseTestRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_read_activity(mac, key)

@router.post("/read/battery")
async def test_read_battery(req: BaseTestRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_read_battery(mac, key)

@router.post("/read/device-info")
async def test_read_device_info(req: BaseTestRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_read_device_info(mac, key)

@router.post("/read/time")
async def test_read_time(req: BaseTestRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_read_time(mac, key)

@router.post("/time/sync")
async def test_sync_time(req: BaseTestRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_sync_time(mac, key)

@router.post("/read/alarms")
async def test_read_alarms(req: BaseTestRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_read_alarms(mac, key)

@router.post("/read/heart-rate")
async def test_read_heart_rate(req: BaseTestRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_read_heart_rate(mac, key)

@router.post("/weather/send")
async def test_send_weather(req: WeatherSendRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_send_weather(
        mac_address=mac,
        auth_key=key,
        current_weather=req.current,
        daily_forecast=req.daily_forecast,
        city=req.city or "São Paulo"
    )

@router.post("/notify")
async def test_send_notification(req: NotifyRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_send_notification(
        mac_address=mac,
        auth_key=key,
        category=req.category or 3,
        title=req.title or "MiBand Server",
        text=req.text or "Mensagem de Teste"
    )

@router.post("/vibrate")
async def test_trigger_vibrate(req: VibrateRequest, session: Session = Depends(get_session)):
    mac, key = _resolve_device_credentials(req, session)
    return await miband_test_service.test_trigger_vibrate(
        mac_address=mac,
        auth_key=key,
        count=req.count or 2,
        text=req.text or "Localizar MiBand"
    )
