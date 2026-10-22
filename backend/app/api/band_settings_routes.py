import json
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from typing import Optional, List, Dict, Any
from pydantic import BaseModel
from bleak import BleakClient

from app.core.database import get_session, DeviceConfig, BandSettings, get_utc_now
from app.services.miband_protocol import MiBandProtocol
from app.services.miband import miband_service

router = APIRouter()

class BandSettingsUpdate(BaseModel):
    device_mac: Optional[str] = None
    event_reminders: Optional[List[Dict[str, Any]]] = None
    alarms: Optional[List[Dict[str, Any]]] = None
    world_clocks: Optional[List[Dict[str, Any]]] = None
    lift_wrist_mode: Optional[str] = None
    lift_wrist_start: Optional[str] = None
    lift_wrist_end: Optional[str] = None
    lift_wrist_speed: Optional[str] = None
    night_mode: Optional[str] = None
    night_mode_start: Optional[str] = None
    night_mode_end: Optional[str] = None
    dnd_mode: Optional[str] = None
    wear_location: Optional[str] = None
    language: Optional[str] = None

class BandSettingsSyncRequest(BaseModel):
    device_mac: Optional[str] = None
    scope: Optional[str] = "all"  # "all", "alarms", "world_clocks", "reminders", "wrist", "night", "language", "wear_location"

def _get_or_create_settings(session: Session, mac_address: Optional[str] = None) -> BandSettings:
    query = select(DeviceConfig)
    if mac_address:
        query = query.where(DeviceConfig.mac_address == mac_address.strip().upper())
    else:
        query = query.order_by(DeviceConfig.id.desc())
    
    dev = session.exec(query).first()
    if not dev:
        raise HTTPException(status_code=400, detail="Nenhum dispositivo encontrado no banco de dados.")

    settings = session.exec(select(BandSettings).where(BandSettings.device_mac == dev.mac_address)).first()
    if not settings:
        settings = BandSettings(
            device_mac=dev.mac_address,
            event_reminders="[]",
            alarms="[]",
            world_clocks=json.dumps([
                {"city": "São Paulo", "timezone": -3},
                {"city": "Londres", "timezone": 0},
                {"city": "Nova York", "timezone": -4},
                {"city": "Tóquio", "timezone": 9}
            ], ensure_ascii=False),
            lift_wrist_mode="all_day",
            lift_wrist_start="07:00",
            lift_wrist_end="22:00",
            lift_wrist_speed="normal",
            night_mode="sunset",
            night_mode_start="22:00",
            night_mode_end="07:00",
            dnd_mode="smart",
            wear_location="left",
            language="pt_BR"
        )
        session.add(settings)
        session.commit()
        session.refresh(settings)

    return settings

@router.get("/settings")
def get_band_settings(mac: Optional[str] = None, session: Session = Depends(get_session)):
    """Retorna as configurações atuais gravadas no banco de dados para a Mi Band"""
    settings = _get_or_create_settings(session, mac)
    
    # Decodificar campos JSON para retorno estruturado
    data = settings.model_dump(mode="json")
    try:
        data["event_reminders"] = json.loads(settings.event_reminders or "[]")
    except Exception:
        data["event_reminders"] = []

    try:
        data["alarms"] = json.loads(settings.alarms or "[]")
    except Exception:
        data["alarms"] = []

    try:
        data["world_clocks"] = json.loads(settings.world_clocks or "[]")
    except Exception:
        data["world_clocks"] = []

    return data

@router.put("/settings")
def update_band_settings(payload: BandSettingsUpdate, session: Session = Depends(get_session)):
    """Atualiza as configurações no banco de dados SQLite"""
    settings = _get_or_create_settings(session, payload.device_mac)

    if payload.event_reminders is not None:
        settings.event_reminders = json.dumps(payload.event_reminders, ensure_ascii=False)
    if payload.alarms is not None:
        settings.alarms = json.dumps(payload.alarms, ensure_ascii=False)
    if payload.world_clocks is not None:
        settings.world_clocks = json.dumps(payload.world_clocks, ensure_ascii=False)
    if payload.lift_wrist_mode is not None:
        settings.lift_wrist_mode = payload.lift_wrist_mode
    if payload.lift_wrist_start is not None:
        settings.lift_wrist_start = payload.lift_wrist_start
    if payload.lift_wrist_end is not None:
        settings.lift_wrist_end = payload.lift_wrist_end
    if payload.lift_wrist_speed is not None:
        settings.lift_wrist_speed = payload.lift_wrist_speed
    if payload.night_mode is not None:
        settings.night_mode = payload.night_mode
    if payload.night_mode_start is not None:
        settings.night_mode_start = payload.night_mode_start
    if payload.night_mode_end is not None:
        settings.night_mode_end = payload.night_mode_end
    if payload.dnd_mode is not None:
        settings.dnd_mode = payload.dnd_mode
    if payload.wear_location is not None:
        settings.wear_location = payload.wear_location
    if payload.language is not None:
        settings.language = payload.language

    settings.updated_at = get_utc_now()
    session.add(settings)
    session.commit()
    session.refresh(settings)

    return {"success": True, "message": "Configurações salvas no servidor!", "settings": get_band_settings(settings.device_mac, session)}

