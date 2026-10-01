import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlmodel import Session, select
from datetime import datetime

from app.core.database import engine, DeviceConfig, ActivityLog, SyncHistory
from app.services.miband import miband_service
from app.services.weather import weather_service

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()

async def run_scheduled_sync():
    """Executa a sincronização programada dos dispositivos cadastrados"""
    logger.info("Verificando dispositivos para sincronização automática...")
    with Session(engine) as session:
        devices = session.exec(select(DeviceConfig).where(DeviceConfig.is_active == True)).all()
        now_str = datetime.now().strftime("%H:%M")

        for dev in devices:
            times = [t.strip() for t in (dev.sync_intervals or "").split(",") if t.strip()]
            # Checar se o horário atual coincide com os horários cadastrados
            if now_str in times or len(times) == 0:
                logger.info(f"Horário de sincronização atingido para o dispositivo {dev.mac_address} ({now_str})")
                
                # 1. Sincronizar Métricas da Pulseira
                res = await miband_service.sync_band(dev.mac_address, dev.auth_key)
                status_code = res.get("status", "ERROR")
                
                # 2. Se auto_weather estiver ativado, obter previsão e enviar para o relógio
                weather_info = ""
                if dev.auto_weather:
                    w = weather_service.get_current_weather()
                    await miband_service.send_weather_info(dev.mac_address, w["temp"], w["condition"])
                    weather_info = f" | Clima enviado: {w['temp']}°C ({w['condition']})"

                sync_log = SyncHistory(
                    status=status_code,
                    message=res.get("message", f"Sincronização automática agendada{weather_info}"),
                    details=str(res.get("data", {}))
                )
                session.add(sync_log)

                if status_code == "SUCCESS" and "data" in res:
                    d = res["data"]
                    act = ActivityLog(
                        device_mac=dev.mac_address,
                        steps=d.get("steps", 0),
                        distance_meters=d.get("distance_meters", 0),
                        calories=d.get("calories", 0),
                        heart_rate=d.get("heart_rate"),
                        battery_level=d.get("battery_level")
                    )
                    session.add(act)
                session.commit()

def start_scheduler():
    if not scheduler.running:
        # Checa a cada 1 minuto se há sincronização pendente
        scheduler.add_job(run_scheduled_sync, 'cron', second=0)
        scheduler.start()
        logger.info("APScheduler iniciado com sucesso.")
