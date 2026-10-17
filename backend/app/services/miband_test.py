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

    def _create_log_collector(self):
        logs: List[Dict[str, str]] = []
        def log_cb(level: str, msg: str):
            logs.append({
                "ts": datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "level": level,
                "msg": msg
            })
        return logs, log_cb

    async def _execute_with_client(self, mac_address: str, auth_key: str, action_fn, action_name: str = "Operação") -> Dict[str, Any]:
        """
        Executa uma ação BLE de teste isolada com proteção de concorrência e coleta de logs.
        Nenhum dado é gravado no banco de dados SQLite ou cache de métricas.
        """
        logs, log_cb = self._create_log_collector()
        start_time = time.time()
        log_cb("INFO", f"Iniciando {action_name} para {mac_address}...")

        clean_key = auth_key.strip() if auth_key else ""
        if clean_key.startswith("0x") or clean_key.startswith("0X"):
            clean_key = clean_key[2:]

        if len(clean_key) != 32:
            log_cb("ERROR", f"Auth Key inválida ({len(clean_key)} caracteres). São necessários 32 hex.")
            return {
                "success": False,
                "duration_ms": round((time.time() - start_time) * 1000),
                "data": None,
                "error": "Auth Key inválida",
                "logs": logs
            }

        if miband_service._ble_lock.locked():
            log_cb("WARN", "Adaptador Bluetooth ocupado por outra operação ou sincronização agendada.")
            return {
                "success": False,
                "duration_ms": round((time.time() - start_time) * 1000),
                "data": None,
                "error": "Bluetooth ocupado no momento. Aguarde alguns segundos.",
                "logs": logs
            }

        async with miband_service._ble_lock:
            try:
                log_cb("INFO", f"Conectando ao dispositivo BLE {mac_address} (timeout 15s)...")
                async with BleakClient(mac_address, timeout=15.0) as client:
                    if not client.is_connected:
                        log_cb("ERROR", "Falha ao estabelecer conexão BLE com o dispositivo.")
                        return {
                            "success": False,
                            "duration_ms": round((time.time() - start_time) * 1000),
                            "data": None,
                            "error": "Não foi possível conectar ao dispositivo BLE",
                            "logs": logs
                        }

                    log_cb("INFO", "Conexão BLE estabelecida com sucesso!")
                    protocol = MiBandProtocol(client, clean_key)
                    protocol.trace_logger = log_cb

                    log_cb("INFO", "Iniciando autenticação criptográfica...")
                    auth_ok = await protocol.authenticate()
                    if not auth_ok:
                        log_cb("ERROR", "Autenticação rejeitada pela pulseira.")
                        return {
                            "success": False,
                            "duration_ms": round((time.time() - start_time) * 1000),
                            "data": None,
                            "error": "Falha na autenticação BLE com a Auth Key fornecida",
                            "logs": logs
                        }

                    log_cb("INFO", "Pulseira autenticada e pronta para comandos!")
                    data = await action_fn(protocol, log_cb)
                    duration_ms = round((time.time() - start_time) * 1000)
                    log_cb("INFO", f"{action_name} finalizada com sucesso em {duration_ms}ms.")
                    return {
                        "success": True,
                        "duration_ms": duration_ms,
                        "data": data,
                        "error": None,
                        "logs": logs
                    }
            except Exception as e:
                duration_ms = round((time.time() - start_time) * 1000)
                log_cb("ERROR", f"Exceção durante execução: {str(e)}")
                return {
                    "success": False,
                    "duration_ms": duration_ms,
                    "data": None,
                    "error": str(e),
                    "logs": logs
                }

    async def test_read_all(self, mac_address: str, auth_key: str) -> Dict[str, Any]:
        """Lê todas as métricas em uma única sessão BLE rápida"""
        async def _action(p: MiBandProtocol, log_cb):
            log_cb("INFO", "Coletando atividade física...")
            activity = await p.read_steps()
            
            log_cb("INFO", "Coletando status da bateria...")
            battery = await p.read_battery_details()
            
            log_cb("INFO", "Coletando informações de hardware/firmware...")
            device_info = await p.read_device_info()
            
            log_cb("INFO", "Coletando horário interno e desvio de relógio...")
            time_data = await p.read_band_time()
            
            log_cb("INFO", "Consultando alarmes configurados...")
            alarms = await p.request_alarms(timeout=5.0)

            return {
                "activity": activity,
                "battery": battery,
                "device_info": device_info,
                "time": time_data,
                "alarms": alarms
            }
        return await self._execute_with_client(mac_address, auth_key, _action, "Sincronização Completa de Teste")

    async def test_read_activity(self, mac_address: str, auth_key: str) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb):
            return await p.read_steps()
        return await self._execute_with_client(mac_address, auth_key, _action, "Leitura de Atividade")

    async def test_read_battery(self, mac_address: str, auth_key: str) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb):
            return await p.read_battery_details()
        return await self._execute_with_client(mac_address, auth_key, _action, "Leitura de Bateria")

    async def test_read_device_info(self, mac_address: str, auth_key: str) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb):
            return await p.read_device_info()
        return await self._execute_with_client(mac_address, auth_key, _action, "Leitura de Informações do Dispositivo")

    async def test_read_time(self, mac_address: str, auth_key: str) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb):
            return await p.read_band_time()
        return await self._execute_with_client(mac_address, auth_key, _action, "Leitura de Horário")

    async def test_sync_time(self, mac_address: str, auth_key: str) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb):
            ok = await p.sync_time()
            time_data = await p.read_band_time()
            return {"synced": ok, "time": time_data}
        return await self._execute_with_client(mac_address, auth_key, _action, "Sincronização de Horário")

    async def test_read_alarms(self, mac_address: str, auth_key: str) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb):
            return await p.request_alarms()
        return await self._execute_with_client(mac_address, auth_key, _action, "Consulta de Alarmes")

    async def test_read_heart_rate(self, mac_address: str, auth_key: str) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb):
            bpm = await p.measure_heart_rate(timeout=25.0)
            return {"heart_rate": bpm}
        return await self._execute_with_client(mac_address, auth_key, _action, "Medição de Frequência Cardíaca")

    async def test_send_weather(self, mac_address: str, auth_key: str, current_weather: dict, daily_forecast: list, city: str) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb):
            ok = await p.send_weather_chunked(current_weather, daily_forecast, city)
            return {"sent": ok}
        return await self._execute_with_client(mac_address, auth_key, _action, "Envio de Previsão do Tempo")

    async def test_send_notification(self, mac_address: str, auth_key: str, category: int, title: str, text: str) -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb):
            ok = await p.send_notification(category, title, text)
            return {"sent": ok}
        return await self._execute_with_client(mac_address, auth_key, _action, "Envio de Notificação")

    async def test_trigger_vibrate(self, mac_address: str, auth_key: str, count: int = 2, text: str = "Teste") -> Dict[str, Any]:
        async def _action(p: MiBandProtocol, log_cb):
            ok = await p.trigger_vibrate(count, text)
            return {"vibrated": ok}
        return await self._execute_with_client(mac_address, auth_key, _action, "Disparo de Vibração")

miband_test_service = MiBandTestService()
