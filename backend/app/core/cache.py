import json
import fnmatch
from typing import Any, Optional
import redis
from app.core.config import settings
from app.core.logger import logger

class CacheService:
    def __init__(self):
        self._client: Optional[redis.Redis] = None
        self._is_available = False
        self._memory_fallback: dict = {}
        self._connect()

    def _connect(self):
        try:
            self._client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True, socket_connect_timeout=2)
            self._client.ping()
            self._is_available = True
            logger.info("Conectado ao Redis com sucesso (cache em memória RAM ativo).")
        except Exception as e:
            self._is_available = False
            self._client = None
            logger.warning(f"Redis indisponível ({e}). Operando com fallback em memória local volátil.")

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._is_available

    def get(self, key: str) -> Optional[Any]:
        if self._client and self._is_available:
            try:
                val = self._client.get(key)
                if val is not None:
                    try:
                        return json.loads(val)
                    except Exception:
                        return val
                return None
            except redis.ConnectionError:
                self._is_available = False
                logger.warning(f"Perda de conexão com Redis ao ler ({key}). Alternando para memória local.")
            except Exception as e:
                logger.error(f"Erro ao ler do Redis ({key}): {e}")
        
        # Fallback local em memória
        return self._memory_fallback.get(key)

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        # Atualiza sempre fallback local
        self._memory_fallback[key] = value

        if self._client and self._is_available:
            try:
                serialized = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
                if ttl_seconds:
                    self._client.setex(key, ttl_seconds, serialized)
                else:
                    self._client.set(key, serialized)
                return True
            except redis.ConnectionError:
                self._is_available = False
                logger.warning(f"Perda de conexão com Redis ao salvar ({key}). Alternando para memória local.")
            except Exception as e:
                logger.error(f"Erro ao salvar no Redis ({key}): {e}")
        
        return True

    def delete(self, key: str) -> bool:
        if "*" in key or "?" in key:
            return self.delete_pattern(key)

        if self._client and self._is_available:
            try:
                self._client.delete(key)
            except redis.ConnectionError:
                self._is_available = False
            except Exception:
                pass

        if key in self._memory_fallback:
            del self._memory_fallback[key]
        return True

    def delete_pattern(self, pattern: str) -> bool:
        """Remove todas as chaves correspondentes a um padrão com wildcard (ex: weather:forecast:*)"""
        deleted_count = 0
        if self._client and self._is_available:
            try:
                matching_keys = list(self._client.scan_iter(match=pattern, count=100))
                if matching_keys:
                    self._client.delete(*matching_keys)
                    deleted_count += len(matching_keys)
            except redis.ConnectionError:
                self._is_available = False
            except Exception as e:
                logger.error(f"Erro ao deletar padrão no Redis ({pattern}): {e}")

        # Limpa também no fallback em memória
        keys_to_del = [k for k in self._memory_fallback if fnmatch.fnmatch(k, pattern)]
        for k in keys_to_del:
            del self._memory_fallback[k]
        deleted_count += len(keys_to_del)

        logger.debug(f"Cache invalidado para o padrão '{pattern}' ({deleted_count} chaves).")
        return True

cache = CacheService()
