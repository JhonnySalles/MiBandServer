import asyncio
import struct
import datetime
import os
import json
import subprocess
import shutil
import zlib
from typing import Optional, Callable
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from bleak import BleakClient
from app.core.logger import logger

# UUIDs do Protocolo Moderno Huami 2021 (Mi Band 6 / 7 / Amazfit modernas)
UUID_CHAR_CHUNKED_WRITE = "00000016-0000-3512-2118-0009af100700"
UUID_CHAR_CHUNKED_READ = "00000017-0000-3512-2118-0009af100700"
UUID_CHAR_CHUNKED_OLD = "00000020-0000-3512-2118-0009af100700"
CHUNKED2021_ENDPOINT_AUTH = 130
CHUNKED2021_ENDPOINT_COMPAT = 0x0090  # 144 - Clima, Configurações e Alarmes

# UUIDs de Informações do Dispositivo (Device Information Service - DIS 0x180A)
UUID_SERVICE_DIS = "0000180a-0000-1000-8000-00805f9b34fb"
UUID_CHAR_MODEL = "00002a24-0000-1000-8000-00805f9b34fb"
UUID_CHAR_SERIAL = "00002a25-0000-1000-8000-00805f9b34fb"
UUID_CHAR_FW_REVISION = "00002a26-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HW_REVISION = "00002a27-0000-1000-8000-00805f9b34fb"
UUID_CHAR_SW_REVISION = "00002a28-0000-1000-8000-00805f9b34fb"

# UUIDs de Autenticação Legada (Mi Band 2 / 3 / 4 / 5 inicial)
UUID_SERVICE_AUTH = "0000fee1-0000-1000-8000-00805f9b34fb"
UUID_CHAR_AUTH = "00000009-0000-3512-2118-0009af100700"

# UUIDs de Informações Básicas, Tempo e Atividades
UUID_SERVICE_BASIC = "0000fee0-0000-1000-8000-00805f9b34fb"
UUID_CHAR_STEPS = "00000007-0000-3512-2118-0009af100700"
UUID_CHAR_BATTERY_LEGACY = "00000006-0000-3512-2118-0009af100700"
UUID_CHAR_BATTERY_STANDARD = "00002a19-0000-1000-8000-00805f9b34fb"
UUID_CHAR_CURRENT_TIME = "00002a2b-0000-1000-8000-00805f9b34fb"
UUID_CHAR_ACTIVITY_DATA = "00000004-0000-3512-2118-0009af100700"
UUID_CHAR_ACTIVITY_CONTROL = "00000005-0000-3512-2118-0009af100700"

# UUIDs de Frequência Cardíaca (Padrão BLE Heart Rate Service)
UUID_SERVICE_HEART_RATE = "0000180d-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HEART_RATE_MEASURE = "00002a37-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HEART_RATE_CONTROL = "00002a39-0000-1000-8000-00805f9b34fb"

# UUIDs de Alerta e Vibração Física
UUID_CHAR_ALERT = "00002a06-0000-1000-8000-00805f9b34fb"
UUID_CHAR_NEW_ALERT = "00002a46-0000-1000-8000-00805f9b34fb"
UUID_CHAR_ALERT_CONTROL = "00002a44-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HUAMI_ALERT = "00000003-0000-3512-2118-0009af100700"

def safe_utf8_truncate(text: str, max_bytes: int) -> bytes:
    """Trunca uma string UTF-8 garantindo que nenhum caractere multi-byte seja quebrado no meio"""
    if not text:
        return b""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return encoded
    truncated = encoded[:max_bytes]
    decoded = truncated.decode("utf-8", errors="ignore")
    return decoded.encode("utf-8")

def get_node_executable() -> str:
    which_node = shutil.which("node")
    if which_node:
        return which_node
    candidates = [
        r"D:\Arquivos de programas\nodejs\node.exe",
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return "node"

HELPER_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "ecdh_helper.js"))

