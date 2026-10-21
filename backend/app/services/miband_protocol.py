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
            # Primeiro item DEVE ser o dia de Hoje (Today), seguido de até 4 dias futuros
            future_days = daily_forecast[1:5] if len(daily_forecast) > 1 else daily_forecast[:4]
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
