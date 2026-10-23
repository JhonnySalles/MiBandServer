from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.logger import logger, setup_logging, RequestLoggingMiddleware
from app.core.database import init_db, engine, DeviceConfig, IntegrationConfig, SyncHistory
from app.core.cache import cache
from app.core.scheduler import start_scheduler
from app.api.routes import router
from app.api.test_routes import router as test_router
from app.api.band_settings_routes import router as band_settings_router
from sqlmodel import Session, select

# Configurar logging centralizado
setup_logging()

def bootstrap_redis():
    """Pré-carrega configurações essenciais e últimas sincronizações no Redis para proteger o SD Card"""
    try:
        with Session(engine) as session:
            # 1. Carregar dispositivos
            devices = session.exec(select(DeviceConfig)).all()
            for dev in devices:
                cache.set(f"device:{dev.mac_address}:config", dev.model_dump(mode="json"))
                if dev.last_sync_time:
                    cache.set(f"device:{dev.mac_address}:last_sync", dev.last_sync_time.isoformat())
                else:
                    # Tentar buscar do último histórico de sucesso
                    last_success = session.exec(
                        select(SyncHistory)
                        .where(SyncHistory.device_mac == dev.mac_address, SyncHistory.status == "SUCCESS")
                        .order_by(SyncHistory.timestamp.desc())
                    ).first()
                    if last_success:
                        cache.set(f"device:{dev.mac_address}:last_sync", last_success.timestamp.isoformat())

            # 2. Carregar integrações
            integration = session.exec(select(IntegrationConfig)).first()
            if integration:
                cache.set("system:integration:config", integration.model_dump(mode="json"))

        logger.info("Bootstrap do Redis concluído com sucesso!")
    except Exception as e:
        logger.warning(f"Aviso no bootstrap do Redis: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicialização do banco, bootstrap do Redis e agendador
    init_db()
    bootstrap_redis()
    start_scheduler()
    yield


app = FastAPI(
    title="MiBand 6 Server API",
    description="API para sincronização de dados e envio de informações para Xiaomi Mi Band 6",
    version="1.0.0",
    lifespan=lifespan
)

# Permitir CORS para que o frontend possa se comunicar livremente de qualquer porta/IP
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware de log estruturado para todas as requisições HTTP
app.add_middleware(RequestLoggingMiddleware)

# Middleware opcional de autenticação por API Key (ativo apenas se API_KEY estiver no ambiente)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from app.core.config import settings

class OptionalApiKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        api_key = settings.API_KEY
        if api_key and request.url.path.startswith("/api/"):
            if request.url.path in ("/api/status", "/api/docs", "/api/openapi.json", "/api/redoc") or request.method == "OPTIONS":
                return await call_next(request)

            client_key = request.headers.get("X-API-Key")
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                client_key = client_key or auth_header[7:].strip()

            if client_key != api_key:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Chave de API não fornecida ou inválida (X-API-Key ou Bearer token requerido)."}
                )
        return await call_next(request)

app.add_middleware(OptionalApiKeyMiddleware)

app.include_router(router, prefix="/api")
app.include_router(test_router, prefix="/api/test")
app.include_router(band_settings_router, prefix="/api/band")
