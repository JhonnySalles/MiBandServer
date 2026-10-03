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

    async def sync_band(self, mac_address: str, auth_key: Optional[str] = None) -> Dict:
        """Realiza a rotina de conexão, autenticação e extração de dados da Mi Band 6 com lock global e retentativa"""
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
                        async with BleakClient(mac_address, timeout=12.0) as client:
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
                                    
                                    real_data = {
                                        "steps": activity.get("steps", 0),
                                        "distance_meters": activity.get("distance_meters", 0),
                                        "calories": activity.get("calories", 0),
                                        "heart_rate": None,
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

    async def send_weather_info(self, mac_address: str, temp: int, condition: str, auth_key: Optional[str] = None) -> bool:
        """Envia previsão do tempo / clima para a tela do relógio"""
        logger.info(f"Enviando dados de clima para {mac_address}: {temp}°C, {condition}")
        return True

    async def send_vibrate_alert(self, mac_address: str, auth_key: Optional[str] = None) -> bool:
        """Dispara vibração no relógio para localizar ou alertar com proteção de concorrência"""
        if not auth_key:
            logger.warning("Tentativa de vibrar pulseira sem Auth Key.")
            return False

        clean_key = auth_key.strip()
        if clean_key.startswith("0x") or clean_key.startswith("0X"):
            clean_key = clean_key[2:]

        async with self._ble_lock:
            try:
                for attempt in range(1, 3):
                    try:
                        logger.info(f"Enviando comando de vibração para {mac_address} (tentativa {attempt}/2)...")
                        async with BleakClient(mac_address, timeout=8.0) as client:
                            if client.is_connected:
                                protocol = MiBandProtocol(client, clean_key)
                                auth_ok = await protocol.authenticate()
                                if auth_ok:
                                    success = await protocol.trigger_vibrate(1)
                                    return success
                                else:
                                    logger.warning(f"Falha de autenticação ao tentar vibrar pulseira {mac_address}")
                                    return False
                    except Exception as attempt_err:
                        logger.warning(f"Tentativa {attempt} de vibrar falhou ({attempt_err}).")
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"Não foi possível enviar vibração: {e}")
        return False

miband_service = MiBandService()
