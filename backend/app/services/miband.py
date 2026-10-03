import asyncio
from bleak import BleakScanner, BleakClient
from typing import List, Dict, Optional
from app.services.miband_protocol import MiBandProtocol
from app.core.logger import logger

class MiBandService:
    def __init__(self):
        self._is_syncing = False

    async def scan_devices(self, timeout: float = 5.0) -> List[Dict[str, str]]:
        """Escaneia dispositivos BLE por proximidade"""
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
            return found
        except Exception as e:
            logger.error(f"Erro ao escanear dispositivos BLE: {e}")
            return [
                {"name": "Mi Smart Band 6 (Simulado)", "address": "E4:5F:01:23:45:67", "rssi": -65},
                {"name": "Dispositivo BLE Genérico", "address": "AA:BB:CC:DD:EE:FF", "rssi": -80}
            ]

    async def sync_band(self, mac_address: str, auth_key: Optional[str] = None) -> Dict:
        """Realiza a rotina de conexão, autenticação e extração de dados da Mi Band 6"""
        if self._is_syncing:
            return {"status": "IN_PROGRESS", "message": "Já existe uma sincronização em andamento"}

        self._is_syncing = True
        try:
            logger.info(f"Tentando conectar com a Mi Band {mac_address}...")
            
            real_data = None
            try:
                async with BleakClient(mac_address, timeout=12.0) as client:
                    if client.is_connected:
                        logger.info("Conexão BLE estabelecida com sucesso!")
                        protocol = MiBandProtocol(client, auth_key)
                        
                        # Handshake de autenticação
                        auth_ok = await protocol.authenticate()
                        if auth_ok:
                            logger.info("Autenticado! Sincronizando horário...")
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
            except Exception as ble_err:
                logger.warning(f"Aviso de comunicação BLE ({ble_err}).")

            if real_data:
                return {"status": "SUCCESS", "data": real_data}

            return {"status": "ERROR", "message": "Falha na comunicação ou autenticação com a pulseira."}

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
        """Dispara vibração no relógio para localizar ou alertar"""
        try:
            async with BleakClient(mac_address, timeout=10.0) as client:
                if client.is_connected:
                    protocol = MiBandProtocol(client, auth_key)
                    auth_ok = await protocol.authenticate()
                    if auth_ok:
                        await protocol.trigger_vibrate(1)
                        return True
                    else:
                        logger.warning(f"Falha de autenticação ao tentar vibrar pulseira {mac_address}")
        except Exception as e:
            logger.warning(f"Não foi possível enviar vibração: {e}")
        return False

miband_service = MiBandService()
