import asyncio
import struct
import datetime
from typing import Optional, Callable
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from bleak import BleakClient
from app.core.logger import logger

# UUIDs característicos do ecossistema Huami / Mi Band
UUID_SERVICE_AUTH = "00000fee1-0000-1000-8000-00805f9b34fb"
UUID_CHAR_AUTH = "00000009-0000-3512-2118-0009af100700"

# UUIDs de Informações Básicas, Tempo e Atividades
UUID_SERVICE_BASIC = "0000fee0-0000-1000-8000-00805f9b34fb"
UUID_CHAR_STEPS = "00000007-0000-3512-2118-0009af100700"
UUID_CHAR_BATTERY = "00000006-0000-3512-2118-0009af100700"
UUID_CHAR_CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"

# UUIDs de Frequência Cardíaca (Padrão BLE Heart Rate Service)
UUID_SERVICE_HEART_RATE = "0000180d-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HEART_RATE_MEASURE = "00002a37-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HEART_RATE_CONTROL = "00002a39-0000-1000-8000-00805f9b34fb"

# UUIDs de Notificações e Clima
UUID_CHAR_ALERT = "00002a06-0000-1000-8000-00805f9b34fb"

class MiBandProtocol:
    def __init__(self, client: BleakClient, auth_key_hex: Optional[str] = None):
        self.client = client
        self.auth_key = bytes.fromhex(auth_key_hex) if auth_key_hex and len(auth_key_hex) == 32 else None
        self._auth_future: Optional[asyncio.Future] = None

    async def authenticate(self) -> bool:
        """
        Executa o handshake de autenticação Huami (AES-128-ECB):
        1. Envia comando para solicitar número randômico (0x02, 0x00)
        2. Recebe desafio de 16 bytes da pulseira
        3. Encripta o desafio com a Auth Key via AES-128-ECB
        4. Devolve o desafio encriptado com prefixo (0x03, 0x00, bytes...)
        """
        if not self.auth_key:
            logger.info("Nenhuma Auth Key fornecida. Prosseguindo sem autenticação Huami customizada.")
            return True

        try:
            loop = asyncio.get_running_loop()
            self._auth_future = loop.create_future()

            await self.client.start_notify(UUID_CHAR_AUTH, self._auth_notification_handler)
            
            # Solicitar desafio
            logger.info("Solicitando desafio de autenticação à Mi Band...")
            await self.client.write_gatt_char(UUID_CHAR_AUTH, bytearray([0x02, 0x00]), response=True)

            # Aguardar resposta (timeout de 8 segundos)
            auth_success = await asyncio.wait_for(self._auth_future, timeout=8.0)
            await self.client.stop_notify(UUID_CHAR_AUTH)
            return auth_success
        except Exception as e:
            logger.warning(f"Falha durante processo de autenticação: {e}")
            return False

    def _auth_notification_handler(self, sender: int, data: bytearray):
        """Manipulador de pacotes de autenticação recebidos"""
        if data[:3] == bytearray([0x10, 0x01, 0x01]):
            logger.info("Chave enviada aceita.")
        elif data[:3] == bytearray([0x10, 0x02, 0x01]):
            # Recebeu o desafio (data[3:] = 16 bytes)
            random_challenge = bytes(data[3:19])
            logger.info(f"Desafio de autenticação recebido ({len(random_challenge)} bytes). Encriptando...")
            
            # Criptografia AES-ECB
            cipher = Cipher(algorithms.AES(self.auth_key), modes.ECB())
            encryptor = cipher.encryptor()
            encrypted = encryptor.update(random_challenge) + encryptor.finalize()

            # Enviar resposta encriptada
            response_pkt = bytearray([0x03, 0x00]) + encrypted
            asyncio.create_task(self.client.write_gatt_char(UUID_CHAR_AUTH, response_pkt, response=True))

        elif data[:3] == bytearray([0x10, 0x03, 0x01]):
            logger.info("Autenticação com a Mi Band 6 concluída com SUCESSO!")
            if self._auth_future and not self._auth_future.done():
                self._auth_future.set_result(True)
        else:
            logger.warning(f"Resposta de autenticação inesperada: {data.hex()}")
            if self._auth_future and not self._auth_future.done():
                self._auth_future.set_result(False)

    async def read_battery(self) -> Optional[int]:
        """Lê o nível de carga da bateria (0 a 100%)"""
        try:
            val = await self.client.read_gatt_char(UUID_CHAR_BATTERY)
            if val and len(val) >= 2:
                return int(val[1])
        except Exception as e:
            logger.warning(f"Não foi possível ler bateria via GATT: {e}")
        return None

    async def read_steps(self) -> dict:
        """Lê passos, distância (metros) e calorias"""
        try:
            val = await self.client.read_gatt_char(UUID_CHAR_STEPS)
            if val and len(val) >= 13:
                steps = int.from_bytes(val[1:5], byteorder="little")
                meters = int.from_bytes(val[5:9], byteorder="little")
                calories = int.from_bytes(val[9:13], byteorder="little")
                return {"steps": steps, "distance_meters": meters, "calories": calories}
        except Exception as e:
            logger.warning(f"Não foi possível ler passos via GATT: {e}")
        return {"steps": 0, "distance_meters": 0, "calories": 0}

    async def trigger_vibrate(self, count: int = 1):
        """Envia comando de vibração/alerta para a pulseira"""
        try:
            await self.client.write_gatt_char(UUID_CHAR_ALERT, bytearray([0x01]), response=False)
            logger.info(f"Vibração disparada na Mi Band ({count}x).")
        except Exception as e:
            logger.warning(f"Não foi possível enviar alerta de vibração: {e}")

    async def sync_time(self, custom_time: Optional[datetime.datetime] = None) -> bool:
        """Envia data/hora atualizada para sincronizar o relógio da Mi Band"""
        try:
            now = custom_time or datetime.datetime.now()
            # Formato padrão 10 bytes BLE Current Time (0x2A2B):
            # year (2 bytes little endian), month (1 byte), day (1 byte), hour (1 byte), minute (1 byte), second (1 byte), day_of_week (1 byte), fractions256 (1 byte), adjust_reason (1 byte)
            payload = struct.pack(
                '<HBBBBBBBB',
                now.year,
                now.month,
                now.day,
                now.hour,
                now.minute,
                now.second,
                now.isoweekday(),
                0,
                0
            )
            await self.client.write_gatt_char(UUID_CHAR_CURRENT_TIME, payload, response=True)
            logger.info(f"Horário sincronizado com sucesso na Mi Band: {now.strftime('%Y-%m-%d %H:%M:%S')}")
            return True
        except Exception as e:
            logger.warning(f"Não foi possível sincronizar horário via GATT: {e}")
            return False

