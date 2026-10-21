import asyncio
from bleak import BleakScanner, BleakClient
from typing import List, Dict, Optional
from app.services.miband_protocol import MiBandProtocol
from app.core.logger import logger

class MiBandService:
    def __init__(self):
        self._is_syncing = False
        self._is_scanning = False
        self._last_scan_cache = []
        self._ble_lock = asyncio.Lock()

    async def scan_devices(self, timeout: float = 3.0) -> List[Dict[str, str]]:
        """Escaneia dispositivos BLE por proximidade com proteção de concorrência"""
        # Se uma conexão ou outro scan estiver em andamento, retorna cache imediatamente
        if self._ble_lock.locked() or self._is_scanning or self._is_syncing:
            return self._last_scan_cache

        async with self._ble_lock:
            self._is_scanning = True
            try:
                logger.info("Iniciando escaneamento BLE...")
                devices = await BleakScanner.discover(timeout=timeout)
                found = []
                for d in devices:
                    name = d.name or "Dispositivo Desconhecido"
                    found.append({
                        "name": name,
                        "address": d.address,
                        "rssi": getattr(d, "rssi", 0)
                    })
                # Ordenar por intensidade do sinal RSSI (mais próximos primeiro)
                found.sort(key=lambda x: x.get("rssi", -100), reverse=True)
                self._last_scan_cache = found
                return found
            except Exception as e:
                logger.error(f"Erro ao escanear dispositivos BLE: {e}")
                return self._last_scan_cache or [
                    {"name": "Mi Smart Band 6 (Simulado)", "address": "E4:5F:01:23:45:67", "rssi": -65},
                    {"name": "Dispositivo BLE Genérico", "address": "AA:BB:CC:DD:EE:FF", "rssi": -80}
                ]
            finally:
                self._is_scanning = False

    async def sync_band(self, mac_address: str, auth_key: Optional[str] = None, weather_data: Optional[Dict] = None) -> Dict:
        """Realiza a rotina de conexão, autenticação, leitura de métricas (BPM, passos, bateria) e envio de clima na mesma sessão BLE"""
        if not auth_key:
            return {
                "status": "ERROR",
                "message": "A Auth Key é obrigatória para comunicar com a Mi Band 6. Cadastre a chave de 32 caracteres do dispositivo."
            }

        clean_key = auth_key.strip()
        if clean_key.startswith("0x") or clean_key.startswith("0X"):
            clean_key = clean_key[2:]
        if len(clean_key) != 32:
            return {
                "status": "ERROR",
                "message": f"Auth Key inválida ({len(clean_key)} caracteres). Deve conter exatamente 32 caracteres hexadecimais."
            }

        if self._is_syncing:
            return {"status": "IN_PROGRESS", "message": "Já existe uma sincronização em andamento"}

        self._is_syncing = True
        try:
            async with self._ble_lock:
                logger.info(f"Conectando com a Mi Band {mac_address} via BLE...")
                
                # Tenta até 2 vezes conectar caso o adaptador Bluetooth esteja ocupado
                last_err = None
                for attempt in range(1, 3):
                    try:
                        logger.info(f"Tentativa {attempt}/2 de conexão BLE com {mac_address}...")
                        async with BleakClient(mac_address, timeout=15.0) as client:
                            if client.is_connected:
                                logger.info("Conexão BLE estabelecida com sucesso!")
                                protocol = MiBandProtocol(client, clean_key)
                                
                                # Handshake de autenticação
                                auth_ok = await protocol.authenticate()
                                if auth_ok:
                                    logger.info("Autenticado com sucesso! Sincronizando horário...")
                                    await protocol.sync_time()

                                    logger.info("Lendo métricas da pulseira...")
                                    battery = await protocol.read_battery()
                                    activity = await protocol.read_steps()

                                    # Medição de Frequência Cardíaca (BPM)
                                    logger.info("Iniciando leitura de frequência cardíaca (BPM)...")
                                    hr_bpm = await protocol.measure_heart_rate(timeout=15.0)
                                    if hr_bpm:
                                        logger.info(f"Frequência cardíaca aferida: {hr_bpm} BPM")
                                    else:
                                        logger.info("Não foi possível obter BPM no momento (pulseira pode estar fora do braço)")

                                    # Envio de Clima se fornecido
                                    if weather_data and isinstance(weather_data, dict):
                                        logger.info("Transmitindo clima estendido para o display da pulseira...")
                                        cur = weather_data.get("current", {})
                                        forecast = weather_data.get("daily_forecast", [])
                                        city = weather_data.get("city", "São Paulo")
                                        await protocol.send_weather_full(cur, forecast, city)

                                    real_data = {
                                        "steps": activity.get("steps", 0),
                                        "distance_meters": activity.get("distance_meters", 0),
                                        "calories": activity.get("calories", 0),
                                        "heart_rate": hr_bpm,
                                        "battery_level": battery
                                    }
                                    return {"status": "SUCCESS", "data": real_data}
                                else:
                                    return {
                                        "status": "ERROR",
                                        "message": "Falha de autenticação com a pulseira. Verifique se a Auth Key está correta."
                                    }
                    except Exception as ble_err:
                        last_err = ble_err
                        logger.warning(f"Tentativa {attempt} falhou ({ble_err}). Aguardando 500ms...")
                        await asyncio.sleep(0.5)

                return {
                    "status": "ERROR", 
                    "message": f"Não foi possível conectar à pulseira: {str(last_err or 'Dispositivo ocupado ou fora de alcance')}"
                }

        except Exception as e:
            logger.error(f"Erro na sincronização: {e}")
            return {"status": "ERROR", "message": str(e)}
        finally:
            self._is_syncing = False

    async def send_weather_info(
        self,
        mac_address: str,
        temp: Optional[int] = None,
        condition: Optional[str] = None,
        auth_key: Optional[str] = None,
        weather_data: Optional[Dict] = None
    ) -> bool:
        """Envia previsão do tempo / clima completa para a tela do relógio via conexão BLE dedicada"""
        clean_key = auth_key.strip() if auth_key else ""
        if clean_key.startswith("0x") or clean_key.startswith("0X"):
            clean_key = clean_key[2:]

        async with self._ble_lock:
            try:
                for attempt in range(1, 3):
                    try:
                        logger.info(f"Conectando com {mac_address} para envio de clima (tentativa {attempt}/2)...")
                        async with BleakClient(mac_address, timeout=15.0) as client:
                            if client.is_connected:
                                protocol = MiBandProtocol(client, clean_key)
                                if clean_key:
                                    auth_ok = await protocol.authenticate()
                                    if not auth_ok:
                                        logger.warning("Falha ao autenticar pulseira para envio de clima.")
                                        return False

                                cur = weather_data.get("current", {}) if weather_data else {}
                                if not cur and temp is not None:
                                    cur = {"temp": temp, "condition": condition or "Ensolarado", "code": 0}
                                forecast = weather_data.get("daily_forecast", []) if weather_data else []
                                city = weather_data.get("city") if weather_data else None

                                return await protocol.send_weather_full(cur, forecast, city)
                    except Exception as ble_err:
                        logger.warning(f"Tentativa {attempt} de envio de clima falhou ({ble_err}).")
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.error(f"Erro ao enviar dados de clima para {mac_address}: {e}")
        return False

    async def send_vibrate_alert(self, mac_address: str, auth_key: Optional[str] = None) -> bool:
        """Dispara vibração no relógio para localizar ou alertar com proteção de concorrência"""
        clean_key = auth_key.strip() if auth_key else ""
        if clean_key.startswith("0x") or clean_key.startswith("0X"):
            clean_key = clean_key[2:]

        async with self._ble_lock:
            try:
                for attempt in range(1, 3):
                    try:
                        logger.info(f"Enviando comando de vibração para {mac_address} (tentativa {attempt}/2)...")
                        async with BleakClient(mac_address, timeout=15.0) as client:
                            if client.is_connected:
                                protocol = MiBandProtocol(client, clean_key)
                                
                                # 1. Se possuir Auth Key, autentica primeiro (imprescindível para o motor físico aceitar comandos)
                                if clean_key:
                                    logger.info("Iniciando autenticação Huami antes do disparo de vibração...")
                                    auth_ok = await protocol.authenticate()
                                    if auth_ok:
                                        logger.info("Pulseira autenticada! Disparando motor de vibração...")
                                        return await protocol.trigger_vibrate(2, "Localizar MiBand")
                                    else:
                                        logger.warning(f"Falha de autenticação ao tentar vibrar pulseira {mac_address}")

                                # 2. Disparo direto como fallback se não houver chave ou auth falhar
                                logger.info("Tentando acionar alerta de vibração direto em {mac_address}...")
                                return await protocol.trigger_vibrate(1)
                    except Exception as attempt_err:
                        logger.warning(f"Tentativa {attempt} de vibrar falhou ({attempt_err}).")
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Não foi possível enviar vibração: {e}")
        return False

miband_service = MiBandService()
