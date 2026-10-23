import asyncio
import time
import datetime
from typing import Dict, Any, Optional, List
from bleak import BleakClient

from app.services.miband_protocol import MiBandProtocol
from app.services.miband import miband_service

class MiBandTestService:
    def __init__(self):
        pass

    def _create_log_collector(self, event_queue: Optional[asyncio.Queue] = None):
        logs: List[Dict[str, str]] = []
        def log_cb(level: str, msg: str):
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            entry = {
                "ts": ts,
                "level": level,
                "msg": msg
            }
            logs.append(entry)
            if event_queue is not None:
                event_queue.put_nowait({
                    "type": "log",
                    "level": level,
                    "msg": msg,
                    "ts": ts
                })
        return logs, log_cb

    async def _execute_with_client(
        self, 
        mac_address: str, 
        auth_key: str, 
        action_fn, 
        action_name: str = "Operação",
        event_queue: Optional[asyncio.Queue] = None
    ) -> Dict[str, Any]:
        """
        Executa uma ação BLE de teste isolada com proteção de concorrência, coleta de logs
        e emissão opcional de eventos de progresso via event_queue (SSE).
        Nenhum dado é gravado no banco de dados SQLite ou cache de métricas.
        """
        logs, log_cb = self._create_log_collector(event_queue)
        start_time = time.time()

        def emit_progress(step: str, message: str, percent: int, partial_data: Any = None):
            if event_queue is not None:
                event_queue.put_nowait({
                    "type": "progress",
                    "step": step,
                    "message": message,
                    "percent": percent,
                    "data": partial_data
                })

        def emit_step_done(step: str, message: str, percent: int, partial_data: Any = None):
            if event_queue is not None:
                event_queue.put_nowait({
                    "type": "step_done",
                    "step": step,
                    "message": message,
                    "percent": percent,
                    "data": partial_data
                })

        emit_progress("validating", f"Iniciando {action_name}...", 5)
        log_cb("INFO", f"Iniciando {action_name} para {mac_address}...")

        clean_key = auth_key.strip() if auth_key else ""
        if clean_key.startswith("0x") or clean_key.startswith("0X"):
            clean_key = clean_key[2:]

        if len(clean_key) != 32:
            log_cb("ERROR", f"Auth Key inválida ({len(clean_key)} caracteres). São necessários 32 hex.")
            res = {
                "success": False,
                "duration_ms": round((time.time() - start_time) * 1000),
                "data": None,
                "error": "Auth Key inválida",
                "logs": logs
            }
            if event_queue is not None:
                event_queue.put_nowait({"type": "complete", **res})
                event_queue.put_nowait(None)
            return res

        if miband_service._ble_lock.locked():
            log_cb("WARN", "Adaptador Bluetooth ocupado por outra operação ou sincronização agendada.")
            res = {
                "success": False,
                "duration_ms": round((time.time() - start_time) * 1000),
                "data": None,
                "error": "Bluetooth ocupado no momento. Aguarde alguns segundos.",
                "logs": logs
            }
            if event_queue is not None:
                event_queue.put_nowait({"type": "complete", **res})
                event_queue.put_nowait(None)
            return res

        emit_progress("lock_wait", "Aguardando canal Bluetooth...", 10)

        async with miband_service._ble_lock:
            try:
                emit_progress("connecting", f"Conectando ao dispositivo BLE {mac_address} (timeout 15s)...", 15)
                log_cb("INFO", f"Conectando ao dispositivo BLE {mac_address} (timeout 15s)...")
                
                async with BleakClient(mac_address, timeout=15.0) as client:
                    if not client.is_connected:
                        log_cb("ERROR", "Falha ao estabelecer conexão BLE com o dispositivo.")
                        res = {
                            "success": False,
                            "duration_ms": round((time.time() - start_time) * 1000),
                            "data": None,
                            "error": "Não foi possível conectar ao dispositivo BLE",
                            "logs": logs
                        }
                        if event_queue is not None:
                            event_queue.put_nowait({"type": "complete", **res})
                            event_queue.put_nowait(None)
                        return res

                    emit_progress("authenticating", "Conexão BLE estabelecida! Autenticando com Auth Key...", 30)
                    log_cb("INFO", "Conexão BLE estabelecida com sucesso!")
                    protocol = MiBandProtocol(client, clean_key)
                    protocol.trace_logger = log_cb

                    log_cb("INFO", "Iniciando autenticação criptográfica...")
                    auth_ok = await protocol.authenticate()
                    if not auth_ok:
                        log_cb("ERROR", "Autenticação rejeitada pela pulseira.")
                        res = {
                            "success": False,
                            "duration_ms": round((time.time() - start_time) * 1000),
                            "data": None,
                            "error": "Falha na autenticação BLE com a Auth Key fornecida",
                            "logs": logs
                        }
                        if event_queue is not None:
                            event_queue.put_nowait({"type": "complete", **res})
                            event_queue.put_nowait(None)
                        return res

                    emit_progress("executing", "Pulseira autenticada! Executando comando...", 40)
                    log_cb("INFO", "Pulseira autenticada e pronta para comandos!")

                    data = await action_fn(protocol, log_cb, emit_progress, emit_step_done)
                    duration_ms = round((time.time() - start_time) * 1000)
                    
                    emit_progress("done", f"{action_name} finalizada com sucesso!", 100, data)
                    log_cb("INFO", f"{action_name} finalizada com sucesso em {duration_ms}ms.")
                    
                    res = {
                        "success": True,
                        "duration_ms": duration_ms,
                        "data": data,
                        "error": None,
                        "logs": logs
                    }
                    if event_queue is not None:
                        event_queue.put_nowait({"type": "complete", **res})
                        event_queue.put_nowait(None)
                    return res

            except Exception as e:
                duration_ms = round((time.time() - start_time) * 1000)
                log_cb("ERROR", f"Exceção durante execução: {str(e)}")
                res = {
                    "success": False,
                    "duration_ms": duration_ms,
                    "data": None,
                    "error": str(e),
                    "logs": logs
                }
                if event_queue is not None:
                    event_queue.put_nowait({"type": "complete", **res})
                    event_queue.put_nowait(None)
                return res

    async def test_read_all(self, mac_address: str, auth_key: str, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        """Lê todas as métricas em uma única sessão BLE rápida, emitindo eventos parciais a cada etapa"""
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("activity", "Lendo atividade física (passos)...", 45)
            log_cb("INFO", "Coletando atividade física...")
            activity = await p.read_steps()
            emit_done("activity", "Passos lidos com sucesso", 55, activity)
            
            emit_prog("battery", "Lendo status da bateria...", 60)
            log_cb("INFO", "Coletando status da bateria...")
            battery = await p.read_battery_details()
            emit_done("battery", "Bateria lida com sucesso", 70, battery)
            
            emit_prog("device_info", "Lendo informações de hardware/firmware...", 75)
            log_cb("INFO", "Coletando informações de hardware/firmware...")
            device_info = await p.read_device_info()
            emit_done("device_info", "Dados do aparelho lidos", 82, device_info)
            
            emit_prog("time", "Lendo horário interno e desvio de relógio...", 85)
            log_cb("INFO", "Coletando horário interno e desvio de relógio...")
            time_data = await p.read_band_time()
            emit_done("time", "Horário verificado", 90, time_data)
            
            emit_prog("alarms", "Consultando alarmes configurados...", 93)
            log_cb("INFO", "Consultando alarmes configurados...")
            alarms = await p.request_alarms(timeout=5.0)
            emit_done("alarms", "Alarmes consultados", 98, alarms)

            return {
                "activity": activity,
                "battery": battery,
                "device_info": device_info,
                "time": time_data,
                "alarms": alarms
            }
        return await self._execute_with_client(mac_address, auth_key, _action, "Sincronização Completa de Teste", event_queue)

    async def test_read_activity(self, mac_address: str, auth_key: str, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("activity", "Lendo contadores de passos e calorias...", 60)
            data = await p.read_steps()
            emit_done("activity", "Passos lidos", 95, data)
            return data
        return await self._execute_with_client(mac_address, auth_key, _action, "Leitura de Atividade", event_queue)

    async def test_read_battery(self, mac_address: str, auth_key: str, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("battery", "Lendo nível e status de carga da bateria...", 60)
            data = await p.read_battery_details()
            emit_done("battery", "Bateria lida", 95, data)
            return data
        return await self._execute_with_client(mac_address, auth_key, _action, "Leitura de Bateria", event_queue)

    async def test_read_device_info(self, mac_address: str, auth_key: str, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("device_info", "Lendo versão de hardware, firmware e serial...", 60)
            data = await p.read_device_info()
            emit_done("device_info", "Dados do dispositivo lidos", 95, data)
            return data
        return await self._execute_with_client(mac_address, auth_key, _action, "Leitura de Informações do Dispositivo", event_queue)

    async def test_read_time(self, mac_address: str, auth_key: str, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("time", "Lendo horário da pulseira e calculando desvio...", 60)
            data = await p.read_band_time()
            emit_done("time", "Horário verificado", 95, data)
            return data
        return await self._execute_with_client(mac_address, auth_key, _action, "Leitura de Horário", event_queue)

    async def test_sync_time(self, mac_address: str, auth_key: str, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("time_sync", "Enviando comando de sincronização de relógio...", 55)
            ok = await p.sync_time()
            emit_prog("time_read", "Confirmando horário atualizado na pulseira...", 75)
            time_data = await p.read_band_time()
            res = {"synced": ok, "time": time_data}
            emit_done("time_sync", "Relógio sincronizado com sucesso", 95, res)
            return res
        return await self._execute_with_client(mac_address, auth_key, _action, "Sincronização de Horário", event_queue)

    async def test_read_alarms(self, mac_address: str, auth_key: str, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("alarms", "Requisitando slots de alarme configurados na pulseira...", 60)
            data = await p.request_alarms()
            emit_done("alarms", "Alarmes lidos", 95, data)
            return data
        return await self._execute_with_client(mac_address, auth_key, _action, "Consulta de Alarmes", event_queue)

    async def test_read_heart_rate(self, mac_address: str, auth_key: str, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("heart_rate", "Acionando sensor óptico PPG na pulseira (aguarde até 25s no pulso)...", 50)
            bpm = await p.measure_heart_rate(timeout=25.0)
            res = {"heart_rate": bpm}
            emit_done("heart_rate", f"Medição concluída: {bpm or '--'} BPM", 95, res)
            return res
        return await self._execute_with_client(mac_address, auth_key, _action, "Medição de Frequência Cardíaca", event_queue)

    async def test_send_weather(
        self, 
        mac_address: str, 
        auth_key: str, 
        current_weather: dict, 
        daily_forecast: list, 
        city: str,
        event_queue: Optional[asyncio.Queue] = None
    ) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("weather_send", f"Codificando e transmitindo 7 dias de clima para {city}...", 60)
            ok = await p.send_weather_chunked(current_weather, daily_forecast, city)
            res = {"sent": ok}
            emit_done("weather_send", "Previsão do tempo enviada à Mi Band", 95, res)
            return res
        return await self._execute_with_client(mac_address, auth_key, _action, "Envio de Previsão do Tempo", event_queue)

    async def test_send_notification(
        self, 
        mac_address: str, 
        auth_key: str, 
        category: int, 
        title: str, 
        text: str,
        event_queue: Optional[asyncio.Queue] = None
    ) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("notify", "Transmitindo pacote BLE New Alert para a tela da pulseira...", 60)
            ok = await p.send_notification(category, title, text)
            res = {"sent": ok}
            emit_done("notify", "Notificação enviada com sucesso", 95, res)
            return res
        return await self._execute_with_client(mac_address, auth_key, _action, "Envio de Notificação", event_queue)

    async def test_trigger_vibrate(
        self, 
        mac_address: str, 
        auth_key: str, 
        count: int = 2, 
        text: str = "Teste",
        event_queue: Optional[asyncio.Queue] = None
    ) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("vibrate", f"Disparando {count} pulso(s) vibratório(s) no motor haptic...", 60)
            ok = await p.trigger_vibrate(count, text)
            res = {"vibrated": ok}
            emit_done("vibrate", "Vibração acionada", 95, res)
            return res
        return await self._execute_with_client(mac_address, auth_key, _action, "Disparo de Vibração", event_queue)

    async def test_measure_spo2(self, mac_address: str, auth_key: str, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("spo2", "Acionando sensor óptico SpO2 (mantenha o braço imóvel por até 30s)...", 50)
            log_cb("INFO", "Disparando medição de oximetria (SpO2)...")
            spo2 = await p.measure_spo2(timeout=30.0)
            res = {"spo2": spo2}
            emit_done("spo2", f"Oximetria concluída: {spo2}%" if spo2 else "Medição de SpO2 finalizada sem leitura estável", 95, res)
            return res
        return await self._execute_with_client(mac_address, auth_key, _action, "Medição de Oxímetro (SpO2)", event_queue)

    async def test_measure_stress(self, mac_address: str, auth_key: str, event_queue: Optional[asyncio.Queue] = None) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("stress", "Coletando intervalo R-R (HRV) para cálculo do índice de estresse...", 50)
            log_cb("INFO", "Disparando medição de estresse...")
            stress = await p.measure_stress(timeout=25.0)
            res = {"stress": stress}
            emit_done("stress", f"Estresse calculado: {stress}/100" if stress is not None else "Leitura concluída sem dados estáveis", 95, res)
            return res
        return await self._execute_with_client(mac_address, auth_key, _action, "Medição de Estresse", event_queue)

    async def test_send_fitness_goals(
        self, 
        mac_address: str, 
        auth_key: str, 
        step_goal: int = 8000, 
        calorie_goal: int = 300,
        event_queue: Optional[asyncio.Queue] = None
    ) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("goals", f"Configurando metas: {step_goal} passos, {calorie_goal} kcal...", 60)
            log_cb("INFO", f"Enviando metas de atividade: passos={step_goal}, calorias={calorie_goal}...")
            ok = await p.set_fitness_goals(step_goal=step_goal, calorie_goal=calorie_goal)
            res = {"sent": ok, "step_goal": step_goal, "calorie_goal": calorie_goal}
            emit_done("goals", "Metas de passos e calorias atualizadas na pulseira", 95, res)
            return res
        return await self._execute_with_client(mac_address, auth_key, _action, "Configuração de Metas de Atividade", event_queue)

    async def test_send_pai(
        self, 
        mac_address: str, 
        auth_key: str, 
        total_pai: int = 100, 
        today_pai: int = 15,
        event_queue: Optional[asyncio.Queue] = None
    ) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb, emit_prog, emit_done):
            emit_prog("pai", f"Transmitindo escore PAI (Total: {total_pai}, Hoje: {today_pai})...", 60)
            log_cb("INFO", f"Enviando escore PAI: total={total_pai}, hoje={today_pai}...")
            ok = await p.send_pai_score(total_pai=total_pai, today_pai=today_pai)
            res = {"sent": ok, "total_pai": total_pai, "today_pai": today_pai}
            emit_done("pai", "Pontuação PAI enviada com sucesso à Mi Band", 95, res)
            return res
        return await self._execute_with_client(mac_address, auth_key, _action, "Sincronização de PAI", event_queue)

miband_test_service = MiBandTestService()
