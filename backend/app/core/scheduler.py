from datetime import datetime, timedelta
from typing import Optional, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

from app.core.logger import logger
from app.core.database import engine, DeviceConfig, IntegrationConfig, SyncSchedule, ActivityLog, SyncHistory
from app.core.cache import cache
from app.services.miband import miband_service
from app.services.weather import weather_service

scheduler = AsyncIOScheduler()

async def execute_sync_workflow(mac_address: str, auth_key: Optional[str] = None, auto_weather: bool = True, source: str = "SCHEDULED") -> dict:
    """
    Pipeline unificado de sincronização direta do Mi Band 6:
    1. Busca Clima Estendido (Redis / API Externa)
    2. Envia Clima para a pulseira
    3. Conecta via BLE e extrai métricas (Passos, BPM, Bateria, Calorias)
    4. Atualiza métricas e timestamp de última sincronização no Redis e SQLite
    """
    logger.info(f"[{source}] Iniciando workflow de sincronização para {mac_address}...")
    
    weather_info_str = ""
    extended_forecast = None
    
    # 1. Se auto_weather estiver ativado, obter Clima Estendido (com prioridade no Cache Redis)
    if auto_weather:
        try:
            with Session(engine) as session:
                integration = session.exec(select(IntegrationConfig)).first()
                prov = integration.weather_provider if integration else None
                tok = integration.weather_api_token if integration else None
                city = integration.weather_city if integration else None
                lat = integration.latitude if integration else None
                lon = integration.longitude if integration else None

            extended_forecast = weather_service.get_extended_forecast(
                latitude=lat,
                longitude=lon,
                provider=prov,
                api_token=tok,
                city=city
            )
            
            cur = extended_forecast.get("current", {})
            temp = cur.get("temp", 24)
            cond = cur.get("condition", "Ensolarado")
            
            # Enviar para a Mi Band
            await miband_service.send_weather_info(mac_address, temp, cond)
            weather_info_str = f" | Clima: {temp}°C ({cond})"
            logger.info(f"[{source}] Clima enviado com sucesso para {mac_address}")
        except Exception as e:
            logger.warning(f"[{source}] Falha ao processar clima para {mac_address}: {e}")

    # 2. Sincronizar Métricas BLE da Pulseira
    res = await miband_service.sync_band(mac_address, auth_key)
    status_code = res.get("status", "ERROR")
    now = datetime.utcnow()

    with Session(engine) as session:
        # Registrar no histórico
        sync_log = SyncHistory(
            device_mac=mac_address,
            timestamp=now,
            status=status_code,
            message=res.get("message", f"Sincronização {source.lower()}{weather_info_str}"),
            details=str(res.get("data", {}))
        )
        session.add(sync_log)

        if status_code == "SUCCESS":
            # Atualizar last_sync_time no banco SQLite
            dev = session.exec(select(DeviceConfig).where(DeviceConfig.mac_address == mac_address)).first()
            if dev:
                dev.last_sync_time = now
                dev.updated_at = now
                session.add(dev)

            # Persistir métricas de atividade
            d = res.get("data", {})
            act = ActivityLog(
                device_mac=mac_address,
                timestamp=now,
                steps=d.get("steps", 0),
                distance_meters=d.get("distance_meters", 0),
                calories=d.get("calories", 0),
                heart_rate=d.get("heart_rate"),
                battery_level=d.get("battery_level")
            )
            session.add(act)

            # Salvar no Redis (Memória RAM) para respostas imediatas sem I/O no disco
            cache.set(f"device:{mac_address}:last_sync", now.isoformat())
            cache.set(f"latest_metrics:{mac_address}", act.model_dump(mode="json"), ttl_seconds=86400)

        session.commit()

    return res

async def check_hourly_sync():
    """
    Rotina executada de hora em hora.
    Verifica a última sincronização de cada dispositivo ativo.
    Se o tempo decorrido >= sync_interval_hours, dispara o workflow.
    """
    logger.info("Executando rotina horária de verificação de sincronização...")
    now = datetime.utcnow()

    with Session(engine) as session:
        devices = session.exec(select(DeviceConfig).where(DeviceConfig.is_active == True)).all()
        for dev in devices:
            interval = dev.sync_interval_hours or 1
            last_sync = dev.last_sync_time

            # Verificar no Redis se não estiver no objeto
            if not last_sync:
                redis_last = cache.get(f"device:{dev.mac_address}:last_sync")
                if redis_last:
                    try:
                        last_sync = datetime.fromisoformat(redis_last)
                    except Exception:
                        pass

            should_sync = False
            if last_sync is None:
                should_sync = True
                logger.info(f"Dispositivo {dev.mac_address} nunca sincronizou. Disparando sincronização por intervalo.")
            else:
                elapsed_hours = (now - last_sync).total_seconds() / 3600.0
                if elapsed_hours >= (interval - 0.05):  # Margem de tolerância
                    should_sync = True
                    logger.info(f"Dispositivo {dev.mac_address}: decorridas {elapsed_hours:.1f}h (intervalo={interval}h). Disparando sincronização.")

            if should_sync:
                await execute_sync_workflow(
                    mac_address=dev.mac_address,
                    auth_key=dev.auth_key,
                    auto_weather=dev.auto_weather,
                    source="HOURLY_INTERVAL"
                )

