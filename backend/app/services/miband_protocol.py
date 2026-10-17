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

# UUIDs de Frequência Cardíaca (Padrão BLE Heart Rate Service)
UUID_SERVICE_HEART_RATE = "0000180d-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HEART_RATE_MEASURE = "00002a37-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HEART_RATE_CONTROL = "00002a39-0000-1000-8000-00805f9b34fb"

# UUIDs de Alerta e Vibração Física
UUID_CHAR_ALERT = "00002a06-0000-1000-8000-00805f9b34fb"
UUID_CHAR_NEW_ALERT = "00002a46-0000-1000-8000-00805f9b34fb"
UUID_CHAR_ALERT_CONTROL = "00002a44-0000-1000-8000-00805f9b34fb"
UUID_CHAR_HUAMI_ALERT = "00000003-0000-3512-2118-0009af100700"

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

                # Derivar chave de sessão AES
                session_key = bytearray(16)
                for i in range(16):
                    session_key[i] = shared_secret[i + 8] ^ self.auth_key[i]
                self.session_key = bytes(session_key)

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
        """Dispara vibração física comprovada na Mi Smart Band 6"""
        # Habilitar notificações de novos alertas no Control Point (0x2A44)
        try:
            await self.client.write_gatt_char(UUID_CHAR_ALERT_CONTROL, bytearray([0x00, 0xFF]), response=True)
        except Exception:
            pass

        vibrated = False
        for i in range(max(1, count)):
            # 1. New Alert (0x2A46) Categoria 3 (Chamada) - vibração física comprovada na tela e pulso
            try:
                alert_payload = bytearray([0x03, 0x01]) + text.encode("utf-8", errors="ignore")[:18]
                await self.client.write_gatt_char(UUID_CHAR_NEW_ALERT, alert_payload, response=True)
                vibrated = True
                logger.info(f"Vibração disparada com sucesso na Mi Band via New Alert (0x2A46) ({i + 1}/{count})!")
            except Exception as e1:
                logger.warning(f"Falha ao enviar New Alert: {e1}")

            # 2. Fallbacks de alerta simultâneos
            try:
                await self.client.write_gatt_char(UUID_CHAR_ALERT, bytearray([0x02]), response=False)
                await self.client.write_gatt_char(UUID_CHAR_HUAMI_ALERT, bytearray([0x02]), response=False)
                vibrated = True
            except Exception:
                pass

            if i < count - 1:
                await asyncio.sleep(1.5)
        return vibrated

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

    async def measure_heart_rate(self, timeout: float = 25.0) -> Optional[int]:
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
            # 1. Parar medição contínua
            try:
                await self.client.write_gatt_char(UUID_CHAR_HEART_RATE_CONTROL, bytearray([0x15, 0x01, 0x00]), response=True)
            except Exception:
                pass
            # 2. Parar medição manual anterior
            try:
                await self.client.write_gatt_char(UUID_CHAR_HEART_RATE_CONTROL, bytearray([0x15, 0x02, 0x00]), response=True)
            except Exception:
                pass
            # 3. Iniciar medição manual
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

    async def request_alarms(self, timeout: float = 6.0) -> list:
        """Consulta alarmes configurados na Mi Band via canal de configuração Huami (0x0090)"""
        alarms_list = []
        alarm_event = asyncio.Event()

        def on_alarm_notification(sender, data: bytearray):
            if not data or len(data) < 4:
                return
            self._trace("RX", f"Resposta de configuração recebida: {data.hex()[:30]}...")
            try:
                if len(data) >= 8:
                    nr = data[8] if len(data) > 8 and data[0] == 0x10 else (len(data) - 1) // 4
                    for i in range(min(nr, 10)):
                        offset = 9 + i if data[0] == 0x10 else (i * 4 + 1)
                        if offset + 3 < len(data):
                            alarm_raw = data[offset]
                            idx = alarm_raw & 0x0F
                            enabled = bool(alarm_raw & 0x80 or alarm_raw & 0x10)
                            hr = data[offset + 1] if offset + 1 < len(data) else 0
                            mi = data[offset + 2] if offset + 2 < len(data) else 0
                            rep = data[offset + 3] if offset + 3 < len(data) else 0
                            alarms_list.append({
                                "index": idx,
                                "time": f"{hr:02d}:{mi:02d}",
                                "enabled": enabled,
                                "repetition": rep
                            })
                    alarm_event.set()
            except Exception as e:
                self._trace("WARN", f"Erro no parsing de alarmes: {e}")

        try:
            self._trace("INFO", "Solicitando lista de alarmes à pulseira...")
            cmd = bytearray([0x01, 0x02])
            await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, cmd, encrypt=True)
            await asyncio.wait_for(alarm_event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self._trace("INFO", "Consulta de alarmes finalizada.")
        except Exception as e:
            self._trace("WARN", f"Aviso ao consultar alarmes: {e}")

        return alarms_list

    async def send_weather_chunked(self, current_weather: dict, daily_forecast: list, city: str = "São Paulo") -> bool:
        """Envia pacotes meteorológicos formatados no padrão Huami 2021 (Mi Band 6)"""
        try:
            now = datetime.datetime.now()
            ts = int(now.timestamp())
            tz_offset_sec = now.astimezone().utcoffset().total_seconds() if now.astimezone().utcoffset() else -10800
            tz_quarters = int(tz_offset_sec / 900)

            # 1. Pacote 2: Clima Atual
            temp = int(current_weather.get("temp", 24))
            cond_str = str(current_weather.get("condition", "Ensolarado"))
            cond_code = self._map_to_huami_weather_code(current_weather.get("code", 0))

            pkg2 = bytearray([0x00, 0x00, 0xC1, 0x00, 0x02])
            pkg2.extend(struct.pack("<I", ts))
            pkg2.append(tz_quarters & 0xFF)
            pkg2.append(cond_code & 0xFF)
            pkg2.append(temp & 0xFF)
            pkg2.extend(cond_str.encode("utf-8") + b"\x00")

            self._trace("INFO", f"Enviando Clima Atual (Pacote 2): {temp}°C, {cond_str} (código={cond_code})")
            await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, bytes(pkg2), encrypt=False)
            await asyncio.sleep(0.15)

            # 2. Pacote 1: Previsão dos Próximos Dias
            forecast_items = daily_forecast[:5] if daily_forecast else []
            nr_days = len(forecast_items) + 1

            pkg1 = bytearray([0x00, 0x00, 0xC1, 0x00, 0x01])
            pkg1.extend(struct.pack("<I", ts))
            pkg1.append(tz_quarters & 0xFF)
            pkg1.append(nr_days & 0xFF)

            # Dia de Hoje no forecast
            pkg1.append(cond_code & 0xFF)
            pkg1.append(cond_code & 0xFF)
            pkg1.append((temp + 2) & 0xFF)
            pkg1.append((temp - 3) & 0xFF)
            pkg1.extend(cond_str.encode("utf-8") + b"\x00")

            # Próximos dias
            for day in forecast_items:
                d_code = self._map_to_huami_weather_code(day.get("code", 0))
                d_max = int(day.get("temp_max", temp + 2))
                d_min = int(day.get("temp_min", temp - 3))
                d_cond = str(day.get("condition", "Ensolarado"))
                pkg1.append(d_code & 0xFF)
                pkg1.append(d_code & 0xFF)
                pkg1.append(d_max & 0xFF)
                pkg1.append(d_min & 0xFF)
                pkg1.extend(d_cond.encode("utf-8") + b"\x00")

            self._trace("INFO", f"Enviando Previsão Estendida ({nr_days} dias, criptografado)...")
            await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, bytes(pkg1), encrypt=True)
            await asyncio.sleep(0.15)

            # 3. Pacote 8: Localização
            pkg8 = bytearray([0x00, 0x00, 0xC1, 0x00, 0x08])
            pkg8.extend(city.encode("utf-8") + b"\x00")
            self._trace("INFO", f"Enviando Cidade: {city}")
            await self._write_chunked_2021(CHUNKED2021_ENDPOINT_COMPAT, bytes(pkg8), encrypt=True)

            self._trace("INFO", "Previsão do tempo enviada com sucesso à Mi Band!")
            return True
        except Exception as e:
            self._trace("ERROR", f"Falha ao enviar previsão do tempo: {e}")
            return False

    def _map_to_huami_weather_code(self, wmo_code: int) -> int:
        """Mapeia código WMO Open-Meteo para código de ícone Huami Amazfit/MiBand"""
        if wmo_code == 0:
            return 0  # Ensolarado / Céu limpo
        elif wmo_code in [1, 2]:
            return 1  # Parcialmente nublado
        elif wmo_code == 3:
            return 2  # Nublado
        elif wmo_code in [45, 48]:
            return 6  # Neblina / Nevoeiro
        elif wmo_code in [51, 53, 55, 61, 63]:
            return 3  # Chuva fraca / moderada
        elif wmo_code in [65, 80, 81, 82]:
            return 4  # Chuva forte / pancadas
        elif wmo_code in [71, 73, 75]:
            return 5  # Neve
        elif wmo_code in [95, 96, 99]:
            return 7  # Tempestade / Trovoadas
        return 0

    async def send_notification(self, category: int = 3, title: str = "MiBand Server", text: str = "Teste") -> bool:
        """Envia alerta/notificação com vibração para a tela da pulseira"""
        try:
            try:
                await self.client.write_gatt_char(UUID_CHAR_ALERT_CONTROL, bytearray([0x00, 0xFF]), response=True)
            except Exception:
                pass

            msg = f"{title}: {text}" if title else text
            payload = bytearray([category & 0xFF, 0x01]) + msg.encode("utf-8", errors="ignore")[:36]
            self._trace("TX", f"Enviando New Alert (Categoria {category}): '{msg}'")
            await self.client.write_gatt_char(UUID_CHAR_NEW_ALERT, payload, response=True)
            self._trace("INFO", "Notificação enviada com sucesso ao display da Mi Band!")
            return True
        except Exception as e:
            self._trace("ERROR", f"Falha ao enviar notificação: {e}")
            return False
