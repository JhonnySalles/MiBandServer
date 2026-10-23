import asyncio
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
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

class StreamTestRequest(BaseModel):
    action: str  # 'read_all', 'activity', 'battery', 'device_info', 'time_read', 'time_sync', 'alarms', 'heart_rate', 'spo2', 'stress', 'fitness_goals', 'pai', 'weather_preview', 'weather_send', 'notify', 'vibrate'
    mac_address: Optional[str] = None
    auth_key: Optional[str] = None
    city: Optional[str] = "São Paulo"
    current: Optional[Dict[str, Any]] = None
    daily_forecast: Optional[List[Dict[str, Any]]] = None
    category: Optional[int] = 3
    title: Optional[str] = "MiBand Server"
    text: Optional[str] = "Mensagem de Teste"
    count: Optional[int] = 2
    step_goal: Optional[int] = 8000
    calorie_goal: Optional[int] = 300
    total_pai: Optional[int] = 100
    today_pai: Optional[int] = 15

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

@router.post("/stream")
async def test_stream(req: StreamTestRequest, session: Session = Depends(get_session)):
    """Executa qualquer ação de teste BLE com streaming em tempo real via Server-Sent Events (SSE)"""
    event_queue: asyncio.Queue = asyncio.Queue()

    worker_task: Optional[asyncio.Task] = None

    if req.action == "weather_preview":
        integration = session.exec(select(IntegrationConfig)).first()
        provider = integration.weather_provider if integration else None
        token = integration.weather_api_token if integration else None
        city = req.city or (integration.weather_city if integration else None)
        lat = integration.latitude if integration else None
        lon = integration.longitude if integration else None

        async def run_weather_preview():
            try:
                event_queue.put_nowait({"type": "progress", "step": "fetching", "message": "Consultando provedor meteorológico...", "percent": 30})
                event_queue.put_nowait({"type": "progress", "step": "fetching", "message": f"Buscando previsão para {city or 'São Paulo'}...", "percent": 65})
                forecast = weather_service.get_extended_forecast(
                    latitude=lat,
                    longitude=lon,
                    provider=provider,
                    api_token=token,
                    city=city
                )
                daily_len = len(forecast.get("daily_forecast", [])) if forecast else 0
                event_queue.put_nowait({
                    "type": "complete",
                    "success": True,
                    "duration_ms": 120,
                    "data": forecast,
                    "error": None,
                    "logs": [
                        {"level": "INFO", "msg": f"Previsão consultada: {daily_len} dias carregados.", "ts": "agora"}
                    ]
                })
            except Exception as e:
                event_queue.put_nowait({
                    "type": "complete",
                    "success": False,
                    "duration_ms": 0,
                    "data": None,
                    "error": str(e),
                    "logs": [
                        {"level": "ERROR", "msg": f"Erro na previsão: {str(e)}", "ts": "agora"}
                    ]
                })
            finally:
                event_queue.put_nowait(None)

        worker_task = asyncio.create_task(run_weather_preview())
    else:
        try:
            mac, key = _resolve_device_credentials(req, session)
        except Exception as e:
            event_queue.put_nowait({
                "type": "complete",
                "success": False,
                "duration_ms": 0,
                "data": None,
                "error": str(e),
                "logs": [{"level": "ERROR", "msg": str(e), "ts": "agora"}]
            })
            event_queue.put_nowait(None)
            async def empty_gen():
                while True:
                    item = await event_queue.get()
                    if item is None:
                        break
                    yield f"data: {json.dumps(item)}\n\n"
            return StreamingResponse(empty_gen(), media_type="text/event-stream")

        async def run_ble_test():
            try:
                if req.action == "read_all":
                    await miband_test_service.test_read_all(mac, key, event_queue)
                elif req.action == "activity":
                    await miband_test_service.test_read_activity(mac, key, event_queue)
                elif req.action == "battery":
                    await miband_test_service.test_read_battery(mac, key, event_queue)
                elif req.action == "device_info":
                    await miband_test_service.test_read_device_info(mac, key, event_queue)
                elif req.action == "time_read":
                    await miband_test_service.test_read_time(mac, key, event_queue)
                elif req.action == "time_sync":
                    await miband_test_service.test_sync_time(mac, key, event_queue)
                elif req.action == "alarms":
                    await miband_test_service.test_read_alarms(mac, key, event_queue)
                elif req.action == "heart_rate":
                    await miband_test_service.test_read_heart_rate(mac, key, event_queue)
                elif req.action == "weather_send":
                    await miband_test_service.test_send_weather(
                        mac_address=mac,
                        auth_key=key,
                        current_weather=req.current or {},
                        daily_forecast=req.daily_forecast or [],
                        city=req.city or "São Paulo",
                        event_queue=event_queue
                    )
                elif req.action == "notify":
                    await miband_test_service.test_send_notification(
                        mac_address=mac,
                        auth_key=key,
                        category=req.category or 3,
                        title=req.title or "MiBand Server",
                        text=req.text or "Mensagem de Teste",
                        event_queue=event_queue
                    )
                elif req.action == "vibrate":
                    await miband_test_service.test_trigger_vibrate(
                        mac_address=mac,
                        auth_key=key,
                        count=req.count or 2,
                        text=req.text or "Localizar MiBand",
                        event_queue=event_queue
                    )
                elif req.action == "spo2":
                    await miband_test_service.test_measure_spo2(mac, key, event_queue)
                elif req.action == "stress":
                    await miband_test_service.test_measure_stress(mac, key, event_queue)
                elif req.action == "fitness_goals":
                    await miband_test_service.test_send_fitness_goals(
                        mac_address=mac,
                        auth_key=key,
                        step_goal=req.step_goal or 8000,
                        calorie_goal=req.calorie_goal or 300,
                        event_queue=event_queue
                    )
                elif req.action == "pai":
                    await miband_test_service.test_send_pai(
                        mac_address=mac,
                        auth_key=key,
                        total_pai=req.total_pai if req.total_pai is not None else 100,
                        today_pai=req.today_pai if req.today_pai is not None else 15,
                        event_queue=event_queue
                    )
                else:
                    event_queue.put_nowait({
                        "type": "complete",
                        "success": False,
                        "duration_ms": 0,
                        "data": None,
                        "error": f"Ação desconhecida: {req.action}",
                        "logs": []
                    })
                    event_queue.put_nowait(None)
            except Exception as ex:
                event_queue.put_nowait({
                    "type": "complete",
                    "success": False,
                    "duration_ms": 0,
                    "data": None,
                    "error": str(ex),
                    "logs": [{"level": "ERROR", "msg": f"Exceção interna: {str(ex)}", "ts": "agora"}]
                })
                event_queue.put_nowait(None)

        worker_task = asyncio.create_task(run_ble_test())

    async def event_generator():
        try:
            while True:
                item = await event_queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n"
        except asyncio.CancelledError:
            if worker_task and not worker_task.done():
                worker_task.cancel()
            raise

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

# -------------------------------------------------------------
# Rotas HTTP Síncronas (Retrocompatibilidade)
# -------------------------------------------------------------
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
