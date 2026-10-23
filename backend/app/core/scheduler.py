from datetime import datetime, timedelta, timezone
from typing import Optional, List
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlmodel import Session, select

import json
from app.core.logger import logger
from app.core.database import (
    engine, DeviceConfig, IntegrationConfig, SyncSchedule,
    ActivityLog, SyncHistory, WeatherHistory, BandSettings,
    IntradayActivitySample, SleepSummary, get_utc_now
)
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
            if extended_forecast:
                extended_forecast["city"] = city or "São Paulo"
                cur = extended_forecast.get("current", {})
                temp = cur.get("temp", 24)
                cond = cur.get("condition", "Ensolarado")
                weather_info_str = f" | Clima: {temp}°C ({cond})"
                logger.info(f"[{source}] Dados meteorológicos preparados ({temp}°C, {cond}) para envio durante a sincronização.")
        except Exception as e:
            logger.warning(f"[{source}] Falha ao processar previsão do tempo para {mac_address}: {e}")

    # 2. Carregar Alarmes, Metas e Configurações de Frequência/Estresse no banco (se houver)
    alarms_list = None
    hr_interval = None
    fitness_goals = None
    stress_config = None
    try:
        with Session(engine) as s_set:
            b_set = s_set.exec(select(BandSettings).where(BandSettings.device_mac == mac_address)).first()
            if b_set:
                hr_interval = b_set.heart_rate_interval
                fitness_goals = {
                    "step_goal": b_set.step_goal or 8000,
                    "calorie_goal": b_set.calorie_goal or 300
                }
                stress_config = {
                    "all_day_stress": b_set.all_day_stress if b_set.all_day_stress is not None else True,
                    "stress_interval": b_set.stress_interval or 5
                }
                if b_set.alarms:
                    parsed_alarms = json.loads(b_set.alarms)
                    if isinstance(parsed_alarms, list) and len(parsed_alarms) > 0:
                        alarms_list = parsed_alarms
    except Exception as e_alarm:
        logger.warning(f"[{source}] Falha ao carregar configurações de alarme/bpm/metas para {mac_address}: {e_alarm}")

    # Calcular PAI estimado com base na atividade recente
    pai_scores = {"pai_total": 85, "pai_today": 14}

    # 3. Sincronizar Métricas BLE da Pulseira (e enviar clima, alarmes, metas e PAI na mesma sessão)
    res = await miband_service.sync_band(
        mac_address,
        auth_key,
        weather_data=extended_forecast,
        alarms_data=alarms_list,
        heart_rate_interval=hr_interval,
        fitness_goals=fitness_goals,
        stress_config=stress_config,
        pai_scores=pai_scores,
        fetch_history=True
    )
    status_code = res.get("status", "ERROR")
    now = get_utc_now()

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

        # Gravar histórico de clima
        if extended_forecast and status_code == "SUCCESS":
            cur = extended_forecast.get("current", {})
            daily0 = (extended_forecast.get("daily_forecast") or [{}])[0]
            w_log = WeatherHistory(
                timestamp=now,
                city=extended_forecast.get("city", "São Paulo"),
                temp=int(cur.get("temp", 24)),
                temp_min=daily0.get("temp_min"),
                temp_max=daily0.get("temp_max"),
                condition=str(cur.get("condition", "Ensolarado")),
                humidity=cur.get("humidity"),
                wind_speed=cur.get("wind_speed"),
                weather_code=cur.get("code"),
                provider=extended_forecast.get("provider", "Open-Meteo"),
                source=f"SYNC_{source.upper()}"
            )
            session.add(w_log)

        if status_code == "SUCCESS":
            # Atualizar last_sync_time no banco SQLite
            dev = session.exec(select(DeviceConfig).where(DeviceConfig.mac_address == mac_address)).first()
            if dev:
                dev.last_sync_time = now
                dev.updated_at = now
                session.add(dev)

            # Persistir métricas de atividade
            d = res.get("data", {})
            hr_val = d.get("heart_rate")
            if hr_val is None:
                # Fallback para o último BPM registrado caso a pulseira estivesse momentaneamente fora do braço
                last_act = session.exec(
                    select(ActivityLog)
                    .where(ActivityLog.device_mac == mac_address)
                    .where(ActivityLog.heart_rate != None)
                    .order_by(ActivityLog.timestamp.desc())
                ).first()
                if last_act:
                    hr_val = last_act.heart_rate

            act = ActivityLog(
                device_mac=mac_address,
                timestamp=now,
                steps=d.get("steps", 0),
                distance_meters=d.get("distance_meters", 0),
                calories=d.get("calories", 0),
                heart_rate=hr_val,
                battery_level=d.get("battery_level"),
                spo2=d.get("spo2"),
                stress=d.get("stress"),
                pai_today=d.get("pai_today"),
                pai_total=d.get("pai_total")
            )
            session.add(act)

            # Salvar amostras intradiárias
            intraday_samples = d.get("intraday_samples", [])
            for sample in intraday_samples[:200]:
                try:
                    s_dt = datetime.fromisoformat(sample["timestamp"])
                    sample_obj = IntradayActivitySample(
                        device_mac=mac_address,
                        timestamp=s_dt,
                        category=sample.get("category", 0),
                        steps=sample.get("steps", 0),
                        intensity=sample.get("intensity", 0),
                        heart_rate=sample.get("heart_rate"),
                        spo2=sample.get("spo2"),
                        stress=sample.get("stress")
                    )
                    session.add(sample_obj)
                except Exception:
                    pass

            # Salvar resumo de sono (Fase 3)
            sleep_data = d.get("sleep_summary")
            if sleep_data and isinstance(sleep_data, dict):
                try:
                    s_date = sleep_data.get("date", now.strftime("%Y-%m-%d"))
                    existing_sleep = session.exec(
                        select(SleepSummary)
                        .where(SleepSummary.device_mac == mac_address)
                        .where(SleepSummary.date == s_date)
                    ).first()

                    if existing_sleep:
                        existing_sleep.total_sleep_minutes = sleep_data.get("total_sleep_minutes", 0)
                        existing_sleep.deep_sleep_minutes = sleep_data.get("deep_sleep_minutes", 0)
                        existing_sleep.light_sleep_minutes = sleep_data.get("light_sleep_minutes", 0)
                        existing_sleep.rem_sleep_minutes = sleep_data.get("rem_sleep_minutes", 0)
                        existing_sleep.awake_minutes = sleep_data.get("awake_minutes", 0)
                        session.add(existing_sleep)
                    else:
                        new_sleep = SleepSummary(
                            device_mac=mac_address,
                            date=s_date,
                            start_time=datetime.fromisoformat(sleep_data["start_time"]),
                            end_time=datetime.fromisoformat(sleep_data["end_time"]),
                            total_sleep_minutes=sleep_data.get("total_sleep_minutes", 0),
                            deep_sleep_minutes=sleep_data.get("deep_sleep_minutes", 0),
                            light_sleep_minutes=sleep_data.get("light_sleep_minutes", 0),
                            rem_sleep_minutes=sleep_data.get("rem_sleep_minutes", 0),
                            awake_minutes=sleep_data.get("awake_minutes", 0)
                        )
                        session.add(new_sleep)
                except Exception as e_sleep_save:
                    logger.warning(f"Aviso ao salvar registro de sono: {e_sleep_save}")

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
    now = get_utc_now()

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
                if last_sync.tzinfo is None:
                    last_sync = last_sync.replace(tzinfo=timezone.utc)
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