@router.post("/settings/sync")
async def sync_band_settings(req: BandSettingsSyncRequest, session: Session = Depends(get_session)):
    """Transmite as configurações selecionadas diretamente para a Mi Band 6 via BLE"""
    settings = _get_or_create_settings(session, req.device_mac)
    dev = session.exec(select(DeviceConfig).where(DeviceConfig.mac_address == settings.device_mac)).first()
    if not dev or not dev.auth_key:
        raise HTTPException(status_code=400, detail="Dispositivo ou Auth Key não encontrados.")

    clean_key = dev.auth_key.strip()
    if clean_key.startswith("0x") or clean_key.startswith("0X"):
        clean_key = clean_key[2:]

    if miband_service._ble_lock.locked():
        raise HTTPException(status_code=409, detail="Canal Bluetooth ocupado por outra operação no momento.")

    results: Dict[str, Any] = {}
    scope = req.scope or "all"

    async with miband_service._ble_lock:
        try:
            async with BleakClient(dev.mac_address, timeout=15.0) as client:
                if not client.is_connected:
                    raise HTTPException(status_code=504, detail="Não foi possível conectar ao dispositivo BLE.")

                protocol = MiBandProtocol(client, clean_key)
                auth_ok = await protocol.authenticate()
                if not auth_ok:
                    raise HTTPException(status_code=401, detail="Autenticação BLE rejeitada pela pulseira.")

                # Sincronização conforme escopo
                if scope in ("all", "wear_location"):
                    ok = await protocol.set_wear_location(settings.wear_location)
                    results["wear_location"] = ok

                if scope in ("all", "wrist"):
                    ok = await protocol.set_lift_wrist(
                        mode=settings.lift_wrist_mode,
                        start_time=settings.lift_wrist_start,
                        end_time=settings.lift_wrist_end,
                        speed=settings.lift_wrist_speed
                    )
                    results["lift_wrist"] = ok

                if scope in ("all", "night"):
                    ok = await protocol.set_night_mode(
                        mode=settings.night_mode,
                        start_time=settings.night_mode_start,
                        end_time=settings.night_mode_end,
                        dnd_mode=settings.dnd_mode
                    )
                    results["night_mode"] = ok

                if scope in ("all", "language"):
                    ok = await protocol.set_band_language(settings.language)
                    results["language"] = ok

                if scope in ("all", "alarms"):
                    alarms_list = json.loads(settings.alarms or "[]")
                    ok = await protocol.set_alarms(alarms_list)
                    results["alarms"] = ok

                if scope in ("all", "world_clocks"):
                    clocks_list = json.loads(settings.world_clocks or "[]")
                    ok = await protocol.set_world_clocks(clocks_list)
                    results["world_clocks"] = ok

                if scope in ("all", "reminders"):
                    reminders_list = json.loads(settings.event_reminders or "[]")
                    ok = await protocol.set_event_reminders(reminders_list)
                    results["event_reminders"] = ok

                return {
                    "success": True,
                    "message": "Configurações sincronizadas com sucesso com a Mi Band 6!",
                    "scope": scope,
                    "results": results
                }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro durante sincronização BLE: {str(e)}")

@router.post("/settings/read")
async def read_band_settings(req: BandSettingsSyncRequest, session: Session = Depends(get_session)):
    """Lê os alarmes e dados atuais gravados na Mi Band 6 e atualiza no banco de dados"""
    settings = _get_or_create_settings(session, req.device_mac)
    dev = session.exec(select(DeviceConfig).where(DeviceConfig.mac_address == settings.device_mac)).first()
    if not dev or not dev.auth_key:
        raise HTTPException(status_code=400, detail="Dispositivo ou Auth Key não encontrados.")

    clean_key = dev.auth_key.strip()
    if clean_key.startswith("0x") or clean_key.startswith("0X"):
        clean_key = clean_key[2:]

    if miband_service._ble_lock.locked():
        raise HTTPException(status_code=409, detail="Canal Bluetooth ocupado por outra operação no momento.")

    async with miband_service._ble_lock:
        try:
            async with BleakClient(dev.mac_address, timeout=15.0) as client:
                if not client.is_connected:
                    raise HTTPException(status_code=504, detail="Não foi possível conectar ao dispositivo BLE.")

                protocol = MiBandProtocol(client, clean_key)
                auth_ok = await protocol.authenticate()
                if not auth_ok:
                    raise HTTPException(status_code=401, detail="Autenticação BLE rejeitada pela pulseira.")

                # Ler alarmes
                alarms = await protocol.request_alarms(timeout=6.0)
                if alarms:
                    settings.alarms = json.dumps(alarms, ensure_ascii=False)
                    settings.updated_at = get_utc_now()
                    session.add(settings)
                    session.commit()
                    session.refresh(settings)

                return {
                    "success": True,
                    "message": f"Leitura concluída! {len(alarms)} alarmes lidos da pulseira.",
                    "alarms": alarms,
                    "settings": get_band_settings(settings.device_mac, session)
                }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro durante leitura BLE: {str(e)}")