async def run_specific_time_sync(mac_address: str, target_time: str):
    """Executa a sincronização programada em um horário exato fixo"""
    logger.info(f"Horário específico fixo ({target_time}) atingido para a pulseira {mac_address}!")
    with Session(engine) as session:
        dev = session.exec(select(DeviceConfig).where(DeviceConfig.mac_address == mac_address)).first()
        if not dev or not dev.is_active:
            logger.info(f"Dispositivo {mac_address} inativo ou removido. Ignorando agendamento fixo.")
            return
        
        await execute_sync_workflow(
            mac_address=dev.mac_address,
            auth_key=dev.auth_key,
            auto_weather=dev.auto_weather,
            source=f"EXACT_TIME_{target_time}"
        )

def reload_scheduler_jobs():
    """
    Recarrega e registra todos os Jobs do APScheduler com base no banco de dados e Redis.
    - 1 Job horário para conferência de intervalo.
    - N Jobs com CronTrigger para cada horário específico configurado na Grid/tabela.
    """
    logger.info("Recarregando agendamentos do APScheduler...")
    scheduler.remove_all_jobs()

    # 1. Job de intervalo a cada hora (no minuto 0)
    scheduler.add_job(
        check_hourly_sync,
        CronTrigger(minute=0),
        id="job_hourly_sync",
        name="Hourly Interval Sync Checker",
        replace_existing=True
    )

    # 2. Jobs de horários específicos
    with Session(engine) as session:
        # A) Lê registros da tabela sync_schedule
        schedules = session.exec(select(SyncSchedule).where(SyncSchedule.is_active == True)).all()
        for sched in schedules:
            try:
                parts = sched.scheduled_time.strip().split(":")
                hour = int(parts[0])
                minute = int(parts[1]) if len(parts) > 1 else 0
                job_id = f"job_fixed_{sched.device_mac}_{hour:02d}_{minute:02d}"
                
                scheduler.add_job(
                    run_specific_time_sync,
                    CronTrigger(hour=hour, minute=minute),
                    args=[sched.device_mac, f"{hour:02d}:{minute:02d}"],
                    id=job_id,
                    name=f"Fixed Time {hour:02d}:{minute:02d} for {sched.device_mac}",
                    replace_existing=True
                )
                logger.info(f"Agendado horário fixo: {hour:02d}:{minute:02d} para {sched.device_mac}")
            except Exception as e:
                logger.error(f"Erro ao agendar horário fixo {sched.scheduled_time}: {e}")

        # B) Também lê o campo texto sync_intervals dos dispositivos como fallback/compatibilidade
        devices = session.exec(select(DeviceConfig).where(DeviceConfig.is_active == True)).all()
        for dev in devices:
            if dev.sync_intervals:
                for t in [x.strip() for x in dev.sync_intervals.split(",") if x.strip()]:
                    try:
                        parts = t.split(":")
                        hour = int(parts[0])
                        minute = int(parts[1]) if len(parts) > 1 else 0
                        job_id = f"job_fixed_{dev.mac_address}_{hour:02d}_{minute:02d}"
                        
                        if not scheduler.get_job(job_id):
                            scheduler.add_job(
                                run_specific_time_sync,
                                CronTrigger(hour=hour, minute=minute),
                                args=[dev.mac_address, f"{hour:02d}:{minute:02d}"],
                                id=job_id,
                                name=f"Fixed Time {hour:02d}:{minute:02d} for {dev.mac_address}",
                                replace_existing=True
                            )
                            logger.info(f"Agendado horário de device_config: {hour:02d}:{minute:02d} para {dev.mac_address}")
                    except Exception as e:
                        logger.error(f"Erro ao agendar {t} para {dev.mac_address}: {e}")

def start_scheduler():
    """Inicia o APScheduler e registra os jobs"""
    if not scheduler.running:
        scheduler.start()
        logger.info("APScheduler inicializado.")
    reload_scheduler_jobs()
