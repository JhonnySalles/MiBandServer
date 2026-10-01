from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.logger import logger, setup_logging, RequestLoggingMiddleware
from app.core.database import init_db, engine, DeviceConfig, IntegrationConfig, SyncHistory
from app.core.cache import cache
from app.core.scheduler import start_scheduler
from app.api.routes import router
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
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware de log estruturado para todas as requisições HTTP
app.add_middleware(RequestLoggingMiddleware)

app.include_router(router, prefix="/api")
