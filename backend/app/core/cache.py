import json
from typing import Any, Optional
import redis
from app.core.config import settings
from app.core.logger import logger

class CacheService:
    def __init__(self):
        self._client: Optional[redis.Redis] = None
        self._is_available = False
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
            self._memory_fallback = {}

    @property
    def is_connected(self) -> bool:
        if self._client:
            try:
                return bool(self._client.ping())
            except Exception:
                return False
        return False

    def get(self, key: str) -> Optional[Any]:
        if self._client and self.is_connected:
            try:
                val = self._client.get(key)
                if val is not None:
                    try:
                        return json.loads(val)
                    except Exception:
                        return val
                return None
            except Exception as e:
                logger.error(f"Erro ao ler do Redis ({key}): {e}")
        
        # Fallback local em memória
        if hasattr(self, "_memory_fallback"):
            return self._memory_fallback.get(key)
        return None

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
        try:
            serialized = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
            if self._client and self.is_connected:
                if ttl_seconds:
                    self._client.setex(key, ttl_seconds, serialized)
                else:
                    self._client.set(key, serialized)
                return True
        except Exception as e:
            logger.error(f"Erro ao salvar no Redis ({key}): {e}")
        
        # Fallback local
        if not hasattr(self, "_memory_fallback"):
            self._memory_fallback = {}
        self._memory_fallback[key] = value
        return True

    def delete(self, key: str) -> bool:
        if self._client and self.is_connected:
            try:
                self._client.delete(key)
                return True
            except Exception:
                pass
        if hasattr(self, "_memory_fallback") and key in self._memory_fallback:
            del self._memory_fallback[key]
        return True

cache = CacheService()