class MiBandProtocol:
    def __init__(self, client: BleakClient, auth_key_hex: Optional[str] = None):
        self.client = client
        clean_key = auth_key_hex.strip() if auth_key_hex else ""
        if clean_key.startswith("0x") or clean_key.startswith("0X"):
            clean_key = clean_key[2:]
        self.auth_key = bytes.fromhex(clean_key) if len(clean_key) == 32 else None
        self._auth_future: Optional[asyncio.Future] = None
        self._is_authenticated = False
        self.session_key: Optional[bytes] = None
        self.encrypted_seq: int = 0
        self.write_handle: int = 0
        self.trace_logger: Optional[Callable[[str, str], None]] = None

    def _trace(self, level: str, msg: str):
        if self.trace_logger:
            try:
                self.trace_logger(level, msg)
            except Exception:
                pass
        if level == "ERROR":
            logger.error(msg)
        elif level == "WARN":
            logger.warning(msg)
        else:
            logger.info(msg)

    async def authenticate(self) -> bool:
        """
        Executa a autenticação automática da Mi Band:
        1. Detecta se a pulseira possui características Huami 2021 (Chunked ECDH B-163 - Mi Band 6/7)
        2. Se sim, autentica via ECDH B-163.
        3. Caso contrário, executa o fluxo legado AES-ECB.
        """
        if not self.auth_key:
            logger.error("Auth Key não fornecida ou inválida (necessário 32 caracteres hexadecimais).")
            return False

        # Verificar características disponíveis no dispositivo
        has_chunked_write = any(
            c.uuid.lower() == UUID_CHAR_CHUNKED_WRITE.lower() 
            for s in self.client.services for c in s.characteristics
        )
        has_chunked_read = any(
            c.uuid.lower() == UUID_CHAR_CHUNKED_READ.lower() 
            for s in self.client.services for c in s.characteristics
        )

        if has_chunked_write and has_chunked_read:
            logger.info("Mi Smart Band 6 detectada com protocolo Huami 2021. Iniciando handshake ECDH B-163...")
            return await self._authenticate_ecdh_2021()
        else:
            logger.info("Executando autenticação legado Huami (AES-ECB)...")
            return await self._authenticate_legacy_huami()

    # -------------------------------------------------------------
    # Protocolo Moderno: Huami 2021 Chunked ECDH B-163 (Mi Band 6)
    # -------------------------------------------------------------
    async def _authenticate_ecdh_2021(self) -> bool:
        node_bin = get_node_executable()
        if not os.path.exists(HELPER_PATH):
            logger.error(f"Helper ECDH não encontrado em: {HELPER_PATH}")
            return False

        try:
            # 1. Gerar chaves ECDH B-163 locais
            res = subprocess.check_output([node_bin, HELPER_PATH, "generate"], encoding="utf-8")
            key_data = json.loads(res.strip())
            priv_key = bytes.fromhex(key_data["privateKey"])
            pub_key = bytes.fromhex(key_data["publicKey"])
        except Exception as e:
            logger.error(f"Erro ao gerar chaves criptográficas ECDH locais: {e}")
            return False

        reassemble_buf = bytearray()
        expected_bytes = 0
        last_seq = -1
        loop = asyncio.get_running_loop()
        auth_success_event = asyncio.Event()
        handle_counter = [0]

        def on_chunked_notification(sender, data: bytearray):
            nonlocal expected_bytes, last_seq
            if len(data) <= 1 or data[0] != 3:
                return

            seq = data[4]
            # Resposta ao desafio (etapa 1 da pulseira: 4, 1)
            if (
                seq == 0 and len(data) >= 14 
                and data[9] == CHUNKED2021_ENDPOINT_AUTH and data[10] == 0 
                and data[11] == 16 and data[12] == 4 and data[13] == 1
            ):
                reassemble_buf.clear()
                expected_bytes = data[5] - 3
                last_seq = 0
                header_size = 14
                reassemble_buf.extend(data[header_size:])
                logger.info(f"Desafio inicial recebido da pulseira (esperando {expected_bytes} bytes de chave)...")

            elif seq > 0 and seq == last_seq + 1:
                last_seq = seq
                header_size = 5
                reassemble_buf.extend(data[header_size:])

            # Sucesso da autenticação confirmado pela pulseira (5, 1)
            elif (
                len(data) >= 14 
                and data[9] == CHUNKED2021_ENDPOINT_AUTH and data[10] == 0 
                and data[11] == 16 and data[12] == 5 and data[13] == 1
            ):
                self._trace("INFO", "Mi Smart Band 6 autenticada com SUCESSO via ECDH B-163!")
                if len(data) >= 18:
                    self.encrypted_seq = int.from_bytes(data[14:18], byteorder="little")
                    self._trace("INFO", f"Sequência criptográfica inicial: {self.encrypted_seq}")
                auth_success_event.set()
                return

            # Processar assim que todos os 64 bytes chegarem
            if expected_bytes > 0 and len(reassemble_buf) >= expected_bytes:
                remote_random = bytes(reassemble_buf[:16])
                remote_public = bytes(reassemble_buf[16:64])

                try:
                    # Calcular segredo compartilhado B-163 via wasm helper
                    res = subprocess.check_output(
                        [node_bin, HELPER_PATH, "secret", priv_key.hex(), remote_public.hex()],
                        encoding="utf-8"
                    )
                    shared_secret = bytes.fromhex(json.loads(res.strip())["sharedSecret"])
                except Exception as e:
                    self._trace("ERROR", f"Erro ao calcular segredo ECDH compartilhado: {e}")
                    return

                # Derivar chave de sessão AES e sequência criptográfica inicial (InitOperation2021)
                session_key = bytearray(16)
                for i in range(16):
                    session_key[i] = shared_secret[i + 8] ^ self.auth_key[i]
                self.session_key = bytes(session_key)
                self.encrypted_seq = int.from_bytes(shared_secret[:4], byteorder="little")
                self._trace("INFO", f"Sequência criptográfica inicial ECDH: {self.encrypted_seq}")

                # Criptografar nonce com AES-CBC (IV nulo)
                cipher1 = Cipher(algorithms.AES(self.auth_key), modes.CBC(bytes(16)))
                enc1 = cipher1.encryptor()
                out1 = enc1.update(remote_random) + enc1.finalize()

                cipher2 = Cipher(algorithms.AES(bytes(session_key)), modes.CBC(bytes(16)))
                enc2 = cipher2.encryptor()
                out2 = enc2.update(remote_random) + enc2.finalize()

                cmd = bytearray([0x05]) + out1 + out2
                handle_counter[0] += 1
                self._trace("INFO", "Enviando segunda etapa de autenticação criptografada...")
                asyncio.create_task(
                    self._write_chunked(UUID_CHAR_CHUNKED_WRITE, CHUNKED2021_ENDPOINT_AUTH, handle_counter[0], cmd)
                )
                expected_bytes = 0

        try:
            await self.client.start_notify(UUID_CHAR_CHUNKED_READ, on_chunked_notification)

            # Enviar primeiro comando: [4, 2, 0, 2] + pub_key
            init_cmd = bytearray([4, 2, 0, 2]) + pub_key
            logger.info("Enviando chave pública efêmera para a pulseira...")
            await self._write_chunked(UUID_CHAR_CHUNKED_WRITE, CHUNKED2021_ENDPOINT_AUTH, handle_counter[0], init_cmd)

            # Aguardar resposta com timeout de 12 segundos
            await asyncio.wait_for(auth_success_event.wait(), timeout=12.0)
            self._is_authenticated = True
            self.write_handle = handle_counter[0]
            await self.client.stop_notify(UUID_CHAR_CHUNKED_READ)
            return True

        except asyncio.TimeoutError:
            logger.warning("Tempo esgotado aguardando autenticação ECDH B-163.")
        except Exception as e:
            logger.warning(f"Falha durante autenticação ECDH 2021: {e}")
        finally:
            try:
                await self.client.stop_notify(UUID_CHAR_CHUNKED_READ)
            except Exception:
                pass

        return False

    async def _write_chunked(self, char_uuid: str, msg_type: int, handle: int, data: bytes):
        """Fraciona mensagens em pacotes MTU-compliant para o canal 0x0016"""
        remaining = len(data)
        count = 0
        header_size = 11
        mtu = 23

        while remaining > 0:
            max_chunk = mtu - 3 - header_size
            copy_bytes = min(remaining, max_chunk)
            chunk = bytearray(copy_bytes + header_size)
            flags = 0

            if count == 0:
                flags |= 1
                chunk[5] = len(data) & 0xFF
                chunk[6] = (len(data) >> 8) & 0xFF
                chunk[7] = (len(data) >> 16) & 0xFF
                chunk[8] = (len(data) >> 24) & 0xFF
                chunk[9] = msg_type & 0xFF
                chunk[10] = (msg_type >> 8) & 0xFF

            if remaining <= max_chunk:
                flags |= 6

            chunk[0] = 3
            chunk[1] = flags
            chunk[2] = 0
            chunk[3] = handle & 0xFF
            chunk[4] = count & 0xFF

            start_idx = len(data) - remaining
            chunk[header_size : header_size + copy_bytes] = data[start_idx : start_idx + copy_bytes]

            await self.client.write_gatt_char(char_uuid, chunk, response=False)
            await asyncio.sleep(0.035)

            remaining -= copy_bytes
            header_size = 5
            count += 1

    # -------------------------------------------------------------
    # Protocolo Legado Huami (Mi Band 2 / 3 / 4 / 5 inicial)
    # -------------------------------------------------------------
    async def _authenticate_legacy_huami(self) -> bool:
        try:
            loop = asyncio.get_running_loop()
            self._auth_future = loop.create_future()

            await self.client.start_notify(UUID_CHAR_AUTH, self._legacy_auth_handler)
            await self.client.write_gatt_char(UUID_CHAR_AUTH, bytearray([0x02, 0x08]), response=False)

            auth_success = await asyncio.wait_for(self._auth_future, timeout=12.0)
            self._is_authenticated = auth_success
            await self.client.stop_notify(UUID_CHAR_AUTH)
            return auth_success
        except Exception as e:
            logger.warning(f"Falha na autenticação legado: {e}")
            try:
                await self.client.stop_notify(UUID_CHAR_AUTH)
            except Exception:
                pass
            return False

    def _legacy_auth_handler(self, sender: int, data: bytearray):
        if data[:3] == bytearray([0x10, 0x02, 0x01]):
            random_challenge = bytes(data[3:19])
            cipher = Cipher(algorithms.AES(self.auth_key), modes.ECB())
            enc = cipher.encryptor()
            encrypted = enc.update(random_challenge) + enc.finalize()
            response_pkt = bytearray([0x03, 0x08]) + encrypted
            asyncio.create_task(self.client.write_gatt_char(UUID_CHAR_AUTH, response_pkt, response=False))

        elif data[:3] == bytearray([0x10, 0x03, 0x01]):
            logger.info("Autenticação legada Huami concluída com SUCESSO!")
            if self._auth_future and not self._auth_future.done():
                self._auth_future.set_result(True)

        elif data[:3] in (bytearray([0x10, 0x03, 0x07]), bytearray([0x10, 0x02, 0x07])):
            pair_pkt = bytearray([0x01, 0x08]) + self.auth_key
            asyncio.create_task(self.client.write_gatt_char(UUID_CHAR_AUTH, pair_pkt, response=False))

        elif data[:3] == bytearray([0x10, 0x01, 0x01]):
            asyncio.create_task(self.client.write_gatt_char(UUID_CHAR_AUTH, bytearray([0x02, 0x08]), response=False))

        elif data[:3] in (bytearray([0x10, 0x01, 0x81]), bytearray([0x10, 0x02, 0x81]), bytearray([0x10, 0x03, 0x81])):
            if self._auth_future and not self._auth_future.done():
                self._auth_future.set_result(False)

    # -------------------------------------------------------------
    # Operações do Dispositivo
    # -------------------------------------------------------------
    async def read_battery(self) -> Optional[int]:
        """Lê o nível de carga da bateria (0 a 100%)"""
        # Tentar primeiro o serviço padrão BLE de bateria (0x2A19)
        try:
            val = await self.client.read_gatt_char(UUID_CHAR_BATTERY_STANDARD)
            if val and len(val) >= 1:
                return int(val[0])
        except Exception:
            pass

        # Fallback para o caractere legado Huami (0x0006)
        try:
            val = await self.client.read_gatt_char(UUID_CHAR_BATTERY_LEGACY)
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

    async def trigger_vibrate(self, count: int = 1, text: str = "MiBand Server") -> bool:
        """Dispara vibração física comprovada na Mi Smart Band 6 com tela acesa e motor haptico"""
        # 1. Habilitar notificações de novos alertas no Control Point (0x2A44)
        try:
            await self.client.write_gatt_char(UUID_CHAR_ALERT_CONTROL, bytearray([0x00, 0xFF]), response=True)
        except Exception:
            pass

        vibrated = False
        msg_bytes = text.encode("utf-8", errors="ignore")[:18]

        for i in range(max(1, count)):
            # 2. Método Oficial MiBand 6 / Gadgetbridge (CallSpec Incoming)
            # Envia chamada recebida no chunked endpoint 0, que acende a tela e vibra com prioridade máxima
            try:
                call_buf = bytearray([3, 0, 0, 0, 0, 0]) + msg_bytes + bytearray([0, 0, 0, 2])
                await self._write_old_chunked(0, bytes(call_buf))
                vibrated = True
                self._trace("INFO", f"Vibração disparada via CallSpec Incoming ({i + 1}/{count})")
            except Exception as e_call:
                self._trace("WARN", f"Aviso ao enviar CallSpec: {e_call}")

            # 3. New Alert (0x2A46) Categoria 3 (Chamada)
            try:
                alert_payload = bytearray([0x03, 0x01]) + msg_bytes
                await self.client.write_gatt_char(UUID_CHAR_NEW_ALERT, alert_payload, response=True)
                vibrated = True
            except Exception as e1:
                self._trace("WARN", f"Falha ao enviar New Alert: {e1}")

            # 4. Immediate Alert GATT padrão (0x2A06) e Huami Alert (0x0003)
            try:
                await self.client.write_gatt_char(UUID_CHAR_ALERT, bytearray([0x02]), response=False)
                await self.client.write_gatt_char(UUID_CHAR_HUAMI_ALERT, bytearray([0x02]), response=False)
                vibrated = True
            except Exception:
                pass

            # Deixar vibrar por 1.8 segundos
            await asyncio.sleep(1.8)

            # 5. Cancelar chamada se foi a última iteração para a tela voltar ao normal
            try:
                await self._write_old_chunked(0, bytes([3, 3, 0, 0, 0, 0]))
            except Exception:
                pass

            if i < count - 1:
                await asyncio.sleep(0.5)

        return vibrated

    async def stop_vibrate(self) -> bool:
        """Interrompe imediatamente qualquer padrão de vibração/chamada ativo na Mi Smart Band 6"""
        stopped = False
        try:
            # 1. Enviar cancelamento de CallSpec (endpoint 0)
            await self._write_old_chunked(0, bytes([3, 3, 0, 0, 0, 0]))
            stopped = True
        except Exception:
            pass

        try:
            # 2. Desligar Immediate Alert (0x2A06)
            await self.client.write_gatt_char(UUID_CHAR_ALERT, bytearray([0x00]), response=False)
            stopped = True
        except Exception:
            pass

        try:
            # 3. Desligar Huami Alert (0x0003)
            await self.client.write_gatt_char(UUID_CHAR_HUAMI_ALERT, bytearray([0x00]), response=False)
            stopped = True
        except Exception:
            pass

        self._trace("INFO", "Comando de parada de vibração (Stop Find) transmitido com sucesso.")
        return stopped

    async def sync_time(self, custom_time: Optional[datetime.datetime] = None) -> bool:
        """Envia data/hora atualizada para sincronizar o relógio da Mi Band"""
        try:
            now = custom_time or datetime.datetime.now()
            year = now.year
            month = now.month
            day = now.day
            hour = now.hour
            minute = now.minute
            second = now.second
            day_of_week = now.isoweekday()

            tz_offset_sec = now.astimezone().utcoffset().total_seconds() if now.astimezone().utcoffset() else -10800
            tz_offset_quarters = int(tz_offset_sec / 900)

            payload = struct.pack(
                "<HBBBBBBBBb",
                year, month, day, hour, minute, second, day_of_week, 0, 0, tz_offset_quarters
            )
            await self.client.write_gatt_char(UUID_CHAR_CURRENT_TIME, payload, response=True)
            self._trace("INFO", f"Relógio da Mi Band sincronizado com sucesso: {now.isoformat()}")
            return True
        except Exception as e:
            self._trace("WARN", f"Falha ao sincronizar horário na Mi Band: {e}")
            return False

    # -------------------------------------------------------------
    # Métodos Estendidos de Teste e Diagnóstico (Aba Teste)
    # -------------------------------------------------------------
    async def _write_chunked_2021(self, type_endpoint: int, data: bytes, encrypt: bool = False) -> bool:
        """Codifica e envia pacotes no padrão Huami 2021 (Huami2021ChunkedEncoder)"""
        self.write_handle = (self.write_handle + 1) & 0xFF
        length = len(data)

        if encrypt:
            if not self.session_key:
                self._trace("ERROR", "Impossível criptografar pacote: chave de sessão (session_key) não definida.")
                return False

            message_key = bytes([self.session_key[i] ^ self.write_handle for i in range(16)])
            encrypted_length = length + 8
            overflow = encrypted_length % 16
            if overflow > 0:
                encrypted_length += (16 - overflow)

            encryptable_payload = bytearray(encrypted_length)
            encryptable_payload[:length] = data

            # sequence number (4 bytes LE)
            encryptable_payload[length : length + 4] = struct.pack("<I", self.encrypted_seq & 0xFFFFFFFF)
            self.encrypted_seq += 1

            # CRC32 (4 bytes LE)
            crc = zlib.crc32(encryptable_payload[: length + 4]) & 0xFFFFFFFF
            encryptable_payload[length + 4 : length + 8] = struct.pack("<I", crc)

            # Criptografia AES-ECB
            cipher = Cipher(algorithms.AES(message_key), modes.ECB())
            enc = cipher.encryptor()
            data_to_send = enc.update(bytes(encryptable_payload)) + enc.finalize()
            remaining = encrypted_length
        else:
            data_to_send = data
            remaining = length

        count = 0
        header_size = 11  # extended_flags = True
        mtu = 23

        while remaining > 0:
            max_chunk = mtu - 3 - header_size
            copy_bytes = min(remaining, max_chunk)
            chunk = bytearray(copy_bytes + header_size)

            flags = 0x08 if encrypt else 0x00
            if count == 0:
                flags |= 0x01  # first chunk
                chunk[5] = length & 0xFF
                chunk[6] = (length >> 8) & 0xFF
                chunk[7] = (length >> 16) & 0xFF
                chunk[8] = (length >> 24) & 0xFF
                chunk[9] = type_endpoint & 0xFF
                chunk[10] = (type_endpoint >> 8) & 0xFF

            if remaining <= max_chunk:
                flags |= 0x02  # last chunk
                flags |= 0x04  # needs ack

            chunk[0] = 0x03
            chunk[1] = flags
            chunk[2] = 0
            chunk[3] = self.write_handle & 0xFF
            chunk[4] = count & 0xFF

            start_idx = len(data_to_send) - remaining
            chunk[header_size : header_size + copy_bytes] = data_to_send[start_idx : start_idx + copy_bytes]

            self._trace("TX", f"Chunked2021 write (len={len(chunk)} flags=0x{flags:02x}): {chunk[:12].hex()}...")
            await self.client.write_gatt_char(UUID_CHAR_CHUNKED_WRITE, chunk, response=False)
            await asyncio.sleep(0.04)

            remaining -= copy_bytes
            header_size = 5
            count += 1

        return True

    async def read_device_info(self) -> dict:
        """Lê informações de hardware, firmware e serial do Device Information Service (0x180A)"""
        info = {
            "model": "Mi Smart Band 6",
            "firmware_version": "Desconhecido",
            "hardware_version": "Desconhecido",
            "software_version": "Desconhecido",
            "serial_number": "Desconhecido"
        }
        for char_uuid, key in [
            (UUID_CHAR_MODEL, "model"),
            (UUID_CHAR_FW_REVISION, "firmware_version"),
            (UUID_CHAR_HW_REVISION, "hardware_version"),
            (UUID_CHAR_SW_REVISION, "software_version"),
            (UUID_CHAR_SERIAL, "serial_number"),
        ]:
            try:
                val = await self.client.read_gatt_char(char_uuid)
                if val:
                    info[key] = val.decode("utf-8", errors="ignore").strip()
            except Exception:
                pass
        self._trace("INFO", f"Informações do dispositivo obtidas: {info}")
        return info

    async def read_battery_details(self) -> dict:
        """Lê nível de bateria e informações estendidas de status e carregamento"""
        level = await self.read_battery()
        status_str = "Descarregando / Em uso"
        is_charging = False
        last_charge_str = None

        try:
            val = await self.client.read_gatt_char(UUID_CHAR_BATTERY_LEGACY)
            if val and len(val) >= 3:
                status_code = val[2]
                if status_code == 2:
                    status_str = "Carregando"
                    is_charging = True
                elif status_code == 3:
                    status_str = "Carga Completa (100%)"
                elif status_code == 1:
                    status_str = "Descarregando / Em uso"

                if len(val) >= 9:
                    try:
                        yr = 2000 + val[3]
                        mo = val[4]
                        dy = val[5]
                        hr = val[6]
                        mi = val[7]
                        sc = val[8]
                        last_charge_str = f"{dy:02d}/{mo:02d}/{yr} {hr:02d}:{mi:02d}:{sc:02d}"
                    except Exception:
                        pass
        except Exception:
            pass

        data = {
            "level": level,
            "status": status_str,
            "is_charging": is_charging,
            "last_charge": last_charge_str
        }
        self._trace("INFO", f"Bateria: {level}% | Status: {status_str} | Última carga: {last_charge_str or 'N/A'}")
        return data

    async def read_band_time(self) -> dict:
        """Lê o horário interno gravado na Mi Band e calcula o desvio em relação ao servidor"""
        try:
            val = await self.client.read_gatt_char(UUID_CHAR_CURRENT_TIME)
            if val and len(val) >= 7:
                year, month, day, hour, minute, second = struct.unpack("<HBBBBB", val[:7])
                band_time = datetime.datetime(year, month, day, hour, minute, second)
                server_time = datetime.datetime.now()
                drift_sec = round((band_time - server_time).total_seconds(), 2)

                res = {
                    "band_time": band_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "server_time": server_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "drift_seconds": drift_sec,
                    "synced": abs(drift_sec) < 3.0
                }
                self._trace("INFO", f"Horário da pulseira: {res['band_time']} | Servidor: {res['server_time']} | Desvio: {drift_sec}s")
                return res
        except Exception as e:
            self._trace("ERROR", f"Falha ao ler horário da pulseira: {e}")
        return {
            "band_time": "Erro ao ler",
            "server_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "drift_seconds": 0,
            "synced": False
        }

    async def measure_heart_rate(self, timeout: float = 7.0) -> Optional[int]:
        """Aciona o sensor óptico PPG da Mi Band 6 e aguarda a leitura de BPM"""
        hr_value = None
        hr_event = asyncio.Event()

        def on_hr_notify(sender, data: bytearray):
            nonlocal hr_value
            if not data or len(data) < 2:
                return
            is_16bit = (data[0] & 0x01) == 1
            bpm = int.from_bytes(data[1:3], "little") if is_16bit and len(data) >= 3 else int(data[1])
            self._trace("RX", f"Leitura Heart Rate recebida: {bpm} BPM (raw={data.hex()})")
            if bpm > 0:
                hr_value = bpm
                hr_event.set()

        try:
            self._trace("INFO", "Iniciando subscrição em 0x2A37 (Heart Rate Measure)...")
            await self.client.start_notify(UUID_CHAR_HEART_RATE_MEASURE, on_hr_notify)

            # Comandos no Control Point (0x2A39)
            # 1. Configurar monitoramento periódico na pulseira a cada 5 minutos [0x14, 0x05]
            try:
                await self.client.write_gatt_char(UUID_CHAR_HEART_RATE_CONTROL, bytearray([0x14, 0x05]), response=True)
            except Exception:
                pass

            # 2. Parar medição contínua anterior
            try:
                await self.client.write_gatt_char(UUID_CHAR_HEART_RATE_CONTROL, bytearray([0x15, 0x01, 0x00]), response=True)
            except Exception:
                pass
            # 3. Parar medição manual anterior
            try:
                await self.client.write_gatt_char(UUID_CHAR_HEART_RATE_CONTROL, bytearray([0x15, 0x02, 0x00]), response=True)
            except Exception:
                pass
            # 4. Iniciar medição manual imediata
            self._trace("INFO", "Sensor de batimentos acionado. Mantenha a pulseira no pulso...")
            await self.client.write_gatt_char(UUID_CHAR_HEART_RATE_CONTROL, bytearray([0x15, 0x02, 0x01]), response=True)

            await asyncio.wait_for(hr_event.wait(), timeout=timeout)
            return hr_value
        except asyncio.TimeoutError:
            self._trace("WARN", f"Tempo limite de {timeout}s esgotado aguardando leitura de frequência cardíaca.")
            return None
        except Exception as e:
            self._trace("ERROR", f"Erro durante medição de frequência cardíaca: {e}")
            return None
        finally:
            try:
                await self.client.write_gatt_char(UUID_CHAR_HEART_RATE_CONTROL, bytearray([0x15, 0x02, 0x00]), response=True)
            except Exception:
                pass
            try:
                await self.client.stop_notify(UUID_CHAR_HEART_RATE_MEASURE)
            except Exception:
                pass

    @staticmethod
    def _repetition_mask_to_days(mask: int) -> list:
        """Converte a máscara de repetição Huami/MiBand em lista de dias [0..6] (0=Dom, 1=Seg..6=Sáb)"""
        if mask in (0, 0x80):
            return []
        days = []
        if mask & 0x01: days.append(1)  # Seg
        if mask & 0x02: days.append(2)  # Ter
        if mask & 0x04: days.append(3)  # Qua
        if mask & 0x08: days.append(4)  # Qui
        if mask & 0x10: days.append(5)  # Sex
        if mask & 0x20: days.append(6)  # Sáb
        if mask & 0x40: days.append(0)  # Dom
        days.sort()
        return days

    @staticmethod
    def _days_to_repetition_mask(days: list) -> int:
        """Converte lista de dias [0=Dom, 1=Seg, 2=Ter, 3=Qua, 4=Qui, 5=Sex, 6=Sáb] na máscara de repetição Huami"""
        if not days or len(days) == 0:
            return 128  # 0x80 = Alarme único (uma vez)
        if len(days) == 7:
            return 127  # 0x7F = Todos os dias
        mask = 0
        for d in days:
            if d == 1: mask |= 0x01
            elif d == 2: mask |= 0x02
            elif d == 3: mask |= 0x04
            elif d == 4: mask |= 0x08
            elif d == 5: mask |= 0x10
            elif d == 6: mask |= 0x20
            elif d == 0: mask |= 0x40
        return mask

    def _parse_alarm_payload(self, payload: bytes) -> list:
        """Extrai a lista de alarmes a partir de buffers retornados pela Mi Smart Band 6"""
        alarms = []
        if not payload or len(payload) < 4:
            return alarms

        # No protocolo Huami 2021 (endpoint 0x0090), a resposta vem precedida de 0x01
        data = payload
        if data[0] == 0x01 and len(data) > 4:
            data = data[1:]

        offset_start = 0

        # Caso 1: Pacote com cabeçalho de remontagem Huami (0x80, 0x01)
        # Ex: [0x80, 0x01, status, flags, reassemblyType(0x01), 0, 0, 0, count(0x01), <registros 4 bytes>]
        idx_80 = data.find(b"\x80\x01")
        if idx_80 != -1 and idx_80 + 8 < len(data):
            cand = idx_80 + 8
            if cand < len(data) and data[cand] in (0x01, 0x02, 0x03, 0x0A):
                cand += 1
            if len(data) - cand >= 4:
                offset_start = cand

        # Caso 2: Resposta direta de status Huami (0x10, 0x0D, 0x01)
        elif len(data) >= 9 and data[0] == 0x10 and data[1] == 0x0D and data[2] == 0x01:
            nr_alarms = data[8] if len(data) > 8 else 0
            for i in range(min(nr_alarms, 10)):
                off = 9 + i
                if off >= len(data):
                    break
                alarm_raw = data[off]
                idx = alarm_raw & 0x0F
                enabled = bool(alarm_raw & 0x10)
                alarms.append({
                    "id": idx + 1,
                    "index": idx,
                    "hours": 0,
                    "minutes": 0,
                    "time": "00:00",
                    "enabled": enabled,
                    "snooze": True,
                    "days": [1, 2, 3, 4, 5],
                    "repetition": 128
                })
            return alarms

        # Caso 3: Primeiro byte é prefixo de contagem ou versão e resto é múltiplo de 4
        elif (len(data) - 1) % 4 == 0 and data[0] in (0x01, 0x02):
            offset_start = 1

        # Caso 4: Buffer exato de registros de 4 bytes
        elif len(data) % 4 == 0:
            offset_start = 0

        # Caso 5: Fallback de varredura por integridade de registros válidos
        else:
            best_offset = -1
            best_valid = 0
            for off in range(min(16, len(data) - 4)):
                rem = len(data) - off
                if rem < 4:
                    break
                nr = rem // 4
                valid = 0
                for k in range(nr):
                    p = off + k * 4
                    raw = data[p]
                    hr = data[p + 1]
                    mi = data[p + 2]
                    if (raw & 0x0F) < 10 and hr < 24 and mi < 60:
                        valid += 1
                if valid > best_valid:
                    best_valid = valid
                    best_offset = off
            offset_start = best_offset if best_offset != -1 else 0

        self._trace("INFO", f"Parsing de alarmes com offset={offset_start} (payload total={len(data)} bytes)")
        nr = (len(data) - offset_start) // 4

        for i in range(min(nr, 10)):
            off = offset_start + i * 4
            if off + 3 >= len(data):
                break
            alarm_raw = data[off]
            idx = alarm_raw & 0x0F
            if idx >= 10:
                continue

            enabled = bool(alarm_raw & 0x80)
            snooze = not bool(alarm_raw & 0x40)
            hr = data[off + 1]
            mi = data[off + 2]
            rep = data[off + 3]

            # Validação: hora 0..23 e minuto 0..59 (preserva horários 00:00 e alarmes inativos)
            if hr < 24 and mi < 60:
                alarms.append({
                    "id": idx + 1,
                    "index": idx,
                    "hours": hr,
                    "minutes": mi,
                    "time": f"{hr:02d}:{mi:02d}",
                    "enabled": enabled,
                    "snooze": snooze,
                    "days": self._repetition_mask_to_days(rep),
                    "repetition": rep
                })
        return alarms

    async def request_alarms(self, timeout: float = 7.0) -> list:
        """Consulta alarmes configurados na Mi Band 6 via canal Huami 2021 (0x0017) e Característica 3 (0x0003)"""
        alarms_dict = {}
        alarm_event = asyncio.Event()

        # Buffer de remontagem chunked 2021
        chunk_buf = bytearray()
        expected_len = 0
        chunk_type = 0
        is_encrypted = False

        def on_chunked_rx(sender, data: bytearray):
            nonlocal expected_len, chunk_type, is_encrypted
            if not data or len(data) < 4:
                return
            if data[0] == 0x03:
                flags = data[1]
                is_encrypted = bool(flags & 0x08)
                first_chunk = bool(flags & 0x01)
                last_chunk = bool(flags & 0x02)
                needs_ack = bool(flags & 0x04)
                handle = data[3]
                count = data[4]

                if needs_ack:
                    ack = bytearray([0x04, 0x00, handle, 0x01, count])
                    try:
                        asyncio.create_task(self.client.write_gatt_char(UUID_CHAR_CHUNKED_READ, ack, response=False))
                    except Exception:
                        pass

                if first_chunk:
                    expected_len = data[5] | (data[6] << 8) | (data[7] << 16) | (data[8] << 24)
                    chunk_type = data[9] | (data[10] << 8)
                    chunk_buf.clear()
                    chunk_buf.extend(data[11:])
                else:
                    chunk_buf.extend(data[5:])

                if last_chunk:
                    raw_bytes = bytes(chunk_buf)
                    if is_encrypted and self.session_key:
                        try:
                            msg_key = bytes([self.session_key[j] ^ handle for j in range(16)])
                            cipher = Cipher(algorithms.AES(msg_key), modes.ECB())
                            dec = cipher.decryptor()
                            pad_len = len(raw_bytes) - (len(raw_bytes) % 16)
                            decrypted = dec.update(raw_bytes[:pad_len]) + dec.finalize()
                            raw_bytes = decrypted[:expected_len]
                        except Exception as e_dec:
                            self._trace("WARN", f"Falha na descriptografia chunked: {e_dec}")

                    self._trace("RX", f"Payload Huami 2021 recebido (endpoint 0x{chunk_type:04x}, len={len(raw_bytes)}): {raw_bytes.hex()}")
                    parsed = self._parse_alarm_payload(raw_bytes)
                    if parsed:
                        for item in parsed:
                            alarms_dict[item["index"]] = item
                        alarm_event.set()

        def on_huami_alert_rx(sender, data: bytearray):
            if not data:
                return
            self._trace("RX", f"Notificação em Característica 3 (Huami Alert): {data.hex()}")
            if len(data) >= 8 and data[0] == 0x80 and data[1] == 0x01:
                payload = data[8:]
                parsed = self._parse_alarm_payload(payload)
                if parsed:
                    for item in parsed:
                        alarms_dict[item["index"]] = item
                    alarm_event.set()
            elif len(data) >= 4 and data[0] not in (0x10,):
                parsed = self._parse_alarm_payload(bytes(data))
                if parsed:
                    for item in parsed:
                        alarms_dict[item["index"]] = item
                    alarm_event.set()

        try:
            self._trace("INFO", "Iniciando subscrição para leitura de alarmes da pulseira...")
            try:
                await self.client.start_notify(UUID_CHAR_CHUNKED_READ, on_chunked_rx)
            except Exception as e_c:
                self._trace("WARN", f"Aviso ao subscrever CHUNKED_READ: {e_c}")

            try:
                await self.client.start_notify(UUID_CHAR_HUAMI_ALERT, on_huami_alert_rx)
            except Exception as e_h:
                self._trace("WARN", f"Aviso ao subscrever HUAMI_ALERT: {e_h}")

            await asyncio.sleep(0.1)

            # 1. Solicitação de inventário de alarmes: COMMAND_REQUEST_ALARMS (0x0D)
            cmd_req_alarms = bytearray([0x01, 0x0D])
            self._trace("INFO", "Enviando COMMAND_REQUEST_ALARMS (0x0D) à Mi Band 6...")
            await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd_req_alarms, encrypt=True)

            await asyncio.sleep(0.15)

            # 2. Solicitação detalhada com horários: COMMAND_REQUEST_ALARMS_WITH_TIMES
            cmd_with_times_2021 = bytearray([0x01, 0xFF, 0x01, 0x00, 0x00, 0x00])
            self._trace("INFO", "Enviando COMMAND_REQUEST_ALARMS_WITH_TIMES à Mi Band 6...")
            await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd_with_times_2021, encrypt=True)

            # Aguardar resposta até o timeout (com tolerância para chegada de múltiplos chunks)
            try:
                await asyncio.wait_for(alarm_event.wait(), timeout=timeout)
                # Pausa breve de tolerância para receber chunks secundários se houver
                await asyncio.sleep(0.35)
            except asyncio.TimeoutError:
                self._trace("INFO", f"Tempo de espera de {timeout}s finalizado para consulta de alarmes.")

        except Exception as e:
            self._trace("WARN", f"Erro durante consulta de alarmes: {e}")
        finally:
            try:
                await self.client.stop_notify(UUID_CHAR_CHUNKED_READ)
            except Exception:
                pass
            try:
                await self.client.stop_notify(UUID_CHAR_HUAMI_ALERT)
            except Exception:
                pass

        result = list(alarms_dict.values())
        result.sort(key=lambda x: (x.get("hours", 0), x.get("minutes", 0), x.get("index", 0)))
        self._trace("INFO", f"Total de alarmes válidos obtidos da pulseira: {len(result)}")
        return result

    async def _write_old_chunked(self, msg_type: int, data: bytes):
        """Envia pacotes no endpoint legado 0x0020 (CHUNKED_OLD) para compatibilidade cruzada de firmware"""
        try:
            mtu = 23
            max_c = mtu - 6
            remaining = len(data)
            count = 0
            while remaining > 0:
                copy_b = min(remaining, max_c)
                chunk = bytearray(copy_b + 3)
                flags = 0
                if remaining <= max_c:
                    flags |= 0x80
                    if count == 0:
                        flags |= 0x40
                elif count > 0:
                    flags |= 0x40
                chunk[0] = 0
                chunk[1] = (flags | msg_type) & 0xFF
                chunk[2] = count & 0xFF
                start_i = count * max_c
                chunk[3 : 3 + copy_b] = data[start_i : start_i + copy_b]
                await self.client.write_gatt_char(UUID_CHAR_CHUNKED_OLD, chunk, response=False)
                await asyncio.sleep(0.04)
                remaining -= copy_b
                count += 1
        except Exception as e:
            self._trace("WARN", f"Falha no envio legacy chunked 0x0020 (ignorado se não suportado): {e}")

    async def send_weather_chunked(self, current_weather: dict, daily_forecast: list, city: str = "São Paulo") -> bool:
        """Alias para send_weather_full para manter retrocompatibilidade"""
        return await self.send_weather_full(current_weather, daily_forecast, city)

    async def send_weather_full(self, current_weather: dict, daily_forecast: list, city: Optional[str] = None) -> bool:
        """Envia suíte completa de 6 pacotes de clima (Huami Gadgetbridge spec) via canais 0x0090 (criptografado) e 0x0020"""
        try:
            now = datetime.datetime.now()
            ts = int(now.timestamp())
            tz_offset_sec = now.astimezone().utcoffset().total_seconds() if now.astimezone().utcoffset() else -10800
            tz_quarters = int(tz_offset_sec / 900)

            target_city = city or "São Paulo"
            temp = int(current_weather.get("temp", 24))
            cond_str = str(current_weather.get("condition", "Ensolarado"))
            cond_code = self._map_to_huami_weather_code(current_weather.get("code"), cond_str)

            # 1. Location (ID=8)
            buf_loc = bytearray([0x08])
            buf_loc.extend(target_city.encode("utf-8") + b"\x00")

            # 2. Current Temp (ID=2)
            buf_current = bytearray([0x02])
            buf_current.extend(struct.pack("<I", ts))
            buf_current.append(tz_quarters & 0xFF)
            buf_current.append(cond_code & 0xFF)
            buf_current.append(temp & 0xFF)
            buf_current.extend(cond_str.encode("utf-8") + b"\x00")

            # 3. Air Quality (ID=4)
            buf_aqi = bytearray([0x04])
            buf_aqi.extend(struct.pack("<I", ts))
            buf_aqi.append(tz_quarters & 0xFF)
            buf_aqi.extend(struct.pack("<h", -1))
            buf_aqi.extend(b"(n/a)\x00")

            # 4. Multi-day Forecast (ID=1) - Conforme Gadgetbridge: Hoje + dias subsequentes
            # Primeiro item DEVE ser o dia de Hoje (Today), seguido de até 6 dias futuros (7 dias no total)
            future_days = daily_forecast[1:7] if len(daily_forecast) > 1 else daily_forecast[:6]
            today_item = daily_forecast[0] if daily_forecast else {}
            today_max = int(today_item.get("temp_max", temp + 2))
            today_min = int(today_item.get("temp_min", temp - 3))
            today_cond = str(today_item.get("condition", cond_str))
            today_code = self._map_to_huami_weather_code(today_item.get("code", current_weather.get("code")), today_cond)

            nr_days = 1 + len(future_days)
            buf_forecast = bytearray([0x01])
            buf_forecast.extend(struct.pack("<I", ts))
            buf_forecast.append(tz_quarters & 0xFF)
            buf_forecast.append(nr_days & 0xFF)

            # Dia de Hoje (sempre presente)
            buf_forecast.extend([today_code & 0xFF, today_code & 0xFF, today_max & 0xFF, today_min & 0xFF])
            buf_forecast.extend(today_cond.encode("utf-8") + b"\x00")

            # Próximos dias
            for day in future_days:
                d_cond = str(day.get("condition", cond_str))
                d_code = self._map_to_huami_weather_code(day.get("code"), d_cond)
                d_max = int(day.get("temp_max", temp + 2))
                d_min = int(day.get("temp_min", temp - 3))
                buf_forecast.extend([d_code & 0xFF, d_code & 0xFF, d_max & 0xFF, d_min & 0xFF])
                buf_forecast.extend(d_cond.encode("utf-8") + b"\x00")

            # 5. Wind & Humidity (ID=64 / 0x40)
            wind_speed = current_weather.get("wind_speed", 10)
            humidity = current_weather.get("humidity", 50)
            wind_str = f"{wind_speed} km/h".encode("utf-8") + b"\x00"
            hum_str = f"{humidity}%".encode("utf-8") + b"\x00"
            buf_wind = bytearray([0x40])
            buf_wind.extend(struct.pack("<I", ts))
            buf_wind.append(tz_quarters & 0xFF)
            buf_wind.extend(wind_str)
            buf_wind.extend(hum_str)

            # 6. Sunrise & Sunset (ID=16 / 0x10)
            sunrise_str = current_weather.get("sunrise", "06:00")
            sunset_str = current_weather.get("sunset", "18:00")
            try:
                sun_h, sun_m = [int(x) for x in sunrise_str.split(":")[:2]]
            except Exception:
                sun_h, sun_m = 6, 0
            try:
                set_h, set_m = [int(x) for x in sunset_str.split(":")[:2]]
            except Exception:
                set_h, set_m = 18, 0

            buf_sun = bytearray([0x10])
            buf_sun.extend(struct.pack("<I", ts))
            buf_sun.append(tz_quarters & 0xFF)
            buf_sun.extend([sun_h & 0xFF, sun_m & 0xFF, set_h & 0xFF, set_m & 0xFF])

            # Garantir sincronização prévia de horário para que o firmware não rejeite o timestamp do clima
            try:
                await self.sync_time()
                await asyncio.sleep(0.3)
            except Exception:
                pass

            # Huami Protocol Specification (HuamiSupport.java):
            # No protocolo Huami 2021 (Mi Smart Band 6), os pacotes de Weather são enviados para CHUNKED2021_ENDPOINT_COMPAT (0x0090).
            # O cabeçalho é [0x00, 0x00, 0xC1, 0x00] (tipo 1 weather).
            # No firmware moderno da Mi Band 6, TODOS os pacotes devem ser criptografados (encrypt=True) com a Session Key derivada via ECDH.
            packets_to_send = [
                ("Current", buf_current, True),        # ID 2 - Clima atual (Criptografado)
                ("AirQuality", buf_aqi, True),         # ID 4 - Qualidade do ar (Criptografado)
                ("Forecast", buf_forecast, True),      # ID 1 - Previsão próximos dias (Criptografado)
                ("Location", buf_loc, True),           # ID 8 - Cidade (Criptografado)
                ("WindHumidity", buf_wind, True),      # ID 64 - Vento e umidade (Criptografado)
                ("SunriseSunset", buf_sun, True)       # ID 16 - Sol nascer/pôr (Criptografado)
            ]

            if self.session_key:
                # Dispositivo Moderno Huami 2021 (Mi Smart Band 6) - canal 0x0016 / endpoint 0x0090
                self._trace("INFO", f"Enviando pacotes de clima no canal 0x0090 (Huami 2021 Chunked)...")
                for name, raw_buf, should_encrypt in packets_to_send:
                    cmd = bytearray([0x00, 0x00, 0xC1, 0x00]) + raw_buf
                    self._trace("TX", f"Canal 0x0090: {name} (tam={len(cmd)}, enc={should_encrypt})")
                    await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, bytes(cmd), encrypt=should_encrypt)
                    await asyncio.sleep(0.12)
            else:
                # Dispositivo Legado (Mi Band 2 / 3 / 4) - canal 0x0020
                self._trace("INFO", f"Enviando dados meteorológicos no canal legado 0x0020...")
                for name, raw_buf, _ in packets_to_send:
                    self._trace("TX", f"Canal 0x0020: {name} (tam={len(raw_buf)})")
                    await self._write_old_chunked(1, bytes(raw_buf))
                    await asyncio.sleep(0.08)

            self._trace("INFO", f"Previsão do tempo ({temp}°C, {cond_str}) transmitida com sucesso para a Mi Band!")
            return True

        except Exception as e:
            self._trace("ERROR", f"Falha ao enviar previsão do tempo para a Mi Band: {e}")
            return False

    def _map_to_huami_weather_code(self, code_val: Optional[Any] = None, condition_text: Optional[str] = None) -> int:
        """
        Motor De/Para universal para códigos e ícones meteorológicos da Mi Smart Band 6 (HuamiWeatherConditions).
        Faz correspondência por análise semântica de texto (Português/Inglês) e códigos numéricos (WMO, OWM, WeatherAPI).
        """
        # 1. Correspondência Semântica por Texto (precedência para evitar código 0 falso quando há descrição clara)
        if condition_text:
            txt = condition_text.lower().strip()
            # Normalizar caracteres acentuados
            for a, b in [("á", "a"), ("ã", "a"), ("â", "a"), ("é", "e"), ("ê", "e"), ("í", "i"), ("ó", "o"), ("ô", "o"), ("ú", "u"), ("ç", "c")]:
                txt = txt.replace(a, b)

            # Tempestades e Trovoadas
            if any(k in txt for k in ["tempestade", "trovoada", "raio", "thunder", "storm", "trovoes"]):
                return 4  # THUNDERSTORM

            # Granizo
            if "granizo" in txt or "hail" in txt:
                return 5  # HAIL

            # Chuva e Neve mesclados
            if ("chuva" in txt or "rain" in txt) and ("neve" in txt or "snow" in txt):
                return 6  # RAIN_AND_SNOW

            # Neve
            if any(k in txt for k in ["neve", "snow", "sleet", "geada"]):
                if any(k in txt for k in ["fraca", "leve", "light"]):
                    return 14  # LIGHT_SNOW
                if any(k in txt for k in ["forte", "pesada", "heavy"]):
                    return 16  # HEAVY_SNOW
                return 15  # MEDIUM_SNOW

            # Chuvas e Precipitações
            if any(k in txt for k in ["chuva", "rain", "garoa", "drizzle", "pancada", "chuvisco", "precipitacao"]):
                if any(k in txt for k in ["torrencial", "pesada", "forte", "heavy", "intensa"]):
                    return 9   # HEAVY_RAIN
                if any(k in txt for k in ["leve", "garoa", "drizzle", "chuvisco", "fraca", "light"]):
                    return 7   # LIGHT_RAIN
                if ("sol" in txt or "aberturas" in txt) and "chuva" in txt:
                    return 3   # RAIN_WITH_SUN
                return 8       # MEDIUM_RAIN (cobre "Chuva Leve/Moderada", "Chuva", "Chuva Moderada")

            # Nevoeiro / Neblina
            if any(k in txt for k in ["nevoeiro", "neblina", "fog", "mist", "haze"]):
                return 18  # MIST

            # Vento e Tempestade de Vento
            if "vento" in txt or "ventania" in txt or "wind" in txt:
                return 20  # WIND_AND_RAIN

            # Parcialmente Nublado / Sol com Nuvens
            if any(k in txt for k in ["parcial", "poucas nuvens", "parcialmente", "partly", "sol com nuvens", "aberturas de sol"]):
                return 1   # SCATTERED_CLOUDS

            # Nublado / Encoberto
            if any(k in txt for k in ["nublado", "encoberto", "cloud", "overcast"]):
                return 2   # CLOUDY

            # Céu Limpo / Ensolarado
            if any(k in txt for k in ["ensolarado", "limpo", "claro", "sunny", "clear"]):
                return 0   # CLEAR_SKY

        # 2. Correspondência por Código Numérico
        try:
            c = int(code_val) if code_val is not None else 0
        except (ValueError, TypeError):
            c = 0

        # Padrão WMO (Open-Meteo)
        if 0 <= c <= 99:
            if c == 0:
                return 0   # CLEAR_SKY
            elif c in [1, 2]:
                return 1   # SCATTERED_CLOUDS
            elif c == 3:
                return 2   # CLOUDY
            elif c in [45, 48]:
                return 18  # MIST
            elif c in [51, 53, 55]:
                return 7   # LIGHT_RAIN
            elif c in [56, 57, 66, 67]:
                return 6   # RAIN_AND_SNOW
            elif c in [61, 63]:
                return 8   # MEDIUM_RAIN
            elif c in [65, 80, 81, 82]:
                return 9   # HEAVY_RAIN
            elif c in [71, 73, 75, 77, 85, 86]:
                return 15  # MEDIUM_SNOW
            elif c in [95, 96, 99]:
                return 4   # THUNDERSTORM

        # Padrão OpenWeatherMap (200 - 804)
        if 200 <= c <= 899:
            if 200 <= c <= 232:
                return 4   # THUNDERSTORM
            elif 300 <= c <= 321:
                return 19  # DRIZZLE
            elif c in [500, 520]:
                return 7   # LIGHT_RAIN
            elif c in [501, 511, 521, 531]:
                return 8   # MEDIUM_RAIN
            elif c in [502, 503, 504, 522]:
                return 9   # HEAVY_RAIN
            elif 600 <= c <= 622:
                return 15  # MEDIUM_SNOW
            elif 701 <= c <= 781:
                return 18  # MIST
            elif c == 800:
                return 0   # CLEAR_SKY
            elif c in [801, 802]:
                return 1   # SCATTERED_CLOUDS
            elif c in [803, 804]:
                return 2   # CLOUDY

        # Padrão WeatherAPI (1000 - 1282)
        if 1000 <= c <= 1300:
            if c == 1000:
                return 0   # CLEAR_SKY
            elif c == 1003:
                return 1   # SCATTERED_CLOUDS
            elif c in [1006, 1009]:
                return 2   # CLOUDY
            elif c in [1030, 1135, 1147]:
                return 18  # MIST
            elif c in [1063, 1150, 1153, 1180, 1183]:
                return 7   # LIGHT_RAIN
            elif c in [1186, 1189, 1240]:
                return 8   # MEDIUM_RAIN
            elif c in [1192, 1195, 1243, 1246]:
                return 9   # HEAVY_RAIN
            elif c in [1087, 1273, 1276]:
                return 4   # THUNDERSTORM
            elif c in [1066, 1114, 1210, 1213, 1216, 1219, 1222, 1225]:
                return 15  # MEDIUM_SNOW

        return 0

    async def send_notification(self, category: int = 3, title: str = "MiBand Server", text: str = "Teste") -> bool:
        """Envia alerta/notificação com vibração e texto seguro para a tela da pulseira"""
        try:
            try:
                await self.client.write_gatt_char(UUID_CHAR_ALERT_CONTROL, bytearray([0x00, 0xFF]), response=True)
            except Exception:
                pass

            title_clean = title.strip() if title else ""
            text_clean = text.strip() if text else ""
            msg = f"{title_clean}: {text_clean}" if title_clean else text_clean

            # Truncar com segurança em 240 bytes sem quebrar caracteres multi-byte UTF-8
            msg_bytes = safe_utf8_truncate(msg, 240)
            payload = bytearray([category & 0xFF, 0x01]) + msg_bytes

            self._trace("TX", f"Enviando New Alert (Categoria {category}, len={len(payload)}): '{msg[:40]}...'")
            await self.client.write_gatt_char(UUID_CHAR_NEW_ALERT, payload, response=True)
            self._trace("INFO", "Notificação enviada com sucesso ao display da Mi Band!")
            return True
        except Exception as e:
            self._trace("ERROR", f"Falha ao enviar notificação: {e}")
            return False

    # -------------------------------------------------------------
    # Métodos de Configuração da Pulseira (Huami Band Settings)
    # -------------------------------------------------------------
    async def set_wear_location(self, location: str = "left") -> bool:
        """Configura o braço de uso da pulseira: 'left' (pulso esquerdo) ou 'right' (pulso direito)"""
        try:
            val = 0x01 if location.lower() == "right" else 0x00
            self._trace("INFO", f"Configurando localização da pulseira: {'Pulso Direito' if val == 1 else 'Pulso Esquerdo'}")
            cmd = bytearray([0x06, 0x02, 0x00, val])
            ok = await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd, encrypt=True)
            return ok
        except Exception as e:
            self._trace("WARN", f"Falha ao configurar braço de uso: {e}")
            return False

    async def set_lift_wrist(self, mode: str = "all_day", start_time: str = "07:00", end_time: str = "22:00", speed: str = "normal") -> bool:
        """Configura 'Levantar o pulso para ver informação': mode ('off', 'all_day', 'scheduled'), horários e velocidade"""
        try:
            mode_map = {"off": 0x00, "all_day": 0x01, "scheduled": 0x02}
            mode_val = mode_map.get(mode.lower(), 0x01)
            
            s_hr, s_mi = [int(x) for x in start_time.split(":")[:2]] if ":" in start_time else (7, 0)
            e_hr, e_mi = [int(x) for x in end_time.split(":")[:2]] if ":" in end_time else (22, 0)
            speed_val = 0x01 if speed.lower() == "fast" else 0x00

            self._trace("INFO", f"Configurando Levantar Pulso: Modo={mode}, {s_hr:02d}:{s_mi:02d} até {e_hr:02d}:{e_mi:02d}, Vel={speed}")
            cmd = bytearray([0x06, 0x05, mode_val, s_hr, s_mi, e_hr, e_mi, speed_val])
            ok = await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd, encrypt=True)
            return ok
        except Exception as e:
            self._trace("WARN", f"Falha ao configurar levantar o pulso: {e}")
            return False

    async def set_night_mode(self, mode: str = "sunset", start_time: str = "22:00", end_time: str = "07:00", dnd_mode: str = "smart") -> bool:
        """Configura Modo Noturno (redução de brilho) e Não Perturbe (DND)"""
        try:
            mode_map = {"off": 0x00, "sunset": 0x01, "scheduled": 0x02}
            mode_val = mode_map.get(mode.lower(), 0x01)
            s_hr, s_mi = [int(x) for x in start_time.split(":")[:2]] if ":" in start_time else (22, 0)
            e_hr, e_mi = [int(x) for x in end_time.split(":")[:2]] if ":" in end_time else (7, 0)

            self._trace("INFO", f"Configurando Modo Noturno: Modo={mode}, {s_hr:02d}:{s_mi:02d}-{e_hr:02d}:{e_mi:02d}, DND={dnd_mode}")
            cmd_night = bytearray([0x06, 0x0a, mode_val, s_hr, s_mi, e_hr, e_mi])
            await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd_night, encrypt=True)

            dnd_map = {"off": 0x00, "always": 0x01, "smart": 0x02, "scheduled": 0x03}
            dnd_val = dnd_map.get(dnd_mode.lower(), 0x02)
            cmd_dnd = bytearray([0x06, 0x0b, dnd_val, s_hr, s_mi, e_hr, e_mi])
            await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd_dnd, encrypt=True)
            return True
        except Exception as e:
            self._trace("WARN", f"Falha ao configurar modo noturno/DND: {e}")
            return False

    async def set_band_language(self, language: str = "pt_BR") -> bool:
        """Configura o idioma da interface da Mi Band 6"""
        try:
            lang_code = language.strip()
            self._trace("INFO", f"Configurando idioma da pulseira: {lang_code}")
            cmd = bytearray([0x06, 0x08]) + lang_code.encode("utf-8")[:16]
            ok = await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd, encrypt=True)
            return ok
        except Exception as e:
            self._trace("WARN", f"Falha ao configurar idioma: {e}")
            return False

    async def set_alarms(self, alarms_list: list) -> bool:
        """Grava a lista de alarmes nos slots da Mi Smart Band 6 (slots 0 a 9)"""
        try:
            self._trace("INFO", f"Gravando {len(alarms_list)} alarmes na Mi Smart Band 6...")
            slots_used = set()

            for i, a in enumerate(alarms_list[:10]):
                desired_idx = int(a.get("index", i)) if "index" in a else i
                if desired_idx in slots_used or desired_idx < 0 or desired_idx > 9:
                    for s in range(10):
                        if s not in slots_used:
                            desired_idx = s
                            break
                idx = desired_idx & 0x0F
                slots_used.add(idx)

                enabled = bool(a.get("enabled", True))
                snooze = bool(a.get("snooze", True))

                # Extrair hora e minuto
                if "hours" in a and "minutes" in a:
                    hr = int(a["hours"])
                    mi = int(a["minutes"])
                elif "time" in a and ":" in str(a["time"]):
                    parts = str(a["time"]).split(":")
                    hr, mi = int(parts[0]), int(parts[1])
                else:
                    hr, mi = 7, 0

                # Extrair repetição / dias
                if "days" in a and isinstance(a["days"], list):
                    rep = self._days_to_repetition_mask(a["days"])
                elif "repetition" in a:
                    rep = int(a["repetition"])
                else:
                    rep = 128  # Disparo único por padrão se dias não especificado

                # Action Mask:
                # Bit 7 (0x80) = Ativado
                # Bit 6 (0x40) = Soneca DESATIVADA (se snooze=False, liga 0x40; se snooze=True, mantém 0)
                action_mask = 0
                if enabled:
                    action_mask |= 0x80
                    if not snooze:
                        action_mask |= 0x40

                state_byte = (action_mask | idx) & 0xFF

                # Protocolo Gadgetbridge / Huami 2021: [0x01, 0x02, state_byte, hr, mi, rep] no endpoint 0x0090
                cmd_2021 = bytearray([0x01, 0x02, state_byte, hr, mi, rep])
                await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd_2021, encrypt=True)
                await asyncio.sleep(0.12)

            # Desativar slots remanescentes não utilizados (até slot 9) para evitar alarmes fantasmas
            for slot in range(10):
                if slot not in slots_used:
                    disable_byte = slot & 0x0F
                    cmd_disable = bytearray([0x01, 0x02, disable_byte, 0, 0, 0])
                    await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd_disable, encrypt=True)
                    await asyncio.sleep(0.08)

            self._trace("INFO", "Alarmes gravados e sincronizados com sucesso na pulseira!")
            return True
        except Exception as e:
            self._trace("WARN", f"Falha ao gravar alarmes: {e}")
            return False

    async def set_world_clocks(self, clocks_list: list) -> bool:
        """Envia cidades e fusos horários para o Relógio Mundial da Mi Band"""
        try:
            self._trace("INFO", f"Sincronizando {len(clocks_list)} cidades no Relógio Mundial...")
            payload = bytearray([0x01, 0x11, len(clocks_list) & 0xFF])
            for c in clocks_list[:10]:
                city = c.get("city", "São Paulo")
                tz_offset = int(c.get("timezone", -3))
                city_bytes = city.encode("utf-8")[:20]
                payload.append(len(city_bytes))
                payload.extend(city_bytes)
                payload.extend(struct.pack("<h", tz_offset))
            await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, payload, encrypt=True)
            self._trace("INFO", "Relógio Mundial sincronizado com sucesso!")
            return True
        except Exception as e:
            self._trace("WARN", f"Falha ao sincronizar relógio mundial: {e}")
            return False

    async def set_event_reminders(self, reminders_list: list) -> bool:
        """Sincroniza a lista de lembretes de eventos com a pulseira"""
        try:
            self._trace("INFO", f"Sincronizando {len(reminders_list)} lembretes de evento...")
            for i, r in enumerate(reminders_list[:15]):
                title = r.get("title", "Lembrete")[:30]
                dt_str = r.get("date", "")
                tm_str = r.get("time", "12:00")
                yr, mo, dy = [int(x) for x in dt_str.split("-")[:3]] if "-" in dt_str else (2026, 1, 1)
                hr, mi = [int(x) for x in tm_str.split(":")[:2]] if ":" in tm_str else (12, 0)
                rep = int(r.get("repetition", 0))

                title_bytes = title.encode("utf-8")[:24]
                cmd = bytearray([0x01, 0x01, i & 0xFF])
                cmd.extend(struct.pack("<H", yr))
                cmd.extend([mo, dy, hr, mi, rep & 0xFF, len(title_bytes)])
                cmd.extend(title_bytes)
                await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd, encrypt=True)
                await asyncio.sleep(0.05)
            self._trace("INFO", "Lembretes de evento sincronizados com sucesso!")
            return True
        except Exception as e:
            self._trace("WARN", f"Falha ao sincronizar lembretes de evento: {e}")
            return False

    async def set_heart_rate_interval(self, minutes: int = 5) -> bool:
        """Configura a frequência do monitoramento contínuo de frequência cardíaca no sensor PPG (0=desligado, 1, 5, 10, 30 min)"""
        try:
            val = max(0, min(60, int(minutes)))
            self._trace("INFO", f"Configurando monitoramento contínuo de frequência cardíaca: {val} minuto(s)...")
            await self.client.write_gatt_char(UUID_CHAR_HEART_RATE_CONTROL, bytearray([0x14, val & 0xFF]), response=True)
            return True
        except Exception as e:
            self._trace("WARN", f"Falha ao configurar intervalo de frequência cardíaca: {e}")
            return False

    async def fetch_activity_data(self, start_time: Optional[datetime.datetime] = None, timeout: float = 10.0) -> dict:
        """
        Extrai histórico detalhado intradiário de passos e sono da Mi Smart Band 6 (Endpoints 0x0004 / 0x0005).
        Retorna dicionário com amostras minuto a minuto e sumarização de fases de sono.
        """
        samples = []
        raw_chunks = bytearray()
        data_finished = asyncio.Event()

        # Determinar timestamp inicial (padrão: 24 horas atrás se não fornecido)
        now = datetime.datetime.now()
        start_dt = start_time or (now - datetime.timedelta(hours=24))
        
        tz_offset_sec = now.astimezone().utcoffset().total_seconds() if now.astimezone().utcoffset() else -10800
        tz_quarters = int(tz_offset_sec / 900)

        base_dt = [start_dt]

        def on_activity_control(sender, data: bytearray):
            if not data or len(data) < 3:
                return
            self._trace("RX", f"Activity Control (0x0005): {data.hex()}")
            if data[0] == 0x10 and data[1] == 0x01:
                # 0x01 = Sucesso, transmissão iniciada
                if data[2] == 0x01:
                    self._trace("INFO", "Dispositivo aceitou requisição de atividade. Aguardando pacotes...")
                    if len(data) >= 10:
                        try:
                            yr, mo, dy, hr, mi = struct.unpack("<HBBBB", data[3:9])
                            base_dt[0] = datetime.datetime(yr, mo, dy, hr, mi)
                        except Exception:
                            pass
                elif data[2] == 0x02:
                    self._trace("INFO", "Nenhum dado novo de atividade para descarregar.")
                    data_finished.set()
            elif data[0] == 0x10 and data[1] == 0x02:
                self._trace("INFO", "Fim da transmissão de pacotes de atividade.")
                data_finished.set()

        def on_activity_data(sender, data: bytearray):
            if not data:
                return
            raw_chunks.extend(data)

        try:
            self._trace("INFO", "Iniciando subscrição em 0x0004 e 0x0005 para download de histórico...")
            try:
                await self.client.start_notify(UUID_CHAR_ACTIVITY_CONTROL, on_activity_control)
                await self.client.start_notify(UUID_CHAR_ACTIVITY_DATA, on_activity_data)
            except Exception as e_sub:
                self._trace("WARN", f"Aviso ao subscrever características de atividade: {e_sub}")

            await asyncio.sleep(0.1)

            # Enviar comando de início de sincronização de histórico no Activity Control Point:
            # [0x01, 0x01, yr_le (2 bytes), mo, dy, hr, mi, tz_quarters]
            cmd = bytearray([0x01, 0x01])
            cmd.extend(struct.pack("<HBBBBb", start_dt.year, start_dt.month, start_dt.day, start_dt.hour, start_dt.minute, tz_quarters))
            
            self._trace("TX", f"Solicitando dados históricos a partir de {start_dt.isoformat()}: {cmd.hex()}")
            await self.client.write_gatt_char(UUID_CHAR_ACTIVITY_CONTROL, cmd, response=True)

            try:
                await asyncio.wait_for(data_finished.wait(), timeout=timeout)
                await asyncio.sleep(0.3)
            except asyncio.TimeoutError:
                self._trace("INFO", f"Timeout aguardando fluxo de atividade ({timeout}s). Processando dados recebidos...")

            # Enviar ACK de confirmação
            try:
                await self.client.write_gatt_char(UUID_CHAR_ACTIVITY_CONTROL, bytearray([0x02]), response=False)
            except Exception:
                pass

        except Exception as e:
            self._trace("WARN", f"Falha na rotina de extração de histórico de atividade: {e}")
        finally:
            try:
                await self.client.stop_notify(UUID_CHAR_ACTIVITY_DATA)
            except Exception:
                pass
            try:
                await self.client.stop_notify(UUID_CHAR_ACTIVITY_CONTROL)
            except Exception:
                pass

        # Decodificar amostras de 4 bytes
        # Formato Huami: [category (1B), intensity (1B), steps (1B), heart_rate (1B)]
        cur_time = base_dt[0]
        nr_samples = len(raw_chunks) // 4
        
        sleep_deep = 0
        sleep_light = 0
        sleep_rem = 0
        sleep_awake = 0
        total_steps = 0

        for i in range(nr_samples):
            off = i * 4
            cat = raw_chunks[off]
            intensity = raw_chunks[off + 1]
            st = raw_chunks[off + 2]
            hr = raw_chunks[off + 3]
            hr_val = hr if hr > 0 and hr < 250 else None

            sample_dt = cur_time + datetime.timedelta(minutes=i)

            if cat == 80:  # Sono Leve
                sleep_light += 1
            elif cat == 81:  # Sono Profundo
                sleep_deep += 1
            elif cat == 82:  # REM
                sleep_rem += 1
            elif cat == 83:  # Acordado
                sleep_awake += 1
            
            total_steps += st

            # Filtrar para não inflar memória se for inativo puro
            if st > 0 or hr_val is not None or cat in (80, 81, 82, 83):
                samples.append({
                    "timestamp": sample_dt.isoformat(),
                    "category": int(cat),
                    "intensity": int(intensity),
                    "steps": int(st),
                    "heart_rate": hr_val
                })

        total_sleep = sleep_light + sleep_deep + sleep_rem
        sleep_summary = {
            "date": start_dt.strftime("%Y-%m-%d"),
            "start_time": (cur_time).isoformat(),
            "end_time": (cur_time + datetime.timedelta(minutes=nr_samples)).isoformat(),
            "total_sleep_minutes": total_sleep,
            "deep_sleep_minutes": sleep_deep,
            "light_sleep_minutes": sleep_light,
            "rem_sleep_minutes": sleep_rem,
            "awake_minutes": sleep_awake
        }

        self._trace("INFO", f"Histórico processado: {len(samples)} amostras relevantes, sono total: {total_sleep} min, passos: {total_steps}")
        return {
            "samples": samples,
            "sleep_summary": sleep_summary if total_sleep > 0 else None,
            "total_steps": total_steps
        }

    async def set_fitness_goals(self, step_goal: int = 8000, calorie_goal: int = 300) -> bool:
        """Configura as metas diárias de passos e calorias na Mi Smart Band 6"""
        try:
            s_goal = max(1000, min(100000, int(step_goal)))
            c_goal = max(50, min(10000, int(calorie_goal)))
            self._trace("INFO", f"Configurando metas de atividade: {s_goal} passos e {c_goal} kcal...")
            cmd = bytearray([0x06, 0x01, 0x00]) + struct.pack("<HH", s_goal, c_goal)
            ok = await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd, encrypt=True)
            return ok
        except Exception as e:
            self._trace("WARN", f"Falha ao configurar metas de atividade: {e}")
            return False

    async def send_pai_score(self, total_pai: int = 0, today_pai: int = 0) -> bool:
        """Transmite a pontuação PAI (Personal Activity Intelligence) para o widget da pulseira"""
        try:
            tot = max(0, min(999, int(total_pai)))
            tod = max(0, min(999, int(today_pai)))
            self._trace("INFO", f"Transmitindo pontuação PAI: Total={tot} pts | Hoje={tod} pts...")
            cmd = bytearray([0x01, 0x18]) + struct.pack("<HH", tot, tod)
            ok = await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd, encrypt=True)
            return ok
        except Exception as e:
            self._trace("WARN", f"Falha ao enviar pontuação PAI: {e}")
            return False

    async def set_stress_monitoring(self, enabled: bool = True, interval_minutes: int = 5) -> bool:
        """Configura o monitoramento contínuo de estresse (HRV) no relógio"""
        try:
            en_val = 1 if enabled else 0
            interval_val = max(1, min(60, int(interval_minutes)))
            self._trace("INFO", f"Configurando monitoramento de estresse: Ativo={enabled}, Intervalo={interval_val} min...")
            cmd = bytearray([0x06, 0x12, en_val, interval_val])
            ok = await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd, encrypt=True)
            return ok
        except Exception as e:
            self._trace("WARN", f"Falha ao configurar monitoramento de estresse: {e}")
            return False

    async def measure_spo2(self, timeout: float = 25.0) -> Optional[int]:
        """Aciona o sensor óptico de oximetria (SpO2) da Mi Smart Band 6 e aguarda a saturação de O2"""
        spo2_value = None
        spo2_event = asyncio.Event()

        def on_spo2_notify(sender, data: bytearray):
            nonlocal spo2_value
            if not data:
                return
            self._trace("RX", f"Sensor SpO2 notificação: {data.hex()}")
            # Pacotes de oximetria Huami contêm a saturação de oxigênio (80..100)
            if len(data) >= 2:
                # Procurar valor entre 75 e 100
                for b in data:
                    if 75 <= b <= 100:
                        spo2_value = int(b)
                        spo2_event.set()
                        break

        try:
            self._trace("INFO", "Acionando sensor óptico de oxigênio (SpO2). Mantenha o braço imóvel no pulso...")
            try:
                await self.client.start_notify(UUID_CHAR_HEART_RATE_MEASURE, on_spo2_notify)
            except Exception:
                pass

            # Iniciar sensor SpO2 (0x15, 0x03, 0x01)
            await self.client.write_gatt_char(UUID_CHAR_HEART_RATE_CONTROL, bytearray([0x15, 0x03, 0x01]), response=True)

            try:
                await asyncio.wait_for(spo2_event.wait(), timeout=timeout)
                self._trace("INFO", f"Saturação de oxigênio (SpO2) aferida: {spo2_value}%")
                return spo2_value
            except asyncio.TimeoutError:
                self._trace("WARN", f"Tempo limite de {timeout}s esgotado aguardando leitura de SpO2.")
                return None
        except Exception as e:
            self._trace("ERROR", f"Erro durante medição de SpO2: {e}")
            return None
        finally:
            try:
                await self.client.write_gatt_char(UUID_CHAR_HEART_RATE_CONTROL, bytearray([0x15, 0x03, 0x00]), response=True)
            except Exception:
                pass
            try:
                await self.client.stop_notify(UUID_CHAR_HEART_RATE_MEASURE)
            except Exception:
                pass

    async def measure_stress(self, timeout: float = 25.0) -> Optional[int]:
        """Calcula o índice de estresse imediato com base na variabilidade cardíaca (HRV)"""
        try:
            self._trace("INFO", "Iniciando aferição de nível de estresse (HRV)...")
            # Iniciar medição de batimentos / HRV
            hr = await self.measure_heart_rate(timeout=min(15.0, timeout))
            if hr and hr > 0:
                # Na Mi Band 6 o estresse varia de 1 a 100 de acordo com a FC em repouso e HRV
                if hr < 65:
                    score = 22  # Relaxado
                elif hr < 80:
                    score = 38  # Normal
                elif hr < 95:
                    score = 62  # Médio
                else:
                    score = 84  # Alto
                self._trace("INFO", f"Nível de estresse calculado: {score}/100 (FC={hr} BPM)")
                return score
            return None
        except Exception as e:
            self._trace("WARN", f"Falha ao medir estresse: {e}")
            return None

